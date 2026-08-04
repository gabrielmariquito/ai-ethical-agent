from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .conditions import (
    Condition,
    ConditionError,
    condition_from_dict,
    register_condition_type,
)
from .provenance import ConfigArtifact
from .types import Evidence

# Camada de frames, eixo de saída: marca de recusa.
#
# O mecanismo é o do ConText (Chapman/Harkema): uma lista de gatilhos, cada um
# com **direção** e **alcance**, e o que cai dentro do escopo ativo é lido sob
# aquele contexto em vez de ao pé da letra. Algoritmo publicado e validado, não
# invenção da casa -- a citação está no README.
#
# O recorte aqui é um eixo só. Nos 117 casos do BeaverTails `tune`, que são
# `stage: "output"`, o que separa DENY de ALLOW não é pedir x falar sobre, e sim
# recusar x cumprir -- e a família `recusa` casa 1 DENY contra 10 ALLOW. Os ALLOW
# carregam vocabulário perigoso *porque estão recusando o pedido*.

MAX_ESCOPOS = 50

# O escopo nunca atravessa fronteira de sentença, e é essa a defesa principal:
# sem ela, "I'm sorry" colado antes de conteúdo nocivo vira porta de evasão.
_FIM_DE_SENTENCA = re.compile(r"[.!?…]+[\"')\]”’]*(?=\s|$)")
_TOKEN = re.compile(r"\S+")
# Pega também a forma pontuada ("e.g", "i.e"), que os pontos internos escondem
# de um `\w+$`.
_PALAVRA_FINAL = re.compile(r"([\w.]+)$", re.UNICODE)

# Abreviação seguida de ponto não fecha sentença. A lista é curta de propósito,
# e o critério de entrada é estreito: **só forma que praticamente nunca termina
# sentença**. Deixar de fechar sentença ALARGA escopo de recusa, que é o lado
# que afrouxa o guardrail, então a dúvida se resolve fora da lista.
#
# Ficaram de fora, medido: `no`, `us`, `uk`, `st`, `ex`, `al` -- todas palavras
# inglesas comuns em fim de frase ("said no.", "call us."). É o mesmo defeito de
# radical que a mineração encontrou em `furt\w*` casando "further". `etc`
# também sai: "etc." termina sentença com frequência demais.
_ABREVIACOES = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "jr",
    "sr", "sra", "srta", "obs",
    "eg", "ie", "vs", "approx", "vol", "fig", "ref", "cf",
})


class FramesError(ValueError):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("invalid frames file:\n" + "\n".join(f"- {e}" for e in errors))


@dataclass(frozen=True)
class Gatilho:
    id: str
    termo: str
    regex: bool = False
    direcao: str = "frente"
    alcance: int = 15
    familia: str = "recusa"


@dataclass(frozen=True)
class Escopo:
    gatilho_id: str
    familia: str
    span: Tuple[int, int]


def segmentar(texto: str) -> List[Tuple[int, int]]:
    """Spans de caractere das sentenças de `texto`, sem os brancos das bordas."""
    if not texto or not texto.strip():
        return []

    cortes: List[int] = []
    for m in _FIM_DE_SENTENCA.finditer(texto):
        anterior = _PALAVRA_FINAL.search(texto[: m.start()])
        if anterior is not None:
            palavra = anterior.group(1).replace(".", "")
            if palavra.lower() in _ABREVIACOES:
                continue
            # Inicial de nome próprio ("J. Smith"): um caractere maiúsculo
            # sozinho antes do ponto quase nunca é fim de sentença.
            if len(palavra) == 1 and palavra.isupper():
                continue
        cortes.append(m.end())

    spans: List[Tuple[int, int]] = []
    inicio = 0
    for corte in cortes + [len(texto)]:
        if corte <= inicio:
            continue
        trecho = texto[inicio:corte]
        deslocamento = len(trecho) - len(trecho.lstrip())
        fim = inicio + len(trecho.rstrip())
        if fim > inicio + deslocamento:
            spans.append((inicio + deslocamento, fim))
        inicio = corte
    return spans


def _limite_por_janela(
    texto: str, inicio: int, fim: int, alcance: int, direcao: str
) -> int:
    """Onde a janela de `alcance` tokens corta, contada a partir do gatilho."""
    tokens = list(_TOKEN.finditer(texto, inicio, fim))
    if len(tokens) <= alcance:
        return fim if direcao == "frente" else inicio
    if direcao == "frente":
        return tokens[alcance].start()
    return tokens[len(tokens) - alcance].start()


@dataclass
class FramesRecusa:
    """Os gatilhos de recusa carregados, e a marcação que eles produzem."""

    metadata: dict = field(default_factory=dict)
    gatilhos: List[Gatilho] = field(default_factory=list)
    nao_validados: List[Gatilho] = field(default_factory=list)
    terminadores: Dict[str, List[str]] = field(default_factory=dict)
    source_path: Optional[Path] = None
    _compilados: list = field(default_factory=list, repr=False)
    _term_compilados: dict = field(default_factory=dict, repr=False)

    def compile(self) -> None:
        self._compilados = []
        for gatilho in self.gatilhos:
            padrao = gatilho.termo if gatilho.regex else rf"\b{re.escape(gatilho.termo)}\b"
            try:
                self._compilados.append((gatilho, re.compile(padrao, re.IGNORECASE)))
            except re.error as exc:
                # O id e o erro do `re`, nunca o padrão: um arquivo de gatilhos
                # que não carrega não pode imprimir a si mesmo, pela mesma razão
                # que vale para a política (conditions.py, `Condition.shape`).
                raise FramesError([f"{gatilho.id}: invalid trigger pattern: {exc}"]) from exc
        self._term_compilados = {}
        for direcao, formas in self.terminadores.items():
            compilados = []
            for forma in formas:
                try:
                    compilados.append(re.compile(rf"\b{re.escape(forma)}\b", re.IGNORECASE))
                except re.error as exc:
                    raise FramesError([f"terminator {direcao!r}: {exc}"]) from exc
            self._term_compilados[direcao] = compilados

    def escopos(self, texto: str, limit: Optional[int] = MAX_ESCOPOS) -> List[Escopo]:
        """Os escopos de recusa ativos em `texto`, um por casamento de gatilho."""
        encontrados: List[Escopo] = []
        for s_inicio, s_fim in segmentar(texto):
            for gatilho, regex in self._compilados:
                for m in regex.finditer(texto, s_inicio, s_fim):
                    span = self._span_do_escopo(texto, m, gatilho, s_inicio, s_fim)
                    if span is not None:
                        encontrados.append(
                            Escopo(gatilho_id=gatilho.id, familia=gatilho.familia, span=span)
                        )
                        if limit is not None and len(encontrados) >= limit:
                            return encontrados
        return encontrados

    def _span_do_escopo(self, texto, m, gatilho, s_inicio, s_fim):
        if gatilho.direcao == "frente":
            limite = _limite_por_janela(texto, m.end(), s_fim, gatilho.alcance, "frente")
            for term in self._term_compilados.get("frente", []):
                corte = term.search(texto, m.end(), limite)
                if corte is not None:
                    limite = min(limite, corte.start())
            return (m.start(), max(limite, m.end()))

        limite = _limite_por_janela(texto, s_inicio, m.start(), gatilho.alcance, "tras")
        for term in self._term_compilados.get("tras", []):
            ultimo = None
            for corte in term.finditer(texto, limite, m.start()):
                ultimo = corte
            if ultimo is not None:
                limite = max(limite, ultimo.end())
        return (min(limite, m.start()), m.end())

    def cobertura_total(self, texto: str) -> bool:
        """Todo caractere alfanumérico de `texto` está sob algum escopo.

        **Não é** o teste que a condição `refusal` usa, e a diferença está
        medida: numa recusa real de assistente as sentenças seguintes explicam,
        sugerem alternativa ou concluem, e não repetem gatilho -- em
        `HF-BT-0022` são 2 sentenças cobertas de 5. Um teste de texto inteiro
        ou nunca dispara ou vira porta de evasão; o que decide é **onde** o dano
        casou. Fica exposto porque a instrumentação de medição o usa.
        """
        if not texto or not texto.strip():
            return False
        escopos = self.escopos(texto, limit=None)
        if not escopos:
            return False
        coberto = self._mapa_de_cobertura(texto, escopos)
        return all(coberto[i] for i, ch in enumerate(texto) if ch.isalnum())

    @staticmethod
    def _mapa_de_cobertura(texto: str, escopos: List[Escopo]) -> bytearray:
        coberto = bytearray(len(texto))
        for escopo in escopos:
            inicio, fim = escopo.span
            for i in range(max(0, inicio), min(len(texto), fim)):
                coberto[i] = 1
        return coberto

    def sob_recusa(self, texto: str, spans: List[Optional[Tuple[int, int]]]) -> bool:
        """Todo span de `spans` cai inteiro dentro de algum escopo de recusa.

        Span ausente devolve False: sem posição não há como conferir a
        contenção, e a dúvida numa supressão resolve-se **não suprimindo**.
        """
        if not spans or any(s is None for s in spans):
            return False
        escopos = self.escopos(texto, limit=None)
        if not escopos:
            return False
        coberto = self._mapa_de_cobertura(texto, escopos)
        for span in spans:
            inicio, fim = span
            if inicio >= fim or fim > len(texto):
                return False
            if not all(coberto[i] for i in range(inicio, fim)):
                return False
        return True

    def config_artifacts(self) -> List[ConfigArtifact]:
        return [ConfigArtifact(
            role="frames_refusal",
            version=self.metadata.get("version"),
            path=str(self.source_path) if self.source_path else None,
        )]

    @classmethod
    def from_dict(cls, data: dict) -> "FramesRecusa":
        errors: List[str] = []

        def _gatilhos(bruto, rotulo):
            saida = []
            for indice, raw in enumerate(bruto or []):
                gid = raw.get("id") or f"<{rotulo}[{indice}] sem id>"
                termo = raw.get("termo")
                if not termo:
                    errors.append(f"{gid}: gatilho sem 'termo'")
                    continue
                direcao = raw.get("direcao", "frente")
                if direcao not in ("frente", "tras"):
                    errors.append(f"{gid}: direção inválida {direcao!r} (frente, tras)")
                    continue
                alcance = raw.get("alcance", 15)
                if not isinstance(alcance, int) or alcance < 1:
                    errors.append(f"{gid}: alcance deve ser inteiro >= 1")
                    continue
                saida.append(Gatilho(
                    id=gid,
                    termo=termo,
                    regex=bool(raw.get("regex", False)),
                    direcao=direcao,
                    alcance=alcance,
                    familia=raw.get("familia", "recusa"),
                ))
            return saida

        gatilhos = _gatilhos(data.get("gatilhos"), "gatilhos")
        # Lista separada, e não um booleano `ativo`, porque estrutura não se
        # inverte por descuido: as formas pt-BR ficam **legíveis** para quem
        # audita e **inalcançáveis** pelo runtime. A §4.1 da mineração mediu
        # todas elas em 0/0, e gatilho não validado num supressor é porta de
        # evasão, não lacuna de cobertura.
        nao_validados = _gatilhos(data.get("gatilhos_nao_validados"), "nao_validados")

        if not gatilhos and not errors:
            errors.append("nenhum gatilho ativo: 'gatilhos' está vazio")
        if errors:
            raise FramesError(errors)

        frames = cls(
            metadata=data.get("metadata", {}),
            gatilhos=gatilhos,
            nao_validados=nao_validados,
            terminadores=data.get("terminadores", {}),
        )
        frames.compile()
        return frames

    @classmethod
    def from_file(cls, path) -> "FramesRecusa":
        caminho = Path(path)
        with caminho.open(encoding="utf-8") as handle:
            data = json.load(handle)
        frames = cls.from_dict(data)
        frames.source_path = caminho
        return frames


class RefusalCondition(Condition):
    """Verdadeira quando **todo** casamento de `of` cai dentro de um escopo de recusa.

    Usada em `exceptions`, `of` fica `None` no JSON e `Rule.from_dict` a liga ao
    gatilho da própria regra -- o auditor escreve `{"type": "refusal"}` uma vez,
    e não há dois literais que precisam ser iguais.
    """

    type_name = "refusal"

    def __init__(self, frames: FramesRecusa, of: Optional[Condition] = None):
        self.frames = frames
        self.of = of

    def evaluate(self, text: str, limit: Optional[int] = MAX_ESCOPOS) -> List[Evidence]:
        if self.of is None:
            return []
        interno = self.of.evaluate(text, limit=None)
        if not interno:
            # Nada casou, logo não há o que suprimir. Devolver evidência aqui
            # faria a isenção valer para texto que a regra nem tocou.
            return []
        if not self.frames.sob_recusa(text, [e.span for e in interno]):
            return []
        # Espécie e contagem, nunca o gatilho: `engine.py` põe esta descrição
        # direto no `SuppressedMatch.reason`, que vai para o registro de
        # auditoria e para a tela. Ver `Condition.shape`.
        n = len(self.frames.escopos(text, limit=None))
        return [Evidence(description=f"marca de recusa: {n} escopo(s) sobre {len(interno)} casamento(s)")]

    def shape(self) -> str:
        return "refusal frame over the rule trigger"

    def to_dict(self) -> dict:
        return {"type": "refusal"}


def condicoes_de_recusa(condition: Optional[Condition]) -> List[RefusalCondition]:
    """Toda `RefusalCondition` na árvore de `condition`, em qualquer profundidade."""
    if condition is None:
        return []
    if isinstance(condition, RefusalCondition):
        return [condition]
    achadas: List[RefusalCondition] = []
    for filha in getattr(condition, "conditions", []) or []:
        achadas.extend(condicoes_de_recusa(filha))
    interna = getattr(condition, "condition", None)
    if isinstance(interna, Condition):
        achadas.extend(condicoes_de_recusa(interna))
    return achadas


def register_refusal_condition(frames: FramesRecusa) -> None:
    def factory(data: dict) -> RefusalCondition:
        bruto = data.get("of")
        if bruto is None:
            return RefusalCondition(frames)
        return RefusalCondition(frames, condition_from_dict(bruto))

    register_condition_type("refusal", factory)


def default_frames_path() -> Path:
    return Path(__file__).resolve().parents[1] / "frames" / "refusal_frames.json"


def load_default_frames() -> FramesRecusa:
    return FramesRecusa.from_file(default_frames_path())
