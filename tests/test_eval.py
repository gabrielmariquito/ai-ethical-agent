from pathlib import Path

from ethical_agent.engine import CompositeEngine, RuleBasedEngine
from ethical_agent.evaluate import evaluate_engine, format_report, load_dataset
from ethical_agent.kg_engine import KnowledgeGraphEngine
from ethical_agent.policy import Policy, default_policy_path
from ethical_agent.relaieo import load_default_ontology

DATASET = Path(__file__).resolve().parents[1] / "eval" / "dataset.json"


def _rule_engine():
    return RuleBasedEngine(Policy.from_file(default_policy_path()))


def _hybrid_engine():
    return CompositeEngine(
        [_rule_engine(), KnowledgeGraphEngine(load_default_ontology())],
        name="hybrid",
    )


def test_hybrid_baseline_meets_quality_bar():
    cases = load_dataset(DATASET)
    results = evaluate_engine(_hybrid_engine(), cases)

    assert results["total_cases"] >= 40
    assert results["binary"]["accuracy"] >= 0.9, results["mismatches"]
    assert results["decision_accuracy"] >= 0.9, results["mismatches"]
    assert results["binary"]["recall"] >= 0.9, results["mismatches"]

    report = format_report(results)
    assert "Binary intervention" in report


def test_hybrid_improves_on_rule_baseline():
    cases = load_dataset(DATASET)
    rule_results = evaluate_engine(_rule_engine(), cases)
    hybrid_results = evaluate_engine(_hybrid_engine(), cases)

    assert hybrid_results["decision_accuracy"] >= rule_results["decision_accuracy"]
    assert hybrid_results["binary"]["recall"] >= rule_results["binary"]["recall"]
    assert hybrid_results["binary"]["fp"] <= rule_results["binary"]["fp"] + 1
