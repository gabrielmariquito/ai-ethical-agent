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
    # Third-party dataset (deepset/prompt-injections, Apache 2.0), converted
    # offline and committed here so this
    # test doesn't need network access. Like dataset_holdout.json, it's
    # expected to score far below eval/dataset.json (see README) -- no
    # accuracy floor enforced, this only guards against the dataset/engine
    # breaking.
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
