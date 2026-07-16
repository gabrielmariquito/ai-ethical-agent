import pytest

from ethical_agent.ontology import OntologyError
from ethical_agent.relaieo import (
    default_grounding_path,
    default_norms_path,
    default_relaieo_ttl,
    load_default_ontology,
    load_relaieo,
    parse_relaieo,
)


def test_parses_all_relaieo_native_classes():
    subjects = parse_relaieo(default_relaieo_ttl().read_text(encoding="utf-8"))
    classes = [k for k, v in subjects.items() if "owl:Class" in v["types"]]
    props = [k for k, v in subjects.items() if "owl:ObjectProperty" in v["types"]]
    assert len(classes) == 154
    assert len(props) == 25


def test_escaped_closing_quote_does_not_swallow_next_statement():
    subjects = parse_relaieo(default_relaieo_ttl().read_text(encoding="utf-8"))
    for name in ("interview_and_survey", "justice", "funder", "responsibility"):
        assert "owl:Class" in subjects[name]["types"], name


def test_external_namespace_classes_are_skipped():
    subjects = parse_relaieo(default_relaieo_ttl().read_text(encoding="utf-8"))
    assert "ethical_assessment" not in subjects
    assert "expectation" not in subjects


def test_triple_quoted_and_annotations_loaded():
    subjects = parse_relaieo(default_relaieo_ttl().read_text(encoding="utf-8"))
    bias = subjects["bias"]
    assert bias["subClassOf"] == ["identified_harm_risk"]
    assert "systemically prejudiced" in " ".join(bias["comment"])
    assert bias["provocation"]


def test_load_relaieo_ontology_only():
    ontology = load_relaieo(default_relaieo_ttl())
    assert len(ontology.concepts) == 154
    assert ontology.norms == []
    bias = ontology.concepts["bias"]
    assert bias.principle == "fairness"
    assert bias.provocation
    assert bias.terms == []
    assert ontology.activate("this model shows clear bias") == {}


def test_grounding_enables_activation_and_is_a_propagation():
    ontology = load_relaieo(default_relaieo_ttl(), default_grounding_path())
    activation = ontology.activate("this model shows clear bias")
    assert "bias" in activation
    assert "identified_harm_risk" in activation


def test_load_default_ontology_has_grounding_and_norms():
    ontology = load_default_ontology()
    assert len(ontology.concepts) == 154
    assert len(ontology.norms) >= 6
    assert ontology.concepts["surveillance"].terms
    assert ontology.concepts["design"].terms


def test_grounding_unknown_concept_rejected(tmp_path):
    bad = tmp_path / "grounding.json"
    bad.write_text('{"grounding": {"not_a_concept": ["foo"]}}', encoding="utf-8")
    with pytest.raises(OntologyError, match="unknown RelAIEO concept"):
        load_relaieo(default_relaieo_ttl(), bad)


def test_default_paths_exist():
    assert default_relaieo_ttl().exists()
    assert default_grounding_path().exists()
    assert default_norms_path().exists()
