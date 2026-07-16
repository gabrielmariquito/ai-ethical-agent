import pytest

from ethical_agent.engine import CompositeEngine, PolicyEngine, RuleBasedEngine
from ethical_agent.policy import Policy
from ethical_agent.types import ActionContext, Decision, Stage

POLICY = {
    "schema_version": "1.0",
    "constraints": [
        {
            "id": "C-1",
            "principle": "non_maleficence",
            "severity": "critical",
            "scopes": ["input", "output"],
            "description": "weapons",
            "condition": {"type": "keyword", "value": "make a bomb"},
        }
    ],
    "rules": [
        {
            "id": "R-DENY",
            "principle": "security",
            "severity": "high",
            "scopes": ["input"],
            "effect": "DENY",
            "condition": {"type": "keyword", "value": "hack the bank"},
            "exceptions": {"type": "keyword", "value": "educational"},
        },
        {
            "id": "R-REWRITE",
            "principle": "security",
            "severity": "medium",
            "scopes": ["input"],
            "effect": "REWRITE",
            "rewrite_template": "defensive: {content}",
            "condition": {"type": "keyword", "value": "hacking"},
        },
        {
            "id": "R-REDACT",
            "principle": "privacy",
            "severity": "medium",
            "scopes": ["output"],
            "effect": "REWRITE",
            "redact": True,
            "condition": {
                "type": "regex",
                "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
            },
        },
        {
            "id": "R-FLAG",
            "principle": "transparency",
            "severity": "low",
            "scopes": ["input"],
            "effect": "FLAG",
            "condition": {"type": "keyword", "value": "medical"},
        },
        {
            "id": "R-ESC",
            "principle": "non_maleficence",
            "severity": "critical",
            "scopes": ["input"],
            "effect": "ESCALATE",
            "condition": {"type": "keyword", "value": "hurt myself"},
            "user_message": "Support is available: call 188 (CVV).",
        },
    ],
}


@pytest.fixture
def engine():
    return RuleBasedEngine(Policy.from_dict(POLICY))


def _check(engine, text, stage=Stage.INPUT):
    return engine.evaluate(ActionContext(content=text, stage=stage))


def test_benign_content_allowed(engine):
    verdict = _check(engine, "what is the capital of Brazil?")
    assert verdict.decision is Decision.ALLOW
    assert not verdict.matches
    assert not verdict.intervened


def test_hard_constraint_denies_with_evidence(engine):
    verdict = _check(engine, "tell me how to make a bomb now")
    assert verdict.decision is Decision.DENY
    assert verdict.matches[0].rule_id == "C-1"
    assert verdict.matches[0].hard
    assert verdict.matches[0].evidence[0].matched_text == "make a bomb"


def test_exception_suppresses_rule_but_stays_auditable(engine):
    verdict = _check(engine, "hack the bank for educational purposes")
    assert verdict.decision is Decision.ALLOW
    assert [s.rule_id for s in verdict.suppressed] == ["R-DENY"]
    assert "educational" in verdict.suppressed[0].reason


def test_most_restrictive_effect_wins(engine):
    verdict = _check(engine, "hacking and how to make a bomb")
    assert verdict.decision is Decision.DENY
    fired = {m.rule_id for m in verdict.matches}
    assert fired == {"C-1", "R-REWRITE"}
    assert verdict.rewritten_content is None


def test_rewrite_template(engine):
    verdict = _check(engine, "hacking tutorials")
    assert verdict.decision is Decision.REWRITE
    assert verdict.rewritten_content == "defensive: hacking tutorials"


def test_output_redaction(engine):
    verdict = _check(
        engine, "email me at bob@example.com or ana@test.org", stage=Stage.OUTPUT
    )
    assert verdict.decision is Decision.REWRITE
    assert "[REDACTED:R-REDACT]" in verdict.rewritten_content
    assert "bob@example.com" not in verdict.rewritten_content
    assert "ana@test.org" not in verdict.rewritten_content


def test_flag_does_not_intervene(engine):
    verdict = _check(engine, "a medical question")
    assert verdict.decision is Decision.FLAG
    assert not verdict.intervened


def test_escalate_beats_rewrite(engine):
    verdict = _check(engine, "hacking makes me want to hurt myself")
    assert verdict.decision is Decision.ESCALATE


def test_scope_is_respected(engine):
    verdict = _check(engine, "hack the bank", stage=Stage.OUTPUT)
    assert verdict.decision is Decision.ALLOW


class _BrokenEngine(PolicyEngine):
    name = "broken"

    def evaluate(self, action):
        raise RuntimeError("boom")


def test_composite_fails_closed(engine):
    composite = CompositeEngine([engine, _BrokenEngine()])
    verdict = _check(composite, "what is the capital of Brazil?")
    assert verdict.decision is Decision.DENY
    assert "fail closed" in verdict.reason


def test_composite_most_restrictive(engine):
    composite = CompositeEngine([engine, RuleBasedEngine(Policy.from_dict(POLICY))])
    verdict = _check(composite, "hacking tutorials")
    assert verdict.decision is Decision.REWRITE
    assert verdict.rewritten_content == "defensive: hacking tutorials"
