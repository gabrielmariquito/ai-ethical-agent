import json
from pathlib import Path

from ethical_agent import RuleBasedEngine, build_check_audit_record
from ethical_agent.policy import Policy
from ethical_agent.types import ActionContext, Stage


def _engine():
    return RuleBasedEngine(
        Policy.from_dict(
            {
                "schema_version": "1.0",
                "rules": [
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
                        "id": "R-TEMPLATE",
                        "principle": "transparency",
                        "severity": "low",
                        "scopes": ["output"],
                        "effect": "REWRITE",
                        "rewrite_template": "{content}\n\n---\nnotice",
                        "condition": {"type": "keyword", "value": "diagnosis"},
                    },
                ],
            }
        )
    )


def test_build_check_audit_record_redact_suppresses_raw_content():
    engine = _engine()
    text = "contact bob@example.com for help"
    verdict = engine.evaluate(ActionContext(content=text, stage=Stage.OUTPUT))
    record = build_check_audit_record(engine, verdict, Stage.OUTPUT, text)
    assert record["status"] == "ok"
    assert record["output_verdict"]["decision"] == "REWRITE"
    assert "raw_response" not in record
    assert json.dumps(record)  # fully serializable


def test_build_check_audit_record_template_only_retains_raw_content():
    engine = _engine()
    text = "a diagnosis of seasonal allergy"
    verdict = engine.evaluate(ActionContext(content=text, stage=Stage.OUTPUT))
    record = build_check_audit_record(engine, verdict, Stage.OUTPUT, text)
    assert record["output_verdict"]["decision"] == "REWRITE"
    assert record["raw_response"] == text


def test_build_check_audit_record_has_no_message_field():
    # Deliberate: check() never calls an LLM and generates no message for
    # anyone -- unlike GuardedAgent.process, which always records
    # result.message. Forcing an empty/redundant "message" here would be
    # noise, not signal. See AUDIT_GUIDE.pt-BR.md's field-presence table.
    engine = _engine()
    text = "contact bob@example.com for help"
    verdict = engine.evaluate(ActionContext(content=text, stage=Stage.OUTPUT))
    record = build_check_audit_record(engine, verdict, Stage.OUTPUT, text)
    assert "message" not in record


def test_build_check_audit_record_input_stage_always_retains_input():
    engine = _engine()
    text = "what is the capital of Brazil?"
    verdict = engine.evaluate(ActionContext(content=text, stage=Stage.INPUT))
    record = build_check_audit_record(engine, verdict, Stage.INPUT, text)
    assert record["input"] == text
    assert "input_verdict" in record


def test_gui_app_no_longer_defines_its_own_check_audit_record():
    # Read the source directly rather than `import gui_app`: importing it
    # requires tkinter to be installed and the CWD/sys.path to include the
    # repo root, neither of which this assertion should depend on -- the
    # source text is enough to prove the duplicate function is gone and the
    # shared helper is what's actually called.
    source_path = Path(__file__).resolve().parent.parent / "gui_app.py"
    source = source_path.read_text(encoding="utf-8")
    assert "def check_audit_record(" not in source
    assert "build_check_audit_record(" in source  # actually called, not just imported


def test_gui_app_uses_shared_llm_provenance_helpers():
    # Same reasoning as above: gui_app.py must call the shared resolve_llm /
    # describe_llm_provenance from ethical_agent.llm instead of reimplementing
    # its own classification of what produced (or simulated) the content --
    # otherwise the CLI and GUI could silently drift on this.
    source_path = Path(__file__).resolve().parent.parent / "gui_app.py"
    source = source_path.read_text(encoding="utf-8")
    assert "def build_llm(" in source  # thin wrapper still present
    assert "resolve_llm(" in source
    assert "describe_llm_provenance(" in source
