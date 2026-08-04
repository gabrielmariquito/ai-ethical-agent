from pathlib import Path

from ethical_agent.engine import CompositeEngine, RuleBasedEngine
from ethical_agent.evaluate import evaluate_engine, format_report, load_dataset
from ethical_agent.kg_engine import KnowledgeGraphEngine
from ethical_agent.policy import Policy, default_policy_path
from ethical_agent.relaieo import load_default_ontology

DATASET = Path(__file__).resolve().parents[1] / "eval" / "dataset_beavertails.json"


def _hybrid_engine():
    return CompositeEngine(
        [
            RuleBasedEngine(Policy.from_file(default_policy_path())),
            KnowledgeGraphEngine(load_default_ontology()),
        ],
        name="hybrid",
    )


def test_beavertails_dataset_loads_and_runs():
    # Dataset de terceiros (PKU-Alignment/BeaverTails, CC BY-NC 4.0), amostrado e
    # convertido offline; é o único que de fato expõe falsos positivos, e sem
    # piso de acurácia: `REGISTRO`, "Texto movido do código".
    cases = load_dataset(DATASET)
    assert len(cases) >= 150

    results = evaluate_engine(_hybrid_engine(), cases)
    assert results["total_cases"] == len(cases)
    report = format_report(results)
    assert "Binary intervention" in report
