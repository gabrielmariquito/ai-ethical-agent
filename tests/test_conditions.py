import pytest

from ethical_agent.conditions import (
    Condition,
    ConditionError,
    condition_from_dict,
    register_condition_type,
)
from ethical_agent.types import Evidence


def test_keyword_is_case_insensitive_with_span():
    cond = condition_from_dict({"type": "keyword", "value": "Hack"})
    evidence = cond.evaluate("how to HACK a server")
    assert len(evidence) == 1
    assert evidence[0].matched_text == "HACK"
    assert evidence[0].span == (7, 11)


def test_keyword_whole_word():
    cond = condition_from_dict(
        {"type": "keyword", "value": "curso", "whole_word": True}
    )
    assert cond.evaluate("um curso de seguranca")
    assert not cond.evaluate("um recurso de seguranca")


def test_regex_collects_all_matches():
    cond = condition_from_dict(
        {"type": "regex", "pattern": r"\b\d{3}-\d{2}\b", "flags": "i"}
    )
    evidence = cond.evaluate("ids 123-45 and 678-90 here")
    assert [e.matched_text for e in evidence] == ["123-45", "678-90"]
    assert all(e.span is not None for e in evidence)


def test_regex_invalid_pattern_raises():
    with pytest.raises(ConditionError):
        condition_from_dict({"type": "regex", "pattern": "([unclosed"})


def test_any_collects_evidence_from_every_branch():
    cond = condition_from_dict(
        {
            "type": "any",
            "conditions": [
                {"type": "keyword", "value": "alpha"},
                {"type": "keyword", "value": "beta"},
            ],
        }
    )
    evidence = cond.evaluate("alpha and beta")
    assert len(evidence) == 2
    assert not cond.evaluate("gamma only")


def test_all_requires_every_branch():
    cond = condition_from_dict(
        {
            "type": "all",
            "conditions": [
                {"type": "keyword", "value": "hack"},
                {"type": "keyword", "value": "educational"},
            ],
        }
    )
    assert cond.evaluate("educational hacking material")
    assert not cond.evaluate("hacking material")


def test_not_inverts():
    cond = condition_from_dict(
        {"type": "not", "condition": {"type": "keyword", "value": "disclaimer"}}
    )
    assert cond.evaluate("no warning here")
    assert not cond.evaluate("a disclaimer is present")


def test_keyword_evaluate_default_still_capped_at_fifty():
    cond = condition_from_dict({"type": "keyword", "value": "x"})
    text = " ".join("x" for _ in range(80))
    assert len(cond.evaluate(text)) == 50


def test_keyword_evaluate_unbounded_with_limit_none():
    cond = condition_from_dict({"type": "keyword", "value": "x"})
    text = " ".join("x" for _ in range(80))
    assert len(cond.evaluate(text, limit=None)) == 80


def test_regex_evaluate_default_still_capped_at_fifty():
    cond = condition_from_dict({"type": "regex", "pattern": r"\d+"})
    text = " ".join(str(i) for i in range(80))
    assert len(cond.evaluate(text)) == 50


def test_regex_evaluate_unbounded_with_limit_none():
    cond = condition_from_dict({"type": "regex", "pattern": r"\d+"})
    text = " ".join(str(i) for i in range(80))
    assert len(cond.evaluate(text, limit=None)) == 80


def test_any_evaluate_default_still_capped_at_fifty():
    cond = condition_from_dict(
        {
            "type": "any",
            "conditions": [
                {"type": "keyword", "value": "aa"},
                {"type": "keyword", "value": "bb"},
            ],
        }
    )
    text = " ".join(["aa"] * 40 + ["bb"] * 40)
    assert len(cond.evaluate(text)) == 50


def test_any_evaluate_unbounded_propagates_to_subconditions():
    cond = condition_from_dict(
        {
            "type": "any",
            "conditions": [
                {"type": "keyword", "value": "aa"},
                {"type": "keyword", "value": "bb"},
            ],
        }
    )
    text = " ".join(["aa"] * 40 + ["bb"] * 40)
    assert len(cond.evaluate(text, limit=None)) == 80


def test_all_evaluate_default_still_capped_at_fifty():
    cond = condition_from_dict(
        {
            "type": "all",
            "conditions": [
                {"type": "keyword", "value": "aa"},
                {"type": "regex", "pattern": r"\d+"},
            ],
        }
    )
    text = " ".join(["aa"] * 80) + " " + " ".join(str(i) for i in range(80))
    assert len(cond.evaluate(text)) == 50


def test_all_evaluate_unbounded_propagates_to_subconditions():
    cond = condition_from_dict(
        {
            "type": "all",
            "conditions": [
                {"type": "keyword", "value": "aa"},
                {"type": "regex", "pattern": r"\d+"},
            ],
        }
    )
    text = " ".join(["aa"] * 80) + " " + " ".join(str(i) for i in range(80))
    assert len(cond.evaluate(text, limit=None)) == 160


def test_unknown_type_raises():
    with pytest.raises(ConditionError):
        condition_from_dict({"type": "concept", "value": "privacy"})


def test_registry_extension_point():
    class AlwaysMatch(Condition):
        type_name = "always"

        def evaluate(self, text):
            return [Evidence(description="always matches")]

        def to_dict(self):
            return {"type": "always"}

    register_condition_type("always", lambda data: AlwaysMatch())
    cond = condition_from_dict({"type": "always"})
    assert cond.evaluate("anything")
