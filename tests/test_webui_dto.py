from ethical_agent.agent import AgentResult
from ethical_agent.types import Decision, RuleMatch, Severity, Stage, Verdict
from ethical_agent.webui.dto import classify_intervention, turn_result_to_dict


def _verdict(decision, stage, matches=None):
    return Verdict(decision=decision, stage=stage, engine="rule-based", matches=matches or [])


def _match(rule_id, effect, redacted):
    return RuleMatch(
        rule_id=rule_id,
        principle="privacy",
        deontic="prohibition",
        severity=Severity.MEDIUM,
        effect=effect,
        rationale="",
        hard=False,
        redacted=redacted,
        evidence=[],
    )


def test_classify_intervention_deny_at_input_wins_over_everything():
    assert classify_intervention("DENY", "REWRITE") == "blocked_input"


def test_classify_intervention_deny_at_output():
    assert classify_intervention("ALLOW", "DENY") == "blocked_output"


def test_classify_intervention_rewrite_at_either_stage():
    assert classify_intervention("REWRITE", None) == "rewrite"
    assert classify_intervention("ALLOW", "REWRITE") == "rewrite"


def test_classify_intervention_none():
    assert classify_intervention("ALLOW", "ALLOW") == "none"
    assert classify_intervention("FLAG", None) == "none"  # FLAG alone is not an intervention


def test_turn_result_to_dict_response_none_when_output_redacted():
    output_verdict = _verdict(Decision.REWRITE, Stage.OUTPUT, matches=[_match("R-PRIV-002", Decision.REWRITE, redacted=True)])
    result = AgentResult(
        status="ok",
        message="[REDACTED]",
        response="the raw pii-laden text",
        input_verdict=_verdict(Decision.ALLOW, Stage.INPUT),
        output_verdict=output_verdict,
    )
    payload = turn_result_to_dict(result, {"kind": "mock_requested"}, 1, [])
    assert payload["response"] is None


def test_turn_result_to_dict_response_retained_when_output_rewrite_is_template_only():
    output_verdict = _verdict(Decision.REWRITE, Stage.OUTPUT, matches=[_match("R-TRANS-001", Decision.REWRITE, redacted=False)])
    result = AgentResult(
        status="ok",
        message="rewritten with disclaimer",
        response="original text",
        input_verdict=_verdict(Decision.ALLOW, Stage.INPUT),
        output_verdict=output_verdict,
    )
    payload = turn_result_to_dict(result, {"kind": "mock_requested"}, 1, [])
    assert payload["response"] == "original text"


def test_turn_result_to_dict_response_retained_when_output_allows():
    result = AgentResult(
        status="ok",
        message="fine",
        response="fine",
        input_verdict=_verdict(Decision.ALLOW, Stage.INPUT),
        output_verdict=_verdict(Decision.ALLOW, Stage.OUTPUT),
    )
    payload = turn_result_to_dict(result, {"kind": "mock_requested"}, 1, [])
    assert payload["response"] == "fine"
