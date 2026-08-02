"""Instrumentation of the auditor's session, and the change-request seam.

The invariant most of these defend: the agent's trail is the object of study,
so the auditor's own behaviour must never end up inside it. That is the same
reasoning that gave demo runs source="demo", taken one step further -- a
separate concern gets a separate file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ethical_agent.webui.auditor_log import ALL_EVENT_TYPES, EVENT_TYPES, sanitize_payload
from ethical_agent.webui.server import AuditLogCollisionError, make_server
from webui_support import RunningServer, make_initial_config

PASSWORD = "senha-de-teste"


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path, audit_password=PASSWORD)
    status, _, _ = running.login_as_auditor(PASSWORD)
    assert status == 200
    yield running
    running.close()


def read_jsonl(path):
    file = Path(path)
    if not file.exists():
        return []
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_telemetry_events_land_in_the_auditor_log_not_in_audit_jsonl(server):
    status, body, _ = server.post(
        "/api/audit/telemetry",
        {
            "events": [
                {"seq": 1, "type": "record_opened", "client_ts": "2026-08-01T10:00:00Z",
                 "payload": {"record_event_id": "ev01", "revisit": False}},
                {"seq": 2, "type": "record_closed", "client_ts": "2026-08-01T10:00:09Z",
                 "payload": {"record_event_id": "ev01", "dwell_ms": 9000,
                             "visible_dwell_ms": 8200, "layers_expanded_in_order": ["layer2"]}},
            ]
        },
    )
    assert status == 202, body
    assert body["accepted"] == 2

    events = read_jsonl(server.auditor_session_log)
    types = [e["type"] for e in events]
    assert "record_opened" in types and "record_closed" in types
    closed = next(e for e in events if e["type"] == "record_closed")
    assert closed["dwell_ms"] == 9000
    assert closed["visible_dwell_ms"] == 8200
    assert closed["layers_expanded_in_order"] == ["layer2"]

    # The agent's trail must be untouched by any of this.
    assert read_jsonl(server.audit_log_path) == []


def test_every_event_carries_the_session_id_and_no_personal_identifier(server):
    status, session, _ = server.get("/api/audit/session")
    assert status == 200
    server.post(
        "/api/audit/telemetry",
        {"events": [{"seq": 1, "type": "record_opened", "payload": {"record_event_id": "e"}}]},
    )
    events = read_jsonl(server.auditor_session_log)
    opened = next(e for e in events if e["type"] == "record_opened")
    assert opened["session_id"] == session["session_id"]
    # An anonymous session id is the only identifier; the link between a
    # session and a participant, if any, stays outside the system.
    flat = json.dumps(events)
    for forbidden in ("User-Agent", "Mozilla", "127.0.0.1", "remote_addr", "ip"):
        assert forbidden not in flat


def test_telemetry_payload_is_an_allow_list(server):
    server.post(
        "/api/audit/telemetry",
        {
            "events": [
                {
                    "seq": 1,
                    "type": "record_opened",
                    "payload": {"record_event_id": "ev01", "nome_do_participante": "Fulano"},
                }
            ]
        },
    )
    events = read_jsonl(server.auditor_session_log)
    opened = next(e for e in events if e["type"] == "record_opened")
    assert opened["record_event_id"] == "ev01"
    # An allow-list rather than a deny-list is what makes "no personal
    # identification" checkable instead of merely intended.
    assert "nome_do_participante" not in opened
    assert "Fulano" not in json.dumps(events)


def test_unknown_event_types_are_dropped(server):
    # The screen shows the auditor a catalog of what can be written; an
    # event type outside it would be something they were never told about.
    status, body, _ = server.post(
        "/api/audit/telemetry",
        {"events": [{"seq": 1, "type": "tipo_inventado", "payload": {}}]},
    )
    assert status == 202
    assert body["accepted"] == 0
    assert body["dropped"] == 1
    assert read_jsonl(server.auditor_session_log) == [
        e for e in read_jsonl(server.auditor_session_log) if e["type"] != "tipo_inventado"
    ]


def test_telemetry_echoes_last_seq_so_the_client_can_detect_gaps(server):
    status, body, _ = server.post(
        "/api/audit/telemetry",
        {"events": [{"seq": 7, "type": "record_opened", "payload": {}},
                    {"seq": 9, "type": "record_closed", "payload": {}}]},
    )
    assert status == 202
    # sendBeacon cannot read a response, so an echoed sequence number is the
    # only way a batch lost at page-hide becomes a visible gap rather than a
    # silently shorter file.
    assert body["last_seq"] == 9


def test_login_and_failure_are_recorded_by_the_server_itself(tmp_path):
    running = RunningServer(tmp_path, audit_password=PASSWORD)
    try:
        running.login_as_auditor("errada")
        running.login_as_auditor(PASSWORD)
        events = read_jsonl(running.auditor_session_log)
        types = [e["type"] for e in events]
        assert "auth_login_failed" in types
        assert "auth_login_succeeded" in types
        failed = next(e for e in events if e["type"] == "auth_login_failed")
        # There is no session yet when a login fails, and inventing one would
        # tie an unrelated attempt to somebody's reading session.
        assert failed["session_id"] is None
    finally:
        running.close()


def test_session_events_endpoint_returns_only_this_session(server, tmp_path):
    server.post(
        "/api/audit/telemetry",
        {"events": [{"seq": 1, "type": "record_opened", "payload": {"record_event_id": "meu"}}]},
    )
    # An event from a different session, written straight into the file.
    with open(server.auditor_session_log, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"session_id": "outra-sessao", "type": "record_opened"}) + "\n")

    status, body, _ = server.get("/api/audit/session/events")
    assert status == 200
    assert all(e["session_id"] != "outra-sessao" for e in body["events"])
    assert any(e.get("record_event_id") == "meu" for e in body["events"])


def test_reading_your_own_events_is_itself_recorded(server):
    status, _, _ = server.get("/api/audit/session/events")
    assert status == 200
    events = read_jsonl(server.auditor_session_log)
    # A transparency screen with one quiet exception in it is not one, so the
    # meta-read is logged too -- and the screen says so.
    assert any(e["type"] == "own_session_events_viewed" for e in events)


def test_session_payload_discloses_the_event_catalog_and_both_paths(server):
    status, body, _ = server.get("/api/audit/session")
    assert status == 200
    served = {item["type"] for item in body["event_types"]}
    assert served == set(ALL_EVENT_TYPES)
    assert all(item["description"] for item in body["event_types"])
    # The disclosure the auditor reads is server truth, not a claim the page
    # makes about itself.
    assert body["auditor_log_path"].endswith("auditor_sessions.jsonl")
    assert body["audit_log_path"] == server.audit_log_path


def test_event_catalog_covers_every_accepted_type():
    # If a type can be written it must be describable to the auditor;
    # a gap here would be an event nobody was told about.
    from ethical_agent.webui.auditor_log import EVENT_TYPE_DESCRIPTIONS

    for name in ALL_EVENT_TYPES:
        assert EVENT_TYPE_DESCRIPTIONS.get(name), name
    assert set(EVENT_TYPES).issubset(set(ALL_EVENT_TYPES))


def test_sanitize_payload_truncates_long_strings_and_lists():
    clean = sanitize_payload({"record_event_id": "x" * 500, "layers_expanded_in_order": ["a"] * 200})
    assert len(clean["record_event_id"]) == 200
    assert len(clean["layers_expanded_in_order"]) == 50


def test_server_refuses_to_start_when_auditor_log_equals_audit_log(tmp_path):
    config = make_initial_config(tmp_path)
    # Mixing the auditor's behaviour into the record of what the agent
    # decided would corrupt the object of study, and no later grep undoes
    # it. A hard invariant, not a convention.
    with pytest.raises(AuditLogCollisionError):
        make_server(
            0, config, audit_password=PASSWORD, auditor_session_log=config["audit_log"]
        )
    with pytest.raises(AuditLogCollisionError):
        make_server(
            0, config, audit_password=PASSWORD, change_requests_log=config["audit_log"]
        )


def test_chat_mode_never_creates_the_auditor_files(tmp_path):
    running = RunningServer(tmp_path)
    try:
        running.get("/api/choices")
        assert not Path(running.auditor_session_log).exists()
        assert not Path(running.change_requests_log).exists()
    finally:
        running.close()


# ------------------------------------------------- the policy-editing seam


def test_change_request_writes_to_its_own_file_and_never_mutates_any_policy(server):
    policy_path = Path(server.initial_config["policy"])
    before = policy_path.read_bytes()

    status, body, _ = server.post(
        "/api/audit/change-requests",
        {"record_event_id": "ev01", "rule_id": "R-INJ-001", "note": "severo demais"},
    )
    assert status == 201, body
    assert body["applied"] is False
    assert "não altera" in body["message"] or "próxima etapa" in body["message"]

    # Records intent; changes nothing. If this ever starts editing policy it
    # will do so in the next change, deliberately and with versioning.
    assert policy_path.read_bytes() == before

    requests = read_jsonl(server.change_requests_log)
    assert len(requests) == 1
    assert requests[0]["record_event_id"] == "ev01"
    assert requests[0]["rule_id"] == "R-INJ-001"
    assert requests[0]["note"] == "severo demais"
    assert requests[0]["applied"] is False

    # The behavioural log gets only a pointer -- the auditor's reasoning is
    # a finding, not telemetry, and the next change reads it without having
    # to parse dwell times.
    events = read_jsonl(server.auditor_session_log)
    submitted = next(e for e in events if e["type"] == "change_request_submitted")
    assert submitted["has_note"] is True
    assert "severo demais" not in json.dumps(events)


def test_change_request_accepts_an_empty_note(server):
    # Optional in earnest: forcing a justification produces justifications
    # about being asked for one, which would contaminate the data.
    status, body, _ = server.post(
        "/api/audit/change-requests", {"record_event_id": "ev01", "rule_id": "R-1"}
    )
    assert status == 201, body
    requests = read_jsonl(server.change_requests_log)
    assert requests[0]["note"] == ""
    assert requests[0]["note_absent"] is True

    status, _, _ = server.post(
        "/api/audit/change-requests",
        {"record_event_id": "ev02", "rule_id": "R-1", "note": "   "},
    )
    assert status == 201
    events = read_jsonl(server.auditor_session_log)
    assert all(e.get("has_note") is not True for e in events if e["type"] == "change_request_submitted")


def test_change_request_requires_a_record_to_anchor_to(server):
    # The anchor is the whole point of the seam: a marking that is not
    # attached to a specific record cannot be acted on later.
    status, body, _ = server.post("/api/audit/change-requests", {"rule_id": "R-1"})
    assert status == 400
    assert body["error"] == "invalid_request"


def test_change_requests_can_be_listed_back_for_one_record(server):
    server.post("/api/audit/change-requests", {"record_event_id": "ev01", "rule_id": "R-1"})
    server.post("/api/audit/change-requests", {"record_event_id": "ev02", "rule_id": "R-2"})

    status, body, _ = server.get("/api/audit/change-requests?record=ev01")
    assert status == 200
    assert [r["record_event_id"] for r in body["change_requests"]] == ["ev01"]

    status, body, _ = server.get("/api/audit/change-requests")
    assert len(body["change_requests"]) == 2
