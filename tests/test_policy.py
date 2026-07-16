import pytest

from ethical_agent.policy import Policy, PolicyError, default_policy_path
from ethical_agent.types import Decision, Stage


def _minimal_rule(**overrides):
    rule = {
        "id": "R-1",
        "principle": "privacy",
        "severity": "high",
        "scopes": ["input"],
        "effect": "DENY",
        "condition": {"type": "keyword", "value": "secret"},
    }
    rule.update(overrides)
    return rule


def test_core_policy_loads_and_is_well_formed():
    policy = Policy.from_file(default_policy_path())
    assert policy.constraints, "core policy must define hard constraints"
    assert policy.rules, "core policy must define rules"
    assert all(rule.hard for rule in policy.constraints)
    assert all(rule.effect is Decision.DENY for rule in policy.constraints)
    deontics = {rule.deontic for rule in policy.rules}
    assert "prohibition" in deontics
    assert "obligation" in deontics


def test_duplicate_ids_rejected():
    data = {"rules": [_minimal_rule(), _minimal_rule()]}
    with pytest.raises(PolicyError, match="duplicate rule id"):
        Policy.from_dict(data)


def test_rewrite_requires_template_or_redact():
    data = {"rules": [_minimal_rule(effect="REWRITE")]}
    with pytest.raises(PolicyError, match="REWRITE effect requires"):
        Policy.from_dict(data)


def test_hard_constraint_rejects_exceptions():
    data = {
        "constraints": [
            _minimal_rule(
                effect=None, exceptions={"type": "keyword", "value": "edu"}
            )
        ]
    }
    data["constraints"][0].pop("effect")
    with pytest.raises(PolicyError, match="no exceptions"):
        Policy.from_dict(data)


def test_invalid_effect_rejected():
    data = {"rules": [_minimal_rule(effect="ALLOW")]}
    with pytest.raises(PolicyError):
        Policy.from_dict(data)


def test_invalid_regex_reports_rule_id():
    data = {
        "rules": [
            _minimal_rule(condition={"type": "regex", "pattern": "([bad"})
        ]
    }
    with pytest.raises(PolicyError, match="R-1"):
        Policy.from_dict(data)


def test_rules_for_puts_constraints_first():
    data = {
        "constraints": [_minimal_rule(id="C-1", effect=None)],
        "rules": [_minimal_rule(id="R-2")],
    }
    data["constraints"][0].pop("effect")
    policy = Policy.from_dict(data)
    ordered = policy.rules_for(Stage.INPUT)
    assert [r.id for r in ordered] == ["C-1", "R-2"]
