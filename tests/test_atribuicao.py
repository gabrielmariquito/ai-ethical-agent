"""`I-C` — a composição lida é a composição implementada.

A atribuição por camada é **recomputada** fora do motor: `evaluate_engine` lê
`CompositeEngine.engines`, roda as filhas e chama de vencedora a que decidiu
igual à composta. Isso troca o teste que o briefing pedia — "a atribuição bate
com o veredito de cada motor isolado" —, que sob este desenho é verdadeiro por
construção, por um invariante que aquele teste **tomava como dado**: a regra de
composição que a atribuição assume é a que o motor implementa.

A cláusula 1 carrega o peso e é a única não derivável da recomputação. Se cair,
o errado é a atribuição, não o teste. É também o único lugar autorizado a chamar
`most_restrictive`: a função dele aqui é confrontar o critério, não repeti-lo.

O que é vermelho e o que é guarda, declarado para ninguém ler verde como prova:
as cláusulas 1-3 e o caso de concordância **passam hoje** — são guardas sobre o
motor que já existe, e existem para pegar mudança futura na composição. As
cláusulas 4-5 e a conferência de que `results["camadas"]` concorda com a
recomputação **falham hoje**, porque a chave ainda não existe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ethical_agent import default_policy_path
from ethical_agent.engine import CompositeEngine, PolicyEngine
from ethical_agent.evaluate import evaluate_engine, load_dataset
from ethical_agent.relaieo import (
    default_grounding_path,
    default_norms_path,
    default_relaieo_ttl,
)
from ethical_agent.types import ActionContext, Decision, Stage, Verdict
from ethical_agent.webui.engine_factory import build_engine

EVAL = Path(__file__).resolve().parents[1] / "eval"
DATASETS = ("dataset.json", "dataset_beavertails.json", "dataset_huggingface_injections.json")


def _hybrid():
    """A composta construída como a tela vai construí-la, pela mesma fábrica.

    Construir por aqui e não à mão importa: `frames` vai para as DUAS camadas, e
    um retrato que monta `KnowledgeGraphEngine(ontology)` sem frames mede um
    sistema que a CLI não roda.
    """
    return build_engine(
        default_policy_path(),
        default_relaieo_ttl(),
        default_grounding_path(),
        default_norms_path(),
        "hybrid",
    )


@pytest.fixture(scope="module")
def hibrida():
    return _hybrid()


def _decisoes(composta: CompositeEngine, acao: ActionContext):
    """(decisão da composta, [(nome, decisão) por camada]) — as camadas lidas do
    próprio motor, nunca reconstruídas.

    Uma camada que levanta entra como `None`, **não** como DENY: espelhar a falha
    fechada de `engine.py` aqui seria reescrever lógica de composição fora do
    motor, que é o defeito que este desenho existe para não cometer.
    """
    filhas = []
    for camada in composta.engines:
        try:
            filhas.append((camada.name, camada.evaluate(acao).decision))
        except Exception:  # noqa: BLE001 -- indisponível é um estado, não um palpite
            filhas.append((camada.name, None))
    return composta.evaluate(acao).decision, filhas


def _varrer(composta: CompositeEngine, nome_dataset: str):
    for caso in load_dataset(EVAL / nome_dataset):
        acao = ActionContext(
            content=caso["content"], stage=Stage(caso.get("stage", "input"))
        )
        composta_dec, filhas = _decisoes(composta, acao)
        yield caso.get("id"), composta_dec, filhas


def _vencedoras(composta_dec, filhas):
    return tuple(n for n, d in filhas if d is not None and d is composta_dec)


# ----------------------------------------------------------------- I-C, 1 a 3
# Guardas: passam hoje. Elas pegam a mudança de critério de composição, que é a
# única coisa capaz de tornar a atribuição errada sem tornar nada vermelho.


@pytest.mark.parametrize("nome_dataset", DATASETS)
def test_ic_clausula_1_a_composta_e_a_mais_restritiva_das_filhas(hibrida, nome_dataset):
    """`most_restrictive([D_r, D_k]) is D_h`, caso a caso.

    Cláusula 0: caso com camada indisponível **não entra** aqui — sai como falha
    nomeada, com o id e o nome da camada. `most_restrictive([D, None])` não é
    especificado, e a primeira exceção real tem de virar achado, não `TypeError`
    dentro do teste.
    """
    indisponiveis = []
    divergentes = []
    for cid, composta_dec, filhas in _varrer(hibrida, nome_dataset):
        ausentes = [n for n, d in filhas if d is None]
        if ausentes:
            indisponiveis.append((cid, ausentes))
            continue
        if Decision.most_restrictive(d for _, d in filhas) is not composta_dec:
            divergentes.append((cid, composta_dec, filhas))

    assert not indisponiveis, f"camada indisponível em {len(indisponiveis)} caso(s): {indisponiveis[:5]}"
    assert not divergentes, (
        f"{len(divergentes)} caso(s) em que a composta não é a mais restritiva das "
        f"filhas — a atribuição descreveria outra composição: {divergentes[:5]}"
    )


@pytest.mark.parametrize("nome_dataset", DATASETS)
def test_ic_clausula_2_sempre_ha_ao_menos_uma_camada_vencedora(hibrida, nome_dataset):
    vazios = [
        cid
        for cid, composta_dec, filhas in _varrer(hibrida, nome_dataset)
        if not _vencedoras(composta_dec, filhas)
    ]
    assert not vazios, f"{len(vazios)} caso(s) sem camada vencedora: {vazios[:5]}"


@pytest.mark.parametrize("nome_dataset", DATASETS)
def test_ic_clausula_3_concordar_e_decidir_junto_sao_a_mesma_coisa(hibrida, nome_dataset):
    """`D_r == D_k ⟺ |vencedoras| == 2`, **nos dois sentidos**.

    O sentido ⟸ é o que impede colapsar a concordância numa camada só e chamar
    isso de desempate. Quando as duas decidiram igual, as duas decidiram.
    """
    falhas = []
    for cid, composta_dec, filhas in _varrer(hibrida, nome_dataset):
        if any(d is None for _, d in filhas):
            continue
        concordam = len({d for _, d in filhas}) == 1
        duas = len(_vencedoras(composta_dec, filhas)) == len(filhas)
        if concordam != duas:
            falhas.append((cid, concordam, duas, filhas))
    assert not falhas, f"{len(falhas)} caso(s) em que concordância e atribuição dupla divergem: {falhas[:5]}"


def test_um_caso_limpo_e_decidido_pelas_duas_camadas_sem_nenhum_match(hibrida):
    """A prova de que `RuleMatch` não poderia ter carregado a atribuição.

    Num caso limpo as duas camadas devolvem ALLOW com **zero** `matches`: não há
    em que pendurar origem por casamento. Medido no BeaverTails: 158 de 220 casos
    são assim.
    """
    acao = ActionContext(content="what is the capital of Brazil?", stage=Stage.INPUT)
    veredito = hibrida.evaluate(acao)
    composta_dec, filhas = _decisoes(hibrida, acao)

    assert veredito.matches == []
    assert veredito.decision is Decision.ALLOW
    assert len(_vencedoras(composta_dec, filhas)) == 2, filhas


# ------------------------------------------------- I-C, 4 e 5 + o que a leva cria
# Vermelhos hoje: `results["camadas"]` não existe.


@pytest.mark.parametrize("nome_dataset", DATASETS)
def test_ic_clausula_4_as_combinacoes_particionam_o_corpus(hibrida, nome_dataset):
    casos = load_dataset(EVAL / nome_dataset)
    resultados = evaluate_engine(hibrida, casos)

    camadas = resultados["camadas"]
    assert camadas["engines"] == [c.name for c in hibrida.engines]
    total = sum(c["casos"] for c in camadas["combinacoes"])
    assert total == resultados["total_cases"] == len(casos)


@pytest.mark.parametrize("nome_dataset", DATASETS)
def test_ic_clausula_5_o_balde_de_camada_indisponivel_e_vazio(hibrida, nome_dataset):
    """Vazio **e nomeado**: a cláusula 0 é o que dá conteúdo a esta afirmação em
    vez de a tornar vácua. Se um dia não for zero, tem de aparecer, não sumir.
    """
    resultados = evaluate_engine(hibrida, load_dataset(EVAL / nome_dataset))
    camadas = resultados["camadas"]

    assert "indisponivel" in camadas, "o balde tem de existir para poder ser zero"
    assert camadas["indisponivel"] == 0


@pytest.mark.parametrize("nome_dataset", DATASETS)
def test_a_atribuicao_reportada_bate_com_a_recomputacao_independente(hibrida, nome_dataset):
    """O relatório concorda com quem conta por fora, combinação a combinação."""
    esperado: dict = {}
    for _, composta_dec, filhas in _varrer(hibrida, nome_dataset):
        chave = _vencedoras(composta_dec, filhas)
        esperado[chave] = esperado.get(chave, 0) + 1

    resultados = evaluate_engine(hibrida, load_dataset(EVAL / nome_dataset))
    reportado = {
        tuple(c["camadas"]): c["casos"] for c in resultados["camadas"]["combinacoes"]
    }
    assert reportado == esperado


def test_cada_divergencia_nomeia_a_camada_que_a_decidiu(hibrida):
    resultados = evaluate_engine(hibrida, load_dataset(EVAL / "dataset.json"))
    nomes = set(resultados["camadas"]["engines"])

    assert resultados["mismatches"], "sem divergência não há o que atribuir"
    for erro in resultados["mismatches"]:
        assert erro["camada"], erro
        assert set(erro["camada"]) <= nomes, erro


def test_motor_de_camada_unica_nao_afirma_camada_nenhuma():
    """`rule` sozinho não tem atribuição a fazer, e a ausência é a resposta certa:
    inventar uma camada única seria dizer algo que a composição não disse.
    """
    rule = build_engine(
        default_policy_path(),
        default_relaieo_ttl(),
        default_grounding_path(),
        default_norms_path(),
        "rule",
    )
    resultados = evaluate_engine(rule, load_dataset(EVAL / "dataset.json"))

    assert "camadas" not in resultados
    assert all("camada" not in erro for erro in resultados["mismatches"])


# ------------------------------------------------------- a camada indisponível


class _CamadaQueLevanta(PolicyEngine):
    name = "quebrada"

    def evaluate(self, action):
        raise RuntimeError("boom")


def _rule_puro():
    return build_engine(
        default_policy_path(),
        default_relaieo_ttl(),
        default_grounding_path(),
        default_norms_path(),
        "rule",
    )


def test_camada_que_levanta_entra_como_indisponivel_e_nao_como_deny():
    """A asserção que impede alguém de "consertar" isto espelhando a falha
    fechada de `engine.py`.

    A composta devolve DENY quando uma filha levanta — e está certa. O que a
    atribuição **não** pode fazer é adivinhar que a camada quebrada decidiu DENY:
    ela não decidiu nada. Adivinhar seria reescrever a composição fora do motor,
    e a atribuição passaria a descrever um sistema que ninguém roda.
    """
    composta = CompositeEngine([_rule_puro(), _CamadaQueLevanta()], name="hybrid")
    casos = [
        {"id": "limpo", "content": "what is the capital of Brazil?",
         "expected_decision": "ALLOW", "stage": "input"}
    ]
    resultados = evaluate_engine(composta, casos)
    camadas = resultados["camadas"]

    assert camadas["indisponivel"] == 1
    atribuido = {n for c in camadas["combinacoes"] for n in c["camadas"]}
    assert "quebrada" not in atribuido, (
        "a camada quebrada não decidiu nada; atribuir DENY a ela seria espelhar "
        "a falha fechada do motor num lugar onde ela não é lei"
    )


def test_a_composta_continua_falhando_fechada_apesar_disso():
    """O contraponto obrigatório: a atribuição não conhecer a decisão da camada
    quebrada **não** afrouxa a decisão. O veredito continua DENY.
    """
    composta = CompositeEngine([_rule_puro(), _CamadaQueLevanta()], name="hybrid")
    veredito = composta.evaluate(
        ActionContext(content="what is the capital of Brazil?", stage=Stage.INPUT)
    )
    assert isinstance(veredito, Verdict)
    assert veredito.decision is Decision.DENY
    assert "fail closed" in veredito.reason
