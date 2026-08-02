from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional

from ethical_agent.llm import describe_llm_provenance

from .dto import classify_intervention

# Reads logs/audit.jsonl to reconstruct the left-sidebar's conversation list
# and a past conversation's read-only transcript. This is deliberately the
# *only* source of conversation history that survives a server restart --
# ConversationStore (state.py) is in-memory only, on purpose (see its
# docstring). Nothing here writes anything; it only ever reads the trail
# that GuardedAgent._finish() already writes for every process() turn.
#
# The trail is append-only and can run to months of accumulated CLI and web
# activity, so both functions below scan it *backward* from the end (newest
# first) and stop as soon as they have what they need, instead of loading
# and grouping the whole file on every sidebar refresh:
#   - summarize_conversations stops once it has LIST_LIMIT distinct
#     conversations. It doesn't need every turn of each one -- the most
#     recent record for a conversation already carries everything a list
#     entry needs (turn_index *is* the running turn count, no need to also
#     count each line; its own timestamp is "updated_at"; its own
#     input/message is the preview).
#   - build_readonly_transcript (opening one past conversation) stops once
#     it has seen that conversation's turn_index == 1, i.e. reached its
#     start -- it never needs to look further back than that one
#     conversation's own turns.
# Both are additionally capped at MAX_SCAN_LINES so a huge trail with few or
# no matching records near the tail still returns promptly instead of
# degrading to a full-file scan.

LIST_LIMIT = 50
MAX_SCAN_LINES = 20_000


def _iter_lines_reverse(path: Path, chunk_size: int = 65536) -> Iterator[str]:
    """Yields lines from the end of the file backward (most recent line
    first), reading in fixed-size chunks rather than loading the whole file.
    Blank lines are skipped; a trailing "\\r" is stripped from every line so
    a CRLF-written trail (AuditLogger.log() opens the file in default text
    mode, which translates "\\n" to os.linesep -- "\\r\\n" on Windows) parses
    the same as an LF-only one.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        position = handle.tell()
        trailing = b""
        while position > 0:
            read_size = min(chunk_size, position)
            position -= read_size
            handle.seek(position)
            data = handle.read(read_size) + trailing
            parts = data.split(b"\n")
            trailing = parts[0]
            for part in reversed(parts[1:]):
                stripped = part.rstrip(b"\r")
                if stripped:
                    yield stripped.decode("utf-8", errors="replace")
        stripped = trailing.rstrip(b"\r")
        if stripped:
            yield stripped.decode("utf-8", errors="replace")


def _is_web_chat_turn(record: dict) -> bool:
    """True only for turns that went through the web chat's
    GuardedAgent.process(..., conversation_id=...). check records never call
    process() at all (no conversation_id key, ever); demo and the CLI's
    single-turn `process` call process() without a conversation_id either --
    so presence of the key alone already isolates web-chat turns. The
    source != "demo" check is a second, independent guard in case that ever
    changes, not the primary filter.
    """
    return "conversation_id" in record and record.get("source") != "demo"


def _parse_line(line: str) -> Optional[dict]:
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        # Tolerate a malformed line (e.g. a process killed mid-write)
        # instead of failing the whole listing.
        return None
    return record if isinstance(record, dict) else None


def summarize_conversations(audit_log_path: str, limit: int = LIST_LIMIT) -> dict:
    """Returns {"conversations": [...], "truncated": bool} -- newest first,
    at most `limit` entries. `truncated` is True when the scan stopped
    because it hit `limit` (there may be older conversations not shown) or
    MAX_SCAN_LINES (the trail is large enough that the sidebar can't afford
    to keep looking for more).
    """
    path = Path(audit_log_path)
    if not path.exists():
        return {"conversations": [], "truncated": False}

    seen: Dict[str, dict] = {}
    scanned = 0
    hit_scan_cap = False
    for line in _iter_lines_reverse(path):
        if len(seen) >= limit:
            break
        scanned += 1
        if scanned > MAX_SCAN_LINES:
            hit_scan_cap = True
            break
        record = _parse_line(line)
        if record is None or not _is_web_chat_turn(record):
            continue
        conversation_id = record["conversation_id"]
        if conversation_id in seen:
            continue  # already captured this conversation's most recent turn
        preview_source = record.get("input") or record.get("message") or ""
        seen[conversation_id] = {
            "conversation_id": conversation_id,
            "turn_count": record.get("turn_index") or 1,
            "updated_at": record.get("timestamp"),
            "preview": preview_source[:80],
        }

    # Insertion order already matches the backward scan, i.e. newest first.
    # `truncated` can be a false positive in the rare case where the trail
    # has *exactly* `limit` conversations total (nothing was actually left
    # out) -- distinguishing that from "there's more" would cost an extra
    # lookahead read for a purely cosmetic difference, not worth it here.
    truncated = hit_scan_cap or len(seen) >= limit
    return {"conversations": list(seen.values()), "truncated": truncated}


def build_readonly_transcript(audit_log_path: str, conversation_id: str) -> Optional[List[dict]]:
    """Returns None if the conversation isn't in the trail at all. Each turn
    in the returned list has the same shape dto.turn_result_to_dict() sends
    for a live turn (message, input_verdict, output_verdict, intervention,
    llm_provenance_text, ...) so the frontend can render both with the same
    code -- except "response": archived turns never carry it. The audit
    record has no field equivalent to AgentResult.response (the file only
    ever has message / conditionally raw_response, per
    build_check_audit_record's redaction rule); reusing raw_response under
    the "response" key here would defeat the whole reason that key is
    conditional in the first place.
    """
    path = Path(audit_log_path)
    if not path.exists():
        return None

    matched: List[dict] = []
    scanned = 0
    for line in _iter_lines_reverse(path):
        scanned += 1
        if scanned > MAX_SCAN_LINES:
            break
        record = _parse_line(line)
        if record is None or not _is_web_chat_turn(record):
            continue
        if record.get("conversation_id") != conversation_id:
            continue
        matched.append(record)
        if record.get("turn_index") == 1:
            break  # reached this conversation's first turn; nothing earlier to find

    if not matched:
        return None
    matched.reverse()  # was newest-first from the backward scan; render oldest-first

    turns = []
    for record in matched:
        input_verdict = record.get("input_verdict")
        output_verdict = record.get("output_verdict")
        llm_provenance = record.get("llm_provenance")
        intervention = classify_intervention(
            (input_verdict or {}).get("decision", "ALLOW"),
            (output_verdict or {}).get("decision") if output_verdict else None,
        )
        turns.append(
            {
                "turn_index": record.get("turn_index"),
                "user_text": record.get("input", ""),
                "status": record.get("status"),
                "message": record.get("message", ""),
                "response": None,
                "llm_provenance": llm_provenance,
                "llm_provenance_text": describe_llm_provenance(llm_provenance) if llm_provenance else None,
                "input_verdict": input_verdict,
                "output_verdict": output_verdict,
                "intervention": intervention,
                "system_error": record.get("status") == "system_error",
            }
        )
    return turns
