"""Listagem, paginação e busca de registro sobre uma trilha real via HTTP
real, com o requisito de que todo limite que a tela se impõe apareça na
resposta em vez de encurtar em silêncio o que o auditor pensa estar vendo: versão longa em `997a6fe^`.
"""
from __future__ import annotations

import json

import pytest

from webui_support import RunningServer

PASSWORD = "senha-de-teste"


def record(event_id, *, kind="web_chat", decision="ALLOW", turn=1, conversation="c1"):
    base = {
        "event_id": event_id,
        "timestamp": f"2026-08-01T10:{int(event_id[-2:]) % 60:02d}:00+00:00",
        "status": "denied" if decision == "DENY" else "ok",
        "engine": "hybrid",
        "config_versions": {"rule-based": {"policy_version": "0.2.1"}},
        "input": f"texto {event_id}",
        "input_verdict": {
            "decision": decision,
            "stage": "input",
            "engine": "hybrid",
            "reason": "motivo",
            "system_error": False,
            "matches": [],
            "suppressed": [],
            "rewritten_content": None,
        },
    }
    if kind == "web_chat":
        base["message"] = "resposta"
        base["conversation_id"] = conversation
        base["turn_index"] = turn
    elif kind == "demo":
        base["message"] = "resposta"
        base["source"] = "demo"
    elif kind == "cli_process":
        base["message"] = "resposta"
    elif kind == "check":
        pass  # no "message" key at all -- that is what makes it a check
    elif kind == "synthetic":
        base["engine"] = "SYNTHETIC-SAMPLE-DATA"
        base.pop("message", None)
    return base


def write_trail(path, records):
    with open(path, "w", encoding="utf-8") as handle:
        for item in records:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path, audit_password=PASSWORD)
    status, _, _ = running.login_as_auditor(PASSWORD)
    assert status == 200
    yield running
    running.close()


def test_default_filter_shows_only_web_conversations(server):
    write_trail(
        server.audit_log_path,
        [
            record("ev01", kind="web_chat"),
            record("ev02", kind="demo"),
            record("ev03", kind="check"),
            record("ev04", kind="cli_process"),
            record("ev05", kind="synthetic"),
        ],
    )
    status, body, _ = server.get("/api/audit/records")
    assert status == 200, body
    assert [r["event_id"] for r in body["records"]] == ["ev01"]
    assert body["kinds"] == ["web_chat"]
    # The cost of the filter is reported, never invisible: a filter whose
    # cost cannot be seen is a filter that misleads about how much trail was
    # actually looked at.
    assert body["scan"]["filtered_out"] == 4
    assert body["scan"]["lines_examined"] == 5


def test_kinds_all_shows_everything(server):
    write_trail(
        server.audit_log_path,
        [
            record("ev01", kind="web_chat"),
            record("ev02", kind="demo"),
            record("ev03", kind="check"),
            record("ev04", kind="cli_process"),
            record("ev05", kind="synthetic"),
        ],
    )
    status, body, _ = server.get("/api/audit/records?kinds=all")
    assert status == 200
    assert len(body["records"]) == 5
    assert {r["kind"] for r in body["records"]} == {
        "web_chat",
        "demo",
        "check",
        "cli_process",
        "synthetic",
    }
    assert body["scan"]["filtered_out"] == 0


def test_records_are_newest_first(server):
    write_trail(server.audit_log_path, [record(f"ev{i:02d}") for i in range(1, 6)])
    status, body, _ = server.get("/api/audit/records")
    assert [r["event_id"] for r in body["records"]] == ["ev05", "ev04", "ev03", "ev02", "ev01"]


def test_deny_and_rewrite_are_marked_with_different_gravity(server):
    write_trail(
        server.audit_log_path,
        [
            record("ev01", decision="ALLOW"),
            record("ev02", decision="DENY"),
            record("ev03", decision="REWRITE"),
        ],
    )
    status, body, _ = server.get("/api/audit/records")
    gravity = {r["event_id"]: r["gravity"] for r in body["records"]}
    # A block and a rewrite must not land in the same visual bucket -- that
    # distinction is what tells an auditor where to start.
    assert gravity == {"ev01": "none", "ev02": "deny", "ev03": "rewrite"}


def test_pagination_cursor_walks_backward_without_repeats_or_gaps(server):
    write_trail(server.audit_log_path, [record(f"ev{i:02d}") for i in range(1, 13)])
    seen = []
    cursor = None
    file_size = None
    for _ in range(10):
        query = "/api/audit/records?limit=5"
        if cursor:
            query += f"&cursor={cursor}&since_size={file_size}"
        status, body, _ = server.get(query)
        assert status == 200, body
        seen.extend(r["event_id"] for r in body["records"])
        cursor = body["next_cursor"]
        file_size = body["file_size"]
        if body["reached_start_of_file"]:
            break
    assert seen == [f"ev{i:02d}" for i in range(12, 0, -1)]
    assert len(seen) == len(set(seen)), "a record was returned on two pages"


def test_scan_budget_is_reported_and_cursor_still_advances_on_a_zero_match_page(
    server, monkeypatch
):
    # Um filtro estreito sobre um trecho longo pode legitimamente não devolver
    # nada, e `next_cursor` tem de avançar até a última linha *examinada*.
    from ethical_agent.webui import audit_view

    monkeypatch.setattr(audit_view, "AUDIT_PAGE_SCAN_LIMIT", 3)
    write_trail(
        server.audit_log_path,
        [record("ev01", kind="web_chat")] + [record(f"ev{i:02d}", kind="demo") for i in range(2, 9)],
    )
    status, body, _ = server.get("/api/audit/records")
    assert status == 200
    assert body["records"] == []
    assert body["scan"]["exhausted_budget"] is True
    assert body["scan"]["budget"] == 3
    assert body["scan"]["filtered_out"] == 3
    assert body["next_cursor"] is not None
    assert body["reached_start_of_file"] is False

    # Continuing from that cursor makes progress rather than repeating.
    status, body2, _ = server.get(
        f"/api/audit/records?cursor={body['next_cursor']}&since_size={body['file_size']}"
    )
    assert status == 200
    assert int(body2["next_cursor"] or 0) < int(body["next_cursor"])


def test_reached_start_of_file_only_set_at_the_real_start(server):
    write_trail(server.audit_log_path, [record(f"ev{i:02d}") for i in range(1, 8)])
    status, body, _ = server.get("/api/audit/records?limit=3")
    assert body["reached_start_of_file"] is False

    status, body, _ = server.get("/api/audit/records?limit=50")
    assert body["reached_start_of_file"] is True
    assert body["next_cursor"] is None


def test_missing_trail_is_an_empty_list_not_an_error(server):
    status, body, _ = server.get("/api/audit/records")
    assert status == 200
    assert body["records"] == []
    assert body["reached_start_of_file"] is True


def test_detail_by_offset_verifies_event_id_and_recovers_from_a_stale_offset(server):
    write_trail(server.audit_log_path, [record(f"ev{i:02d}") for i in range(1, 6)])
    status, page, _ = server.get("/api/audit/records")
    target = page["records"][2]

    status, body, _ = server.get(
        f"/api/audit/records/{target['event_id']}?offset={target['offset']}"
    )
    assert status == 200
    assert body["event_id"] == target["event_id"]

    # A stale offset (pointing at a different record) must not silently
    # return the wrong one -- the id is verified, then the scan corrects it.
    status, body, _ = server.get(f"/api/audit/records/{target['event_id']}?offset=0")
    assert status == 200
    assert body["event_id"] == target["event_id"]
    assert body["offset"] == target["offset"]


def test_detail_of_unknown_event_id_is_404(server):
    write_trail(server.audit_log_path, [record("ev01")])
    status, body, _ = server.get("/api/audit/records/nao-existe")
    assert status == 404
    assert body["error"] == "unknown_record"


def test_detail_of_corrupt_line_is_404_not_500(server):
    # A process killed mid-write leaves a torn line. The screen must survive
    # meeting it.
    with open(server.audit_log_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record("ev01")) + "\n")
        handle.write('{"event_id": "ev02", "truncad\n')
    status, body, _ = server.get("/api/audit/records/ev02?offset=0")
    assert status == 404, body
    assert body["error"] in ("unknown_record", "record_not_found_within_scan_budget")


def test_corrupt_lines_are_counted_in_the_list_not_silently_skipped(server):
    with open(server.audit_log_path, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(record("ev01")) + "\n")
        handle.write("isto nao e json\n")
    status, body, _ = server.get("/api/audit/records")
    assert status == 200
    assert [r["event_id"] for r in body["records"]] == ["ev01"]
    assert body["scan"]["unreadable_lines"] == 1


def test_truncated_file_returns_409_stale_cursor(server):
    write_trail(server.audit_log_path, [record(f"ev{i:02d}") for i in range(1, 13)])
    status, page, _ = server.get("/api/audit/records?limit=5")
    assert status == 200
    big = page["file_size"]

    write_trail(server.audit_log_path, [record("ev01")])
    status, body, _ = server.get(
        f"/api/audit/records?cursor={page['next_cursor']}&since_size={big}"
    )
    # Byte offsets from the previous page mean nothing once the file shrank.
    # Refusing beats renumbering silently: an audit tool that papers over its
    # subject being rewritten is the wrong tool.
    assert status == 409, body
    assert body["error"] == "stale_cursor"


def test_invalid_cursor_is_400(server):
    write_trail(server.audit_log_path, [record("ev01")])
    status, body, _ = server.get("/api/audit/records?cursor=abc")
    assert status == 400
    assert body["error"] == "invalid_cursor"


def test_conversation_endpoint_returns_turns_in_order_and_marks_completeness(server):
    write_trail(
        server.audit_log_path,
        [
            record("ev01", turn=1, conversation="conv-a"),
            record("ev02", turn=1, conversation="conv-b"),
            record("ev03", turn=2, conversation="conv-a"),
            record("ev04", turn=3, conversation="conv-a", decision="DENY"),
        ],
    )
    status, body, _ = server.get("/api/audit/conversations/conv-a")
    assert status == 200, body
    # Oldest first: a decision is only judgeable after what led to it.
    assert [t["turn_index"] for t in body["turns"]] == [1, 2, 3]
    assert [t["event_id"] for t in body["turns"]] == ["ev01", "ev03", "ev04"]
    assert body["complete"] is True
    assert body["turn_index_duplicates"] == []


def test_conversation_marks_itself_incomplete_when_turn_one_was_not_reached(
    server, monkeypatch
):
    from ethical_agent.webui import audit_view

    monkeypatch.setattr(audit_view, "AUDIT_PAGE_SCAN_LIMIT", 2)
    write_trail(
        server.audit_log_path,
        [record(f"ev{i:02d}", turn=i, conversation="conv-a") for i in range(1, 6)],
    )
    status, body, _ = server.get("/api/audit/conversations/conv-a")
    assert status == 200
    # Saying "this may be partial" beats presenting a truncated sequence as
    # if it were the whole conversation.
    assert body["complete"] is False


def test_conversation_reports_duplicate_turn_indices(server):
    write_trail(
        server.audit_log_path,
        [
            record("ev01", turn=1, conversation="conv-a"),
            record("ev02", turn=2, conversation="conv-a"),
            record("ev03", turn=2, conversation="conv-a"),
        ],
    )
    status, body, _ = server.get("/api/audit/conversations/conv-a")
    assert status == 200
    # Reported so the screen can warn instead of presenting an order it
    # cannot actually vouch for.
    assert body["turn_index_duplicates"] == [2]


def test_conversation_scan_stops_at_the_first_turn_one_it_meets(server):
    # Documenta uma limitação conhecida e delimitada: a varredura para em
    # `turn_index == 1`, então um segundo registro de turno 1 mais antigo não é
    # coletado: versão longa em `997a6fe^`.
    write_trail(
        server.audit_log_path,
        [
            record("ev01", turn=1, conversation="conv-a"),
            record("ev02", turn=1, conversation="conv-a"),
        ],
    )
    status, body, _ = server.get("/api/audit/conversations/conv-a")
    assert status == 200
    assert [t["event_id"] for t in body["turns"]] == ["ev02"]
    assert body["turn_index_duplicates"] == []


def test_unknown_conversation_is_404(server):
    write_trail(server.audit_log_path, [record("ev01", conversation="conv-a")])
    status, body, _ = server.get("/api/audit/conversations/conv-zzz")
    assert status == 404
    assert body["error"] == "unknown_conversation"


def test_audit_reader_ignores_any_client_supplied_audit_log_path(server, tmp_path):
    # Aceitar um `audit_log` por requisição aqui daria ao auditor um oráculo de
    # existência e conteúdo de qualquer arquivo que o processo consiga ler.
    write_trail(server.audit_log_path, [record("ev01")])
    other = tmp_path / "outra.jsonl"
    write_trail(other, [record("ev99")])

    for query in (
        f"?audit_log={other}",
        f"?path={other}",
        f"?audit_log_path={other}",
    ):
        status, body, _ = server.get(f"/api/audit/records{query}")
        assert status == 200
        assert [r["event_id"] for r in body["records"]] == ["ev01"], query


def test_record_rows_carry_the_rule_ids_but_layer1_does_not(server):
    trail_record = record("ev01", decision="DENY")
    trail_record["input_verdict"]["matches"] = [
        {
            "rule_id": "R-INJ-001",
            "principle": "security",
            "deontic": "prohibition",
            "severity": "high",
            "effect": "DENY",
            "rationale": "porque sim",
            "hard": False,
            "redacted": False,
            "evidence": [{"description": "keyword", "matched_text": "x", "span": [0, 1]}],
        }
    ]
    write_trail(server.audit_log_path, [trail_record])

    status, page, _ = server.get("/api/audit/records")
    assert page["records"][0]["rule_ids"] == ["R-INJ-001"]

    status, detail, _ = server.get("/api/audit/records/ev01")
    # Layer 1 must stay readable without vocabulary; the rule identifier
    # belongs to layer 2.
    assert "R-INJ-001" not in json.dumps(detail["layer1"])
    assert "R-INJ-001" in json.dumps(detail["layer2"])
