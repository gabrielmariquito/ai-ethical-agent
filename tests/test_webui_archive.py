import json

from ethical_agent.webui.archive import (
    _iter_lines_reverse,
    build_readonly_transcript,
    summarize_conversations,
)


def _write(tmp_path, records):
    path = tmp_path / "audit.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")
    return path


def _verdict(decision, stage="input", matches=None):
    return {
        "decision": decision,
        "stage": stage,
        "engine": "rule-based",
        "reason": "",
        "system_error": False,
        "matches": matches or [],
        "suppressed": [],
        "rewritten_content": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _chat_record(conversation_id, turn_index, text, timestamp, **extra):
    record = {
        "conversation_id": conversation_id,
        "turn_index": turn_index,
        "status": "ok",
        "message": f"reply to {text}",
        "input": text,
        "input_verdict": _verdict("ALLOW"),
        "timestamp": timestamp,
    }
    record.update(extra)
    return record


# ------------------------------------------------------- _iter_lines_reverse


def _write_raw(tmp_path, text):
    # write_text()/open("w") on Windows translates "\n" -> os.linesep by
    # default (universal newlines) -- newline="" here writes exactly the
    # bytes in `text`, so these tests control LF vs. CRLF precisely instead
    # of getting whatever the host platform's default happens to be.
    path = tmp_path / "f.txt"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def test_iter_lines_reverse_basic_order(tmp_path):
    path = _write_raw(tmp_path, "a\nb\nc\n")
    assert list(_iter_lines_reverse(path)) == ["c", "b", "a"]


def test_iter_lines_reverse_no_trailing_newline(tmp_path):
    path = _write_raw(tmp_path, "a\nb\nc")
    assert list(_iter_lines_reverse(path)) == ["c", "b", "a"]


def test_iter_lines_reverse_empty_file(tmp_path):
    path = _write_raw(tmp_path, "")
    assert list(_iter_lines_reverse(path)) == []


def test_iter_lines_reverse_across_small_chunk_boundaries(tmp_path):
    path = _write_raw(tmp_path, "aaaa\nbbbb\ncccc\n")
    # chunk_size smaller than any single line forces lines to be
    # reassembled across multiple backward reads.
    assert list(_iter_lines_reverse(path, chunk_size=3)) == ["cccc", "bbbb", "aaaa"]


def test_iter_lines_reverse_skips_blank_lines(tmp_path):
    path = _write_raw(tmp_path, "a\n\nb\n\n\nc\n")
    assert list(_iter_lines_reverse(path)) == ["c", "b", "a"]


def test_iter_lines_reverse_tolerates_crlf(tmp_path):
    # AuditLogger.log() opens the file in default text mode, which
    # translates "\n" to os.linesep -- "\r\n" on Windows -- so a real trail
    # on this platform is CRLF-separated; confirmed directly against
    # AuditLogger.log()'s actual output, not assumed.
    path = _write_raw(tmp_path, "a\r\nb\r\nc\r\n")
    assert list(_iter_lines_reverse(path)) == ["c", "b", "a"]


# ---------------------------------------------------- summarize_conversations


def test_summarize_conversations_excludes_check_records(tmp_path):
    path = _write(tmp_path, [{"status": "ok", "engine": "rule-based", "input": "hi", "input_verdict": _verdict("ALLOW")}])
    result = summarize_conversations(str(path))
    assert result == {"conversations": [], "truncated": False}


def test_summarize_conversations_excludes_demo_records(tmp_path):
    record = _chat_record("c1", 1, "Why is the sky blue?", "2026-01-01T00:00:00+00:00", source="demo")
    path = _write(tmp_path, [record])
    result = summarize_conversations(str(path))
    assert result == {"conversations": [], "truncated": False}


def test_summarize_conversations_missing_file(tmp_path):
    result = summarize_conversations(str(tmp_path / "nope.jsonl"))
    assert result == {"conversations": [], "truncated": False}


def test_summarize_conversations_uses_most_recent_turn_index_as_count(tmp_path):
    records = [
        _chat_record("c1", 1, "first", "2026-01-01T00:00:00+00:00"),
        _chat_record("c1", 2, "second", "2026-01-01T00:00:01+00:00"),
        _chat_record("c1", 3, "third", "2026-01-01T00:00:02+00:00"),
    ]
    path = _write(tmp_path, records)
    result = summarize_conversations(str(path))
    assert len(result["conversations"]) == 1
    entry = result["conversations"][0]
    assert entry["turn_count"] == 3
    assert entry["preview"] == "third"
    assert entry["updated_at"] == "2026-01-01T00:00:02+00:00"
    assert result["truncated"] is False


def test_summarize_conversations_newest_conversation_first(tmp_path):
    records = [
        _chat_record("old", 1, "old one", "2026-01-01T00:00:00+00:00"),
        _chat_record("new", 1, "new one", "2026-01-02T00:00:00+00:00"),
    ]
    path = _write(tmp_path, records)
    result = summarize_conversations(str(path))
    assert [c["conversation_id"] for c in result["conversations"]] == ["new", "old"]


def test_summarize_conversations_respects_limit_and_reports_truncated(tmp_path):
    records = [_chat_record(f"c{i}", 1, f"msg {i}", f"2026-01-01T00:00:{i:02d}+00:00") for i in range(5)]
    path = _write(tmp_path, records)
    result = summarize_conversations(str(path), limit=2)
    assert len(result["conversations"]) == 2
    assert result["truncated"] is True
    # Newest two: c4, c3
    assert [c["conversation_id"] for c in result["conversations"]] == ["c4", "c3"]


def test_summarize_conversations_stops_scanning_without_reading_whole_file(tmp_path):
    # A huge amount of non-matching noise sits BEFORE (earlier in the file
    # than) 3 matching conversations near the end -- the function must not
    # need to read back through all of it to find `limit` conversations.
    # (`truncated` is True here by design: reaching `limit` and reaching the
    # scan cap look the same from the caller's side -- neither proves
    # there's nothing older left. See summarize_conversations' docstring.)
    noise = [{"status": "ok", "engine": "rule-based", "input": "noise", "input_verdict": _verdict("ALLOW")}] * 10_000
    real = [_chat_record(f"c{i}", 1, f"msg {i}", f"2026-01-01T00:00:{i:02d}+00:00") for i in range(3)]
    path = _write(tmp_path, noise + real)
    result = summarize_conversations(str(path), limit=3)
    assert len(result["conversations"]) == 3
    assert result["truncated"] is True


# ------------------------------------------------------ build_readonly_transcript


def test_build_readonly_transcript_unknown_conversation_returns_none(tmp_path):
    path = _write(tmp_path, [])
    assert build_readonly_transcript(str(path), "nope") is None


def test_build_readonly_transcript_orders_turns_oldest_first(tmp_path):
    records = [
        _chat_record("c1", 1, "first", "2026-01-01T00:00:00+00:00"),
        _chat_record("c1", 2, "second", "2026-01-01T00:00:01+00:00"),
        _chat_record("c1", 3, "third", "2026-01-01T00:00:02+00:00"),
    ]
    path = _write(tmp_path, records)
    turns = build_readonly_transcript(str(path), "c1")
    assert [t["user_text"] for t in turns] == ["first", "second", "third"]


def test_build_readonly_transcript_stops_at_turn_one_without_scanning_earlier_history(tmp_path):
    # An unrelated conversation's turns sit before c1's turn 1 in the file;
    # the scan must not need to read past c1's own start.
    other = [_chat_record("other", i, f"other {i}", f"2026-01-01T00:00:{i:02d}+00:00") for i in range(1, 4)]
    mine = [
        _chat_record("c1", 1, "first", "2026-01-01T00:01:00+00:00"),
        _chat_record("c1", 2, "second", "2026-01-01T00:01:01+00:00"),
    ]
    path = _write(tmp_path, other + mine)
    turns = build_readonly_transcript(str(path), "c1")
    assert [t["user_text"] for t in turns] == ["first", "second"]


def test_build_readonly_transcript_response_field_always_none(tmp_path):
    records = [
        {
            "conversation_id": "c1", "turn_index": 1, "status": "ok",
            "message": "You can reach our support team at [REDACTED:R-PRIV-002].",
            "input": "What is the support contact?",
            "input_verdict": _verdict("ALLOW"),
            "output_verdict": _verdict(
                "REWRITE",
                stage="output",
                matches=[
                    {
                        "rule_id": "R-PRIV-002", "principle": "privacy", "deontic": "prohibition",
                        "severity": "medium", "effect": "REWRITE", "rationale": "...", "hard": False,
                        "redacted": True, "evidence": [],
                    }
                ],
            ),
            "llm_provenance": {"kind": "mock_requested"},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
    ]
    path = _write(tmp_path, records)
    turns = build_readonly_transcript(str(path), "c1")
    assert turns[0]["response"] is None
    assert turns[0]["intervention"] == "rewrite"
