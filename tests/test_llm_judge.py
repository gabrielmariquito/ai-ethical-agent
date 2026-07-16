from ethical_agent.engine import CompositeEngine, RuleBasedEngine
from ethical_agent.llm import MockLLM
from ethical_agent.llm_judge import LLMJudgeEngine
from ethical_agent.policy import Policy
from ethical_agent.types import ActionContext, Decision

from test_engine import POLICY


def _policy():
    return Policy.from_dict(POLICY)


def test_judge_allow():
    llm = MockLLM(
        default='{"decision": "ALLOW", "reason": "benign", "confidence": 0.9}'
    )
    judge = LLMJudgeEngine(llm, _policy())
    verdict = judge.evaluate(ActionContext(content="hello"))
    assert verdict.decision is Decision.ALLOW


def test_judge_deny_with_match_trace():
    llm = MockLLM(
        default='{"decision": "DENY", "reason": "violates R-DENY", "confidence": 0.8}'
    )
    judge = LLMJudgeEngine(llm, _policy())
    verdict = judge.evaluate(ActionContext(content="bad request"))
    assert verdict.decision is Decision.DENY
    assert verdict.matches[0].rule_id == "LLM-JUDGE"


def test_judge_unparseable_fails_closed():
    judge = LLMJudgeEngine(MockLLM(default="I think it is fine!"), _policy())
    verdict = judge.evaluate(ActionContext(content="hello"))
    assert verdict.decision is Decision.DENY
    assert "fail closed" in verdict.reason


def test_judge_rewrite_without_safe_request_becomes_deny():
    llm = MockLLM(
        default='{"decision": "REWRITE", "reason": "needs cleanup", "safe_request": ""}'
    )
    judge = LLMJudgeEngine(llm, _policy())
    verdict = judge.evaluate(ActionContext(content="something"))
    assert verdict.decision is Decision.DENY


def test_composite_rule_engine_overrides_lenient_judge():
    judge = LLMJudgeEngine(
        MockLLM(default='{"decision": "ALLOW", "reason": "looks fine"}'), _policy()
    )
    composite = CompositeEngine([RuleBasedEngine(_policy()), judge])
    verdict = composite.evaluate(ActionContext(content="please hack the bank"))
    assert verdict.decision is Decision.DENY
