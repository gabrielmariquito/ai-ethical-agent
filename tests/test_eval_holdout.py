from pathlib import Path

from ethical_agent.engine import CompositeEngine, RuleBasedEngine
from ethical_agent.evaluate import evaluate_engine, format_report, load_dataset
from ethical_agent.kg_engine import KnowledgeGraphEngine
from ethical_agent.policy import Policy, default_policy_path
from ethical_agent.relaieo import load_default_ontology

HOLDOUT = Path(__file__).resolve().parents[1] / "eval" / "dataset_holdout.json"


def _hybrid_engine():
    return CompositeEngine(
        [
            RuleBasedEngine(Policy.from_file(default_policy_path())),
            KnowledgeGraphEngine(load_default_ontology()),
        ],
        name="hybrid",
    )


def test_holdout_dataset_loads_and_runs():
    # This dataset documents generalization limits (see README) -- it is
    # expected to score much lower than eval/dataset.json. No accuracy floor
    # is enforced here; the point is to keep the report reproducible and
    # catch the dataset/engine breaking (exceptions, schema errors), not to
    # gate merges on the guardrail "passing" adversarial paraphrases.
    cases = load_dataset(HOLDOUT)
    assert len(cases) >= 20

    results = evaluate_engine(_hybrid_engine(), cases)
    assert results["total_cases"] == len(cases)
    report = format_report(results)
    assert "Binary intervention" in report


def test_holdout_dataset_precision_stays_perfect():
    # Even on out-of-distribution phrasing, the engines must not raise the
    # false-positive rate: everything they DO intervene on should be a real
    # match (precision == 1.0), even though recall is expected to be low.
    cases = load_dataset(HOLDOUT)
    results = evaluate_engine(_hybrid_engine(), cases)
    assert results["binary"]["fp"] == 0
