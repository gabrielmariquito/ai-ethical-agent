import json

import pytest

from ethical_agent.__main__ import main
from test_engine import POLICY


@pytest.fixture
def policy_path(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps(POLICY), encoding="utf-8")
    return p


def _base_argv(policy_path, audit_log):
    return ["--engine", "rule", "--policy", str(policy_path), "--audit-log", str(audit_log)]


def _read_records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").strip().splitlines()]


def test_check_writes_audit_record(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    argv = _base_argv(policy_path, log_path) + [
        "check", "what is the capital of Brazil?",
    ]
    code = main(argv)
    assert code == 0
    records = _read_records(log_path)
    assert len(records) == 1
    record = records[0]
    assert record["status"] == "ok"
    assert record["engine"] == "rule-based"
    assert "policy_version" in record["config_versions"]
    assert "event_id" in record
    assert "timestamp" in record


def test_process_writes_audit_record_with_config_versions(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    argv = _base_argv(policy_path, log_path) + [
        "process", "what is the capital of Brazil?", "--mock",
    ]
    code = main(argv)
    assert code == 0
    records = _read_records(log_path)
    assert len(records) == 1
    assert "config_versions" in records[0]
    assert "policy_version" in records[0]["config_versions"]


def test_demo_writes_one_record_per_case(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    argv = _base_argv(policy_path, log_path) + ["demo"]
    code = main(argv)
    assert code == 0
    records = _read_records(log_path)
    assert len(records) == 7


def test_no_audit_flag_no_longer_exists(policy_path, tmp_path):
    log_path = tmp_path / "audit.jsonl"
    argv = _base_argv(policy_path, log_path) + [
        "--no-audit", "process", "what is the capital of Brazil?", "--mock",
    ]
    with pytest.raises(SystemExit):
        main(argv)


def test_env_var_no_longer_disables_audit(policy_path, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ETHICAL_AGENT_NO_AUDIT", "1")
    log_path = tmp_path / "audit.jsonl"
    argv = _base_argv(policy_path, log_path) + [
        "process", "what is the capital of Brazil?", "--mock",
    ]
    code = main(argv)
    assert code == 0
    records = _read_records(log_path)
    assert len(records) == 1


def test_eval_never_writes_audit(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "case-1",
                        "content": "what is the capital of Brazil?",
                        "stage": "input",
                        "expected_decision": "ALLOW",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    argv = _base_argv(policy_path, log_path) + [
        "eval", "--dataset", str(dataset_path), "--json",
    ]
    code = main(argv)
    assert code == 0
    assert not log_path.exists()


def test_check_record_shape_matches_process_record_shape(policy_path, tmp_path, capsys):
    check_log = tmp_path / "check_audit.jsonl"
    process_log = tmp_path / "process_audit.jsonl"

    main(_base_argv(policy_path, check_log) + ["check", "what is the capital of Brazil?"])
    main(
        _base_argv(policy_path, process_log)
        + ["process", "what is the capital of Brazil?", "--mock"]
    )

    check_record = _read_records(check_log)[0]
    process_record = _read_records(process_log)[0]

    shared_keys = {"status", "engine", "config_versions", "event_id", "timestamp"}
    assert shared_keys <= check_record.keys()
    assert shared_keys <= process_record.keys()
    assert isinstance(check_record["config_versions"], dict) and check_record["config_versions"]
    assert isinstance(process_record["config_versions"], dict) and process_record["config_versions"]
    assert check_record["status"] in ("ok", "denied")
    assert process_record["status"] in ("ok", "denied")
    # same trace-key vocabulary too: a check on stage=input produces the same
    # keys GuardedAgent.process's input stage would.
    assert "input" in check_record and "input" in process_record
    assert "input_verdict" in check_record and "input_verdict" in process_record


def test_check_output_stage_denied_content_not_retained(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    full_response = (
        "Sure, here is how to make a bomb at home: mix reagent XYZ123 with "
        "compound ABC789 for exactly three minutes, then attach a QRS-detonator."
    )
    argv = _base_argv(policy_path, log_path) + [
        "check", full_response, "--stage", "output",
    ]
    code = main(argv)
    assert code == 2

    log_text = log_path.read_text(encoding="utf-8")
    assert full_response not in log_text
    assert "XYZ123" not in log_text
    assert "QRS-detonator" not in log_text

    record = _read_records(log_path)[0]
    assert record["status"] == "denied"
    assert "raw_response" not in record
    assert "output_verdict" in record


def test_check_output_redaction_raw_content_not_retained(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    argv = _base_argv(policy_path, log_path) + [
        "check", "contact bob@example.com for help", "--stage", "output",
    ]
    code = main(argv)
    assert code == 2  # REWRITE intervenes

    log_text = log_path.read_text(encoding="utf-8")
    assert "bob@example.com" not in log_text

    record = _read_records(log_path)[0]
    assert record["status"] == "ok"
    assert record["output_verdict"]["decision"] == "REWRITE"
    assert "raw_response" not in record


def test_check_output_template_only_rewrite_retains_raw_content(policy_path, tmp_path, capsys):
    log_path = tmp_path / "audit.jsonl"
    raw = "A common diagnosis for this symptom is seasonal allergy."
    argv = _base_argv(policy_path, log_path) + [
        "check", raw, "--stage", "output",
    ]
    code = main(argv)
    assert code == 2  # REWRITE intervenes

    record = _read_records(log_path)[0]
    assert record["status"] == "ok"
    assert record["output_verdict"]["decision"] == "REWRITE"
    assert record["raw_response"] == raw


def test_permission_denied_audit_path_does_not_crash(policy_path, tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    bad_log = blocker / "audit.jsonl"

    argv = _base_argv(policy_path, bad_log) + [
        "process", "what is the capital of Brazil?", "--mock",
    ]
    code = main(argv)
    assert code == 0
    captured = capsys.readouterr()
    assert "[audit] could not initialize audit log" in captured.err
