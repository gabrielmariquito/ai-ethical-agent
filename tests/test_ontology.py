import pytest

from ethical_agent.conditions import ConditionError, condition_from_dict
from ethical_agent.ontology import (
    Ontology,
    OntologyError,
    register_concept_condition,
)

MINI_ONTOLOGY = {
    "schema_version": "1.0",
    "concepts": [
        {
            "id": "biometric_data",
            "label": "Biometric data",
            "terms": [{"term": "facial recognition"}],
        },
        {
            "id": "sensitive_data",
            "label": "Sensitive data",
            "terms": [{"term": "sensitive data"}],
        },
        {
            "id": "personal_data",
            "label": "Personal data",
            "terms": [{"term": "personal data"}],
        },
        {
            "id": "data_collection",
            "label": "Data collection",
            "terms": [{"term": "collect\\w*", "regex": True}],
        },
        {
            "id": "consent",
            "label": "Consent",
            "terms": [{"term": "with consent"}],
        },
    ],
    "relations": [
        {"subject": "biometric_data", "predicate": "is_a", "object": "sensitive_data"},
        {"subject": "sensitive_data", "predicate": "is_a", "object": "personal_data"},
    ],
    "norms": [
        {
            "id": "N-1",
            "principle": "privacy",
            "severity": "high",
            "effect": "ESCALATE",
            "when": ["data_collection", "sensitive_data"],
            "unless": ["consent"],
            "description": "sensitive collection",
        }
    ],
}


@pytest.fixture
def ontology():
    return Ontology.from_dict(MINI_ONTOLOGY)


def test_activation_propagates_along_is_a_chain(ontology):
    activation = ontology.activate("we store facial recognition templates")
    assert "biometric_data" in activation
    assert "sensitive_data" in activation
    assert "personal_data" in activation
    inferred = activation["personal_data"][0]
    assert "--is_a-->" in inferred.description
    assert inferred.matched_text == "facial recognition"


def test_activation_requires_grounding(ontology):
    activation = ontology.activate("the weather is nice today")
    assert activation == {}


def test_unknown_relation_reference_rejected():
    data = {
        "concepts": [{"id": "a", "label": "a", "terms": [{"term": "a"}]}],
        "relations": [{"subject": "a", "predicate": "is_a", "object": "ghost"}],
        "norms": [],
    }
    with pytest.raises(OntologyError, match="unknown concept"):
        Ontology.from_dict(data)


def test_norm_with_unknown_concept_rejected():
    data = {
        "concepts": [{"id": "a", "label": "a", "terms": [{"term": "a"}]}],
        "norms": [
            {"id": "N-1", "principle": "x", "effect": "DENY", "when": ["ghost"]}
        ],
    }
    with pytest.raises(OntologyError, match="unknown concept"):
        Ontology.from_dict(data)


def test_norm_rewrite_effect_rejected():
    data = {
        "concepts": [{"id": "a", "label": "a", "terms": [{"term": "a"}]}],
        "norms": [
            {"id": "N-1", "principle": "x", "effect": "REWRITE", "when": ["a"]}
        ],
    }
    with pytest.raises(OntologyError, match="norm effect"):
        Ontology.from_dict(data)


def test_concept_condition_with_inference(ontology):
    register_concept_condition(ontology)
    cond = condition_from_dict({"type": "concept", "concept": "personal_data"})
    evidence = cond.evaluate("our app uses facial recognition at the door")
    assert evidence
    assert "--is_a-->" in evidence[0].description
    assert not cond.evaluate("totally unrelated text")


def test_concept_condition_direct_only(ontology):
    register_concept_condition(ontology)
    cond = condition_from_dict(
        {"type": "concept", "concept": "personal_data", "direct_only": True}
    )
    assert not cond.evaluate("our app uses facial recognition at the door")
    assert cond.evaluate("we process personal data here")


def test_concept_condition_unknown_concept(ontology):
    register_concept_condition(ontology)
    with pytest.raises(ConditionError, match="unknown ontology concept"):
        condition_from_dict({"type": "concept", "concept": "ghost"})
