import json

import pytest

from ethical_agent.agent import GuardedAgent
from ethical_agent.audit import AuditLogger
from ethical_agent.engine import PolicyEngine, RuleBasedEngine
from ethical_agent.llm import MockLLM
from ethical_agent.policy import Policy
from ethical_agent.types import Decision, Stage

from test_engine import POLICY


@pytest.fixture
def engine():
    return RuleBasedEngine(Policy.from_dict(POLICY))


def test_benign_input_reaches_llm(engine):
    llm = MockLLM(default="Brasilia.")
    agent = GuardedAgent(engine=engine, llm=llm)
    result = agent.process("what is the capital of Brazil?")
    assert result.status == "ok"
    assert result.message == "Brasilia."
    assert len(llm.calls) == 1


def test_denied_input_never_reaches_llm(engine):
    llm = MockLLM()
    agent = GuardedAgent(engine=engine, llm=llm)
    result = agent.process("please hack the bank")
    assert result.status == "denied"
    assert llm.calls == []
    assert "R-DENY" in result.message


def test_rewritten_input_is_what_the_llm_sees(engine):
    llm = MockLLM(default="ok")
    agent = GuardedAgent(engine=engine, llm=llm)
    result = agent.process("hacking tutorials")
    assert result.status == "ok"
    assert llm.calls[0][-1]["content"] == "defensive: hacking tutorials"
    assert result.trace["rewritten_input"] == "defensive: hacking tutorials"


def test_output_pii_is_redacted(engine):
    llm = MockLLM(default="contact bob@example.com for help")
    agent = GuardedAgent(engine=engine, llm=llm)
    result = agent.process("how do I get support?")
    assert result.status == "ok"
    assert "bob@example.com" not in result.message
    assert "[REDACTED:R-REDACT]" in result.message


def test_escalation_blocks_and_shows_support_message(engine):
    llm = MockLLM()
    agent = GuardedAgent(engine=engine, llm=llm)
    result = agent.process("I want to hurt myself")
    assert result.status == "escalated"
    assert llm.calls == []
    assert "CVV" in result.message


def test_audit_log_written(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(
        engine=engine, llm=MockLLM(), audit=AuditLogger(log_path)
    )
    agent.process("what is the capital of Brazil?")
    agent.process("please hack the bank")
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["status"] == "ok"
    assert records[1]["status"] == "denied"
    assert records[1]["input_verdict"]["decision"] == "DENY"


class _BrokenEngine(PolicyEngine):
    name = "broken"

    def evaluate(self, action):
        raise RuntimeError("boom")


def test_check_fails_closed():
    agent = GuardedAgent(engine=_BrokenEngine())
    verdict = agent.check("anything", Stage.INPUT)
    assert verdict.decision is Decision.DENY
    assert "fail closed" in verdict.reason


def test_process_requires_llm(engine):
    agent = GuardedAgent(engine=engine)
    with pytest.raises(RuntimeError, match="requires an LLMClient"):
        agent.process("hello")
