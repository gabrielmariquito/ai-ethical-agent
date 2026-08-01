import json

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


def test_build_check_audit_record_input_stage_always_retains_input():
    engine = _engine()
    text = "what is the capital of Brazil?"
    verdict = engine.evaluate(ActionContext(content=text, stage=Stage.INPUT))
    record = build_check_audit_record(engine, verdict, Stage.INPUT, text)
    assert record["input"] == text
    assert "input_verdict" in record


def test_gui_app_no_longer_defines_its_own_check_audit_record():
    import gui_app

    assert not hasattr(gui_app, "check_audit_record")
    assert gui_app.build_check_audit_record is build_check_audit_record
