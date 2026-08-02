import json

import pytest

from ethical_agent.agent import GuardedAgent
from ethical_agent.audit import AuditLogger
from ethical_agent.engine import PolicyEngine, RuleBasedEngine
from ethical_agent.llm import LLMClient, MockLLM
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


def test_denied_input_refusal_text_is_recorded(engine, tmp_path):
    # Before this field existed, a DENY record had status/input/input_verdict
    # but no trace of what the user was actually told -- an auditor could
    # see *that* a request was refused, never *what the refusal said*.
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=MockLLM(), audit=AuditLogger(log_path))
    result = agent.process("please hack the bank")
    assert result.status == "denied"
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["message"] == result.message
    assert "R-DENY" in record["message"]


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


def test_redacted_output_pii_not_retained_in_evidence(engine, tmp_path):
    llm = MockLLM(default="contact bob@example.com for help")
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=llm, audit=AuditLogger(log_path))
    result = agent.process("how do I get support?")
    assert result.status == "ok"
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    redact_match = next(
        m for m in record["output_verdict"]["matches"] if m["rule_id"] == "R-REDACT"
    )
    # a redact rule's whole purpose is removing the matched value; the
    # verdict's own evidence must not smuggle it back in.
    matched_texts = [e["matched_text"] for e in redact_match["evidence"]]
    assert "bob@example.com" not in matched_texts
    assert all(text is None for text in matched_texts)


def test_redacted_output_raw_response_not_retained_in_trace(engine):
    llm = MockLLM(default="contact bob@example.com for help")
    agent = GuardedAgent(engine=engine, llm=llm)
    result = agent.process("how do I get support?")
    assert result.status == "ok"
    assert result.output_verdict.suppresses_raw_content is True
    assert "raw_response" not in result.trace


def test_template_only_output_rewrite_retains_raw_response(engine):
    raw = "A common diagnosis for this symptom is seasonal allergy."
    llm = MockLLM(default=raw)
    agent = GuardedAgent(engine=engine, llm=llm)
    result = agent.process("what could cause sneezing?")
    assert result.status == "ok"
    assert result.output_verdict.decision is Decision.REWRITE
    assert result.output_verdict.suppresses_raw_content is False
    assert result.trace["raw_response"] == raw
    assert raw in result.message
    assert "Notice: educational only." in result.message


def test_selfharm_denies_and_shows_support_message(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    llm = MockLLM()
    agent = GuardedAgent(engine=engine, llm=llm, audit=AuditLogger(log_path))
    result = agent.process("I want to hurt myself")
    assert result.status == "denied"
    assert llm.calls == []
    # Two different guarantees: the user actually received the support
    # message (R-HARM-002's "surface help resources" obligation, honored)...
    assert "CVV" in result.message
    # ...and that delivery is independently auditable after the fact --
    # previously the audit record had no trace of what was said at all.
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "CVV" in record["message"]


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


def test_audit_log_records_config_versions(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=MockLLM(), audit=AuditLogger(log_path))
    agent.process("what is the capital of Brazil?")
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "config_versions" in record
    assert "policy_version" in record["config_versions"]


def test_audit_log_records_llm_provenance_when_given(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    provenance = {"kind": "real", "model": "llama3.2:3b", "backend": "ollama_local"}
    agent = GuardedAgent(
        engine=engine,
        llm=MockLLM(),
        audit=AuditLogger(log_path),
        llm_provenance=provenance,
    )
    agent.process("what is the capital of Brazil?")
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["llm_provenance"] == provenance


def test_audit_log_omits_llm_provenance_when_not_given(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=MockLLM(), audit=AuditLogger(log_path))
    agent.process("what is the capital of Brazil?")
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "llm_provenance" not in record


def test_audit_log_records_conversation_id_and_turn_index_when_given(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=MockLLM(), audit=AuditLogger(log_path))
    agent.process(
        "what is the capital of Brazil?",
        conversation_id="conv-1",
        turn_index=1,
    )
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["conversation_id"] == "conv-1"
    assert record["turn_index"] == 1


def test_audit_log_omits_conversation_id_and_turn_index_when_not_given(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=MockLLM(), audit=AuditLogger(log_path))
    agent.process("what is the capital of Brazil?")
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert "conversation_id" not in record
    assert "turn_index" not in record


def test_denied_output_is_never_retained(engine, tmp_path):
    full_response = (
        "Sure, here is how to make a bomb at home: mix reagent XYZ123 with "
        "compound ABC789 for exactly three minutes, then attach a QRS-detonator."
    )
    llm = MockLLM(default=full_response)
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=llm, audit=AuditLogger(log_path))
    result = agent.process("what is the capital of Brazil?")
    assert result.status == "denied"
    assert result.response is None
    assert "raw_response" not in result.trace
    log_text = log_path.read_text(encoding="utf-8")
    # the rule engine's evidence legitimately surfaces the short matched
    # keyword for auditability, but the full generated (blocked) content
    # must never be persisted anywhere.
    assert full_response not in log_text
    assert "XYZ123" not in log_text
    assert "QRS-detonator" not in log_text
    # the refusal text itself IS recorded (it's guardrail-generated, from
    # rule rationale/user_message, never from the blocked content) -- but it
    # must still carry none of the content the retention rule protects.
    record = json.loads(log_text.strip())
    assert record["message"] == result.message
    assert full_response not in record["message"]
    assert "XYZ123" not in record["message"]
    assert "QRS-detonator" not in record["message"]


def test_no_history_produces_same_two_message_list_as_before(engine):
    # Regression lock: calling process() without history/conversation_id/
    # turn_index must reproduce today's exact message list, unchanged.
    llm = MockLLM(default="Brasilia.")
    agent = GuardedAgent(engine=engine, llm=llm)
    agent.process("what is the capital of Brazil?")
    assert llm.calls == [
        [
            {"role": "system", "content": agent.system_prompt},
            {"role": "user", "content": "what is the capital of Brazil?"},
        ]
    ]


def test_history_is_threaded_into_llm_messages(engine):
    llm = MockLLM(responses=["Brasilia.", "Around 203 million."])
    agent = GuardedAgent(engine=engine, llm=llm)
    turn1 = agent.process("what is the capital of Brazil?")
    assert turn1.status == "ok"
    turn2 = agent.process("and what is its population?", history=[turn1])
    assert turn2.status == "ok"
    assert llm.calls[1] == [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user", "content": "what is the capital of Brazil?"},
        {"role": "assistant", "content": "Brasilia."},
        {"role": "user", "content": "and what is its population?"},
    ]


def test_history_skips_input_denied_prior_turn(engine):
    llm = MockLLM(default="ok")
    agent = GuardedAgent(engine=engine, llm=llm)
    turn1 = agent.process("please hack the bank")
    assert turn1.status == "denied"
    assert llm.calls == []  # input DENY never reached the model originally
    turn2 = agent.process("what is the capital of Brazil?", history=[turn1])
    assert turn2.status == "ok"
    assert len(llm.calls) == 1
    contents = [m["content"] for m in llm.calls[0]]
    assert not any("hack the bank" in c for c in contents)


def test_history_prior_output_denied_turn_leaks_nothing(engine, tmp_path):
    full_response = (
        "Sure, here is how to make a bomb at home: mix reagent XYZ123 with "
        "compound ABC789 for exactly three minutes, then attach a QRS-detonator."
    )
    log_path = tmp_path / "audit.jsonl"
    llm = MockLLM(responses=[full_response, "Brasilia."])
    agent = GuardedAgent(engine=engine, llm=llm, audit=AuditLogger(log_path))
    turn1 = agent.process("what is the capital of Brazil?")
    assert turn1.status == "denied"
    turn2 = agent.process("what is the capital of Brazil, again?", history=[turn1])
    assert turn2.status == "ok"
    for call in llm.calls:
        for message in call:
            assert full_response not in message["content"]
            assert "XYZ123" not in message["content"]
            assert "QRS-detonator" not in message["content"]
    log_text = log_path.read_text(encoding="utf-8")
    assert full_response not in log_text
    assert "XYZ123" not in log_text
    assert "QRS-detonator" not in log_text


def test_history_prior_redacted_output_turn_leaks_nothing(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    llm = MockLLM(responses=["contact bob@example.com for help", "Brasilia."])
    agent = GuardedAgent(engine=engine, llm=llm, audit=AuditLogger(log_path))
    turn1 = agent.process("how do I get support?")
    assert turn1.status == "ok"
    assert "bob@example.com" not in turn1.message
    turn2 = agent.process("what is the capital of Brazil?", history=[turn1])
    assert turn2.status == "ok"
    assert llm.calls[1][2] == {"role": "assistant", "content": turn1.message}
    for call in llm.calls:
        for message in call:
            assert "bob@example.com" not in message["content"]
    log_text = log_path.read_text(encoding="utf-8")
    assert "bob@example.com" not in log_text


class _BrokenEngine(PolicyEngine):
    name = "broken"

    def evaluate(self, action):
        raise RuntimeError("boom")


def test_check_fails_closed():
    agent = GuardedAgent(engine=_BrokenEngine())
    verdict = agent.check("anything", Stage.INPUT)
    assert verdict.decision is Decision.DENY
    assert verdict.system_error is True
    # the raw exception detail is kept for operators/audit ...
    assert "boom" in verdict.reason
    assert "fail closed" in verdict.reason


def test_engine_failure_does_not_leak_exception_to_user(engine):
    agent = GuardedAgent(engine=_BrokenEngine(), llm=MockLLM())
    result = agent.process("anything")
    assert result.status == "denied"
    # ... but never shown verbatim to the end user in the refusal message.
    assert "boom" not in result.message
    assert "fail closed" not in result.message


def test_process_requires_llm(engine):
    agent = GuardedAgent(engine=engine)
    with pytest.raises(RuntimeError, match="requires an LLMClient"):
        agent.process("hello")


class _BrokenLLM(LLMClient):
    def chat(self, messages):
        raise RuntimeError("boom")


def test_llm_failure_produces_system_error_and_audit_record(engine, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    agent = GuardedAgent(engine=engine, llm=_BrokenLLM(), audit=AuditLogger(log_path))
    result = agent.process("what is the capital of Brazil?")
    assert result.status == "system_error"
    assert result.response is None

    assert log_path.exists()
    record = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert record["status"] == "system_error"
    assert "boom" in record["llm_error"]


def test_llm_failure_does_not_leak_exception_to_user(engine):
    agent = GuardedAgent(engine=engine, llm=_BrokenLLM())
    result = agent.process("what is the capital of Brazil?")
    assert result.status == "system_error"
    assert "boom" not in result.message
