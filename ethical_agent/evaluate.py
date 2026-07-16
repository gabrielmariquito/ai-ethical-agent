from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import List, Union

from .engine import PolicyEngine
from .types import ActionContext, Decision, Stage

INTERVENING = {Decision.DENY, Decision.REWRITE, Decision.ESCALATE}


def load_dataset(path: Union[str, Path]) -> List[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        data = json.load(handle)
    cases = data.get("cases", [])
    if not cases:
        raise ValueError(f"{path}: dataset has no cases")
    return cases


def evaluate_engine(engine: PolicyEngine, cases: List[dict]) -> dict:
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

    return {
        "engine": engine.name,
        "total_cases": total,
        "binary": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "accuracy": (tp + tn) / total if total else 0.0,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "decision_accuracy": exact / total if total else 0.0,
        "per_principle": {k: dict(v) for k, v in sorted(per_principle.items())},
        "mismatches": mismatches,
    }


def format_report(results: dict) -> str:
    binary = results["binary"]
    lines = [
        f"Engine: {results['engine']}",
        f"Cases:  {results['total_cases']}",
        "",
        "Binary intervention (DENY/REWRITE/ESCALATE vs ALLOW/FLAG):",
        f"  accuracy  : {binary['accuracy']:.3f}",
        f"  precision : {binary['precision']:.3f}",
        f"  recall    : {binary['recall']:.3f}",
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
