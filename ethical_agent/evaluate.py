from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Union

from .engine import PolicyEngine
from .policy import default_policy_path
from .types import ActionContext, Decision, Stage

INTERVENING = {Decision.DENY, Decision.REWRITE}

METADES = ("tune", "holdout", "full")

# O papel de cada metade, ao lado da partição que a produz e não num rótulo de
# tela. `metade_do_caso` é simétrica — par vira `tune`, ímpar vira `holdout` —,
# então sem isto a assimetria entre calibrar e reportar não existe em lugar
# nenhum do código e vira convenção oral. Não é enforcement: nada aqui impede
# ninguém de calibrar contra o holdout. O que isto garante é que nenhum número
# de holdout chega sem o papel colado, inclusive no texto copiado da tela.
PAPEIS_DAS_METADES = {
    "tune": "Ajuste. É aqui que se leem os erros do sistema para corrigir regras e léxicos",
    "holdout": "Reporte. É o desempenho verdadeiro do sistema",
    "full": "Conjunto inteiro dos dados. Inclui dados de ajuste e de reporte juntos",
}


# A divisão tune/holdout, receita `divisao/v1` escrita por extenso: só o id do
# caso entra no material, a constante da receita está dentro dos dois hashes, e
# a proporção DENY/ALLOW é *verificada* e não construída —
# versão longa em `997a6fe^`.
RECEITA_DIVISAO = "divisao/v1"  # also the seed -- see item 3 above

# Os dois limites e a derivação deles: a grandeza ameaçada é o *gap entre as
# metades*, o recall é invariante à mistura DENY/ALLOW e acurácia/F1 não são —
# e este é **flag, não assert**, porque uma verificação permanentemente
# vermelha vira ruído: versão longa em `997a6fe^`.
LIMITE_COMPARABILIDADE = 0.02

# The hard limit *is* an assert. At a 0.10 gap the induced accuracy gap (~0.096)
# is four times the between-engine spread in every README table: past that the
# two halves are no longer two views of the same corpus.
LIMITE_DURO = 0.10


def eval_dir() -> Path:
    """O diretório dos datasets, resolvido pelo pacote e não por nome de arquivo.

    Vive aqui, e não em `__main__` nem no handler, porque os dois precisavam do
    mesmo caminho e o computavam por rotas diferentes.
    """
    return (default_policy_path().parents[1] / "eval").resolve()


def dataset_curado() -> Path:
    """O conjunto curado in-distribution, que nunca é dividido."""
    return eval_dir() / "dataset.json"


def recusa_de_divisao(nome: str) -> str:
    """A frase que a CLI imprime e a tela mostra, escrita uma vez.

    Uma tela que dividisse o que a linha de comando recusa produziria um número
    rotulado `holdout` que não é um — e o teste que registra a recusa passaria a
    valer em só um dos dois caminhos. Isso não é lacuna, é garantia falsa, e
    garantia falsa ninguém questiona.

    O compartilhado é o **motivo**. O remédio é específico da interface por
    natureza (`--half full` na CLI, o seletor na tela) e cada caminho acrescenta
    o seu, que é o que mantém o stderr da CLI byte a byte igual ao de sempre.
    """
    return (
        f"{nome} não é dividido -- é o conjunto curado in-distribution, escrito "
        "pelo autor das próprias regras. Ele é reportado inteiro e separado, "
        "nunca somado nem promediado com os datasets externos."
    )


def metade_do_caso(case_id: str) -> str:
    """Which half a case belongs to. See the `divisao/v1` recipe above."""
    material = f"{RECEITA_DIVISAO}|{case_id}".encode("utf-8")
    return "tune" if int(hashlib.sha256(material).hexdigest(), 16) % 2 == 0 else "holdout"


def _id_obrigatorio(case: dict, indice: int) -> str:
    """`id` é opcional para `evaluate_engine` e obrigatório para a divisão,
    com erro explícito porque sem id estável a atribuição cairia na posição na
    lista: versão longa em `997a6fe^`.
    """
    cid = case.get("id")
    if cid is None or cid == "":
        raise ValueError(
            f"caso {indice} não tem `id`, e a divisão `{RECEITA_DIVISAO}` é "
            "derivada dele. Um dataset sem id estável não pode ser dividido de "
            "forma reprodutível. Dê ids aos casos, ou avalie com --half full."
        )
    return str(cid)


def tem_ids_estaveis(cases: List[dict]) -> bool:
    return all(c.get("id") not in (None, "") for c in cases)


def dividir(cases: List[dict]) -> dict:
    """{"tune": [...], "holdout": [...]}, ordem original preservada dentro de
    cada metade e por caso, nunca embaralhando a lista.
    """
    metades: dict = {"tune": [], "holdout": []}
    for indice, case in enumerate(cases):
        metades[metade_do_caso(_id_obrigatorio(case, indice))].append(case)
    return metades


def selecionar_metade(cases: List[dict], metade: str) -> List[dict]:
    if metade not in METADES:
        raise ValueError(f"metade desconhecida: {metade!r} (esperado: {', '.join(METADES)})")
    if metade == "full":
        return list(cases)
    return dividir(cases)[metade]


def identificador_da_metade(cases: List[dict]) -> str:
    """Identificador reproduzível de uma metade: é a linha que deixa distinguir
    "o mesmo holdout" de "um holdout".
    """
    ids = [_id_obrigatorio(case, indice) for indice, case in enumerate(cases)]
    linhas = [RECEITA_DIVISAO] + sorted(ids)
    return hashlib.sha256("\n".join(linhas).encode("utf-8")).hexdigest()


def _proporcao_deny(cases: List[dict]) -> tuple:
    """(positivos, negativos), com positivo sendo a classe *interveniente*,
    contando DENY **e** REWRITE porque é a classe sobre a qual o recall é
    computado: versão longa em `997a6fe^`.
    """
    positivos = sum(1 for c in cases if Decision(c["expected_decision"]) in INTERVENING)
    return positivos, len(cases) - positivos


def erro_padrao_do_recall(recall: float, n_deny: int) -> Optional[float]:
    """Erro padrão binomial do recall, reportado ao lado dele e nunca sozinho:
    um ganho menor que ele não se distingue de ruído, e uma leva que não
    imprime este número vai comemorá-lo: versão longa em `997a6fe^`.
    """
    if not n_deny:
        return None
    return math.sqrt(recall * (1 - recall) / n_deny)


def resumo_da_divisao(cases_da_metade: List[dict], cases_totais: List[dict],
                      metade: str) -> dict:
    """O bloco de procedência que viaja com todo número que o harness imprime:
    recall sem metade nomeada é afirmação sem procedência, e sem piso de
    ruído é afirmação sem escala.
    """
    deny, allow = _proporcao_deny(cases_da_metade)
    n = len(cases_da_metade)

    # `full` é a metade que nunca precisou da divisão, logo a que tem de continuar
    # funcionando num dataset sem ids: versão longa em `997a6fe^`.
    divisivel = metade != "full" or tem_ids_estaveis(cases_totais)

    gap = None
    if metade != "full":
        metades = dividir(cases_totais)
        if metades["tune"] and metades["holdout"]:
            proporcoes = []
            for outra in ("tune", "holdout"):
                d, a = _proporcao_deny(metades[outra])
                proporcoes.append(d / (d + a))
            gap = abs(proporcoes[0] - proporcoes[1])

    # `n_deny` é o tamanho do estrato sobre o qual o recall é medido, e viaja aqui
    # para virar erro padrão.
    return {
        "metade": metade,
        "receita": RECEITA_DIVISAO,
        "casos": n,
        "casos_no_conjunto": len(cases_totais),
        "deny": deny,
        "allow": allow,
        "proporcao_deny": deny / n if n else 0.0,
        "gap_entre_metades": gap,
        "limite_comparabilidade": LIMITE_COMPARABILIDADE,
        "acuracia_comparavel": None if gap is None else gap <= LIMITE_COMPARABILIDADE,
        "n_deny": deny,
        "identificador": (identificador_da_metade(cases_da_metade)
                          if divisivel else None),
    }


def load_dataset(path: Union[str, Path]) -> List[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    cases = data.get("cases", [])
    if not cases:
        raise ValueError(f"{path}: dataset has no cases")
    return cases


def _camadas_de(engine: PolicyEngine) -> list:
    """As camadas de um motor composto, lidas do PRÓPRIO motor.

    `CompositeEngine.engines` já é atributo público — `describe_config` e
    `config_artifacts` leem dele. Ler daqui em vez de reconstruir os motores dá
    três coisas: nenhuma recarga de ontologia, as instâncias são literalmente as
    que a composta consulta, e a atribuição não pode nomear camada que a
    composta não tem.

    `getattr` e não `isinstance`: o que importa é o motor expor as filhas que
    ele consulta, não a classe dele. Motor de camada única devolve lista vazia,
    e aí o relatório não afirma camada nenhuma — inventar uma camada única seria
    dizer algo que a composição não disse.
    """
    return list(getattr(engine, "engines", ()) or ())


def _quem_decidiu(camadas: list, action: ActionContext, decisao_final: Decision):
    """(vencedoras, houve_indisponivel) para um caso.

    Vencedora é a camada que decidiu **igual** à composta. A decisão final é a
    mais restritiva, então "quem decidiu" é quem produziu o veredito vencedor —
    e quando duas decidiram igual, as duas decidiram. Isso é informação, não
    empate a desfazer.

    O critério não é re-derivado: compara-se contra `decisao_final`, que a
    composta já computou. Esta função nunca chama `most_restrictive` nem olha o
    ranking de restritividade, e por isso não pode discordar da decisão que
    descreve.

    Camada que levanta entra como indisponível, **não** como DENY. A composta
    falha fechada e está certa; espelhar essa regra aqui seria reescrever lógica
    de composição fora do motor, e a atribuição passaria a descrever um sistema
    que ninguém roda. O caso vai para um balde nomeado em vez de sumir.
    """
    decisoes = []
    for camada in camadas:
        try:
            decisoes.append((camada.name, camada.evaluate(action).decision))
        except Exception:  # noqa: BLE001 -- indisponível é um estado, não um palpite
            decisoes.append((camada.name, None))
    vencedoras = tuple(
        nome for nome, d in decisoes if d is not None and d is decisao_final
    )
    return vencedoras, any(d is None for _, d in decisoes)


def evaluate_engine(engine: PolicyEngine, cases: List[dict],
                    divisao: Optional[dict] = None) -> dict:
    tp = fp = fn = tn = 0
    exact = 0
    per_principle = defaultdict(lambda: {"total": 0, "correct": 0})
    mismatches = []

    camadas = _camadas_de(engine)
    combinacoes: dict = defaultdict(int)
    indisponiveis = 0

    for case in cases:
        stage = Stage(case.get("stage", "input"))
        expected = Decision(case["expected_decision"])
        action = ActionContext(content=case["content"], stage=stage)
        verdict = engine.evaluate(action)
        predicted = verdict.decision

        vencedoras = ()
        if camadas:
            vencedoras, faltou = _quem_decidiu(camadas, action, predicted)
            combinacoes[vencedoras] += 1
            indisponiveis += 1 if faltou else 0

        expected_intervene = expected in INTERVENING
        predicted_intervene = predicted in INTERVENING
        if expected_intervene and predicted_intervene:
            tp += 1
        elif not expected_intervene and predicted_intervene:
            fp += 1
        elif expected_intervene and not predicted_intervene:
            fn += 1
        else:
            tn += 1

        principle = case.get("principle", "unspecified")
        per_principle[principle]["total"] += 1
        if predicted is expected:
            exact += 1
            per_principle[principle]["correct"] += 1
        else:
            divergencia = {
                "id": case.get("id"),
                "content": case["content"],
                "stage": stage.value,
                "expected": expected.value,
                "predicted": predicted.value,
                "matched_rules": [m.rule_id for m in verdict.matches],
                "reason": verdict.reason,
            }
            if camadas:
                # É o dado que hoje exige investigação manual: ao olhar um caso
                # errado, saber qual das duas camadas errou.
                divergencia["camada"] = list(vencedoras)
            mismatches.append(divergencia)

    total = len(cases)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    binary = {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "accuracy": (tp + tn) / total if total else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }
    # The noise floor travels with the number it qualifies, in the same dict, so
    # that no consumer can pick up `recall` without it being one key away.
    binary["recall_erro_padrao"] = erro_padrao_do_recall(recall, tp + fn)

    results = {
        "engine": engine.name,
        "total_cases": total,
        "binary": binary,
        "decision_accuracy": exact / total if total else 0.0,
        "per_principle": {k: dict(v) for k, v in sorted(per_principle.items())},
        "mismatches": mismatches,
    }
    if divisao is not None:
        results["divisao"] = divisao
    if camadas:
        ordem = [c.name for c in camadas]
        results["camadas"] = {
            "engines": ordem,
            # `combinacoes` é a ÚNICA forma armazenada: "sozinha", "no total" e
            # "concordaram" são derivadas na impressão, para que cada número
            # tenha uma fonte só e não possam divergir entre si.
            "combinacoes": [
                {"camadas": list(chave), "casos": n}
                for chave, n in sorted(
                    combinacoes.items(),
                    key=lambda kv: (len(kv[0]), [ordem.index(e) for e in kv[0]]),
                )
            ],
            # Zero por construção. Existe para poder deixar de ser zero em vez
            # de o caso sumir: se uma camada levantar, isso aparece aqui.
            "indisponivel": indisponiveis,
        }
    return results


def _linhas_da_divisao(divisao: dict) -> List[str]:
    """A metade, nomeada, antes de qualquer métrica — e o bloco imprime para
    `full` também, porque default silencioso é o mesmo defeito disfarçado: versão longa em `997a6fe^`.
    """
    identificador = divisao["identificador"]
    rotulo_id = (f"{identificador[:12]}…" if identificador
                 else "— (casos sem id: dataset não divisível)")
    linhas = [
        f"Divisão : {divisao['metade']}  ({divisao['receita']})",
        # O papel colado ao número, e não em ajuda que ninguém abre: um recall
        # de `holdout` copiado desta caixa leva junto para que serve a metade.
        f"  papel     : {PAPEIS_DAS_METADES[divisao['metade']]}",
        f"  casos     : {divisao['casos']} de {divisao['casos_no_conjunto']}"
        f"        metade-id : {rotulo_id}",
        f"  DENY/ALLOW: {divisao['deny']}/{divisao['allow']}  "
        f"({divisao['proporcao_deny']:.3f})",
    ]
    gap = divisao["gap_entre_metades"]
    if gap is not None:
        linhas[-1] += f"    gap entre metades: {gap:.3f}"
        if not divisao["acuracia_comparavel"]:
            linhas.append(
                f"  !! acurácia e F1 NÃO são comparáveis com a outra metade "
                f"(gap {gap:.3f} > {divisao['limite_comparabilidade']:.2f})."
            )
            linhas.append(
                "     Compare recall, que é invariante à mistura DENY/ALLOW."
            )
    linhas.append("")
    return linhas


def _linhas_das_camadas(camadas: dict) -> List[str]:
    """Quem produziu o veredito vencedor, quando o motor tem camadas.

    A decisão final é a mais restritiva, então "quem decidiu" é quem decidiu
    igual a ela — e quando duas decidiram igual, **as duas decidiram**. Isso é
    informação, não empate a desfazer: um caso em que regras e conceitos chegam
    ao mesmo veredito diz algo diferente de um em que só uma chegou.

    Todos os números saem de `combinacoes`, que é a única forma armazenada.
    """
    ordem = camadas["engines"]
    total = sum(c["casos"] for c in camadas["combinacoes"])
    presente: dict = {}
    sozinha: dict = {}
    juntas = 0
    for combinacao in camadas["combinacoes"]:
        nomes, n = combinacao["camadas"], combinacao["casos"]
        for nome in nomes:
            presente[nome] = presente.get(nome, 0) + n
        if len(nomes) == 1:
            sozinha[nomes[0]] = sozinha.get(nomes[0], 0) + n
        elif len(nomes) > 1:
            juntas += n

    largura = max((len(nome) for nome in ordem), default=0)
    linhas = ["Camada decisória (quem produziu o veredito vencedor):"]
    for nome in ordem:
        linhas.append(
            f"  {nome:<{largura}} : {presente.get(nome, 0)} de {total}"
            f"   ({sozinha.get(nome, 0)} sozinha)"
        )
    linhas.append(f"  as camadas concordaram em {juntas} de {total} casos.")
    if camadas["indisponivel"]:
        # Aparece em vez de sumir: camada que levanta não é atribuída a
        # ninguém, e o caso não pode desaparecer da contagem por isso.
        linhas.append(
            f"  !! {camadas['indisponivel']} caso(s) com camada indisponível "
            "(o motor levantou) — sem camada atribuída."
        )
    return linhas


def format_report(results: dict) -> str:
    binary = results["binary"]
    erro = binary.get("recall_erro_padrao")
    escala = (f"  (± {erro:.3f} e.p., N_DENY={binary['tp'] + binary['fn']})"
              if erro is not None else "")
    lines = []
    if results.get("divisao"):
        lines.extend(_linhas_da_divisao(results["divisao"]))
    lines += [
        f"Engine: {results['engine']}",
        f"Cases:  {results['total_cases']}",
        "",
        "Binary intervention (DENY/REWRITE vs ALLOW/FLAG):",
        f"  accuracy  : {binary['accuracy']:.3f}",
        f"  precision : {binary['precision']:.3f}",
        f"  recall    : {binary['recall']:.3f}{escala}",
        f"  f1        : {binary['f1']:.3f}",
        f"  confusion : TP={binary['tp']} FP={binary['fp']} "
        f"FN={binary['fn']} TN={binary['tn']}",
        "",
        f"Exact decision accuracy: {results['decision_accuracy']:.3f}",
        "",
        "Per principle (exact decision):",
    ]
    for principle, stats in results["per_principle"].items():
        lines.append(
            f"  {principle:<16} {stats['correct']}/{stats['total']}"
        )
    # Mesmo idioma do `results.get("divisao")` acima: um results sem a chave é
    # um motor de camada única, e o bloco simplesmente não existe.
    if results.get("camadas"):
        lines.append("")
        lines.extend(_linhas_das_camadas(results["camadas"]))
    if results["mismatches"]:
        lines.append("")
        lines.append(f"Mismatches ({len(results['mismatches'])}):")
        for miss in results["mismatches"]:
            camada = (
                f"    [camada: {', '.join(miss['camada']) or '—'}]"
                if "camada" in miss
                else ""
            )
            lines.append(
                f"  [{miss['id']}] expected {miss['expected']}, "
                f"got {miss['predicted']} (rules: {miss['matched_rules']}){camada}"
            )
            lines.append(f"      {miss['content']!r}")
    else:
        lines.append("")
        lines.append("No mismatches.")
    return "\n".join(lines)
