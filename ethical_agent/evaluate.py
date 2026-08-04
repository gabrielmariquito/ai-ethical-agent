from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import List, Optional, Union

from .engine import PolicyEngine
from .types import ActionContext, Decision, Stage

INTERVENING = {Decision.DENY, Decision.REWRITE}

METADES = ("tune", "holdout", "full")


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


def evaluate_engine(engine: PolicyEngine, cases: List[dict],
                    divisao: Optional[dict] = None) -> dict:
    tp = fp = fn = tn = 0
    exact = 0
    per_principle = defaultdict(lambda: {"total": 0, "correct": 0})
    mismatches = []

    for case in cases:
        stage = Stage(case.get("stage", "input"))
        expected = Decision(case["expected_decision"])
        verdict = engine.evaluate(ActionContext(content=case["content"], stage=stage))
        predicted = verdict.decision

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
            mismatches.append(
                {
                    "id": case.get("id"),
                    "content": case["content"],
                    "stage": stage.value,
                    "expected": expected.value,
                    "predicted": predicted.value,
                    "matched_rules": [m.rule_id for m in verdict.matches],
                    "reason": verdict.reason,
                }
            )

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
    if results["mismatches"]:
        lines.append("")
        lines.append(f"Mismatches ({len(results['mismatches'])}):")
        for miss in results["mismatches"]:
            lines.append(
                f"  [{miss['id']}] expected {miss['expected']}, "
                f"got {miss['predicted']} (rules: {miss['matched_rules']})"
            )
            lines.append(f"      {miss['content']!r}")
    else:
        lines.append("")
        lines.append("No mismatches.")
    return "\n".join(lines)
