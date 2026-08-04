from pathlib import Path

from ethical_agent.engine import CompositeEngine, RuleBasedEngine
from ethical_agent.evaluate import evaluate_engine, format_report, load_dataset
from ethical_agent.kg_engine import KnowledgeGraphEngine
from ethical_agent.policy import Policy, default_policy_path
from ethical_agent.relaieo import load_default_ontology

DATASET = Path(__file__).resolve().parents[1] / "eval" / "dataset_huggingface_injections.json"


def _hybrid_engine():
    return CompositeEngine(
        [
            RuleBasedEngine(Policy.from_file(default_policy_path())),
            KnowledgeGraphEngine(load_default_ontology()),
        ],
        name="hybrid",
    )


def test_huggingface_dataset_loads_and_runs():
    # Dataset de terceiros (deepset/prompt-injections, Apache 2.0), convertido
    # offline e commitado para dispensar rede; sem piso de acurácia, isto guarda
    # só contra dataset/motor quebrarem: versão longa em `997a6fe^`.
    cases = load_dataset(DATASET)
    assert len(cases) >= 500

    results = evaluate_engine(_hybrid_engine(), cases)
    assert results["total_cases"] == len(cases)
    report = format_report(results)
    assert "Binary intervention" in report


def test_huggingface_dataset_precision_stays_perfect():
    # Same invariant as the holdout dataset: recall may be low on
    # out-of-distribution phrasing, but everything the engine DOES flag
    # must be a real injection attempt (no new false positives on genuine
    # third-party benign prompts).
    cases = load_dataset(DATASET)
    results = evaluate_engine(_hybrid_engine(), cases)
    assert results["binary"]["fp"] == 0
