import json
from pathlib import Path

import pytest

from ethical_agent.demo import DEMO_CASES
from webui_support import RunningServer


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path, engine="rule")
    yield running
    running.close()


def test_demo_runs_all_seven_cases(server):
    status, body, _ = server.post("/api/demo", {"config": {}})
    assert status == 200
    assert len(body["cases"]) == 7
    assert [case["text"] for case in body["cases"]] == DEMO_CASES


def test_demo_never_calls_a_real_model(server):
    # Same guarantee as cmd_demo/the former DemoTab: always MockLLM, so this
    # must succeed even with an unreachable/garbage model configured.
    status, body, _ = server.post("/api/demo", {"config": {"model": "this-does-not-exist:latest"}})
    assert status == 200
    assert len(body["cases"]) == 7
    assert body["note"]


def test_demo_endpoint_tags_all_records_with_demo_source(server):
    # Behavioral replacement for the old gui_app.py source-grep test
    # (test_gui_demo_tags_source): actually run the endpoint and read the
    # audit trail back, rather than asserting a literal 'source="demo"'
    # string exists somewhere in a source file.
    status, _, _ = server.post("/api/demo", {"config": {}})
    assert status == 200

    records = [
        json.loads(line) for line in Path(server.audit_log_path).read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) == 7
    assert all(record.get("source") == "demo" for record in records)
    # And confirmed excluded from the chat history sidebar's real-usage list
    # (archive.py's filter), not just tagged.
    status, history, _ = server.get(f"/api/chat/history?audit_log={server.audit_log_path}")
    assert history["conversations"] == []


def test_demo_produces_expected_mix_of_outcomes(server):
    # Mirrors what the 7 fixed prompts are chosen to demonstrate: some
    # interventions, some not.
    status, body, _ = server.post("/api/demo", {"config": {}})
    assert status == 200
    statuses = [case["status"] for case in body["cases"]]
    assert "denied" in statuses
    assert "ok" in statuses
