from __future__ import annotations

import uuid
from pathlib import Path
from typing import List, Optional

from . import audit_view, routing
from .archive import _parse_line, iter_records_reverse
from .auditor_log import EVENT_TYPES, event_type_catalog, sanitize_payload
from .auth import SESSION_TTL_SECONDS
from .errors import ApiError, bad_request

# The audit screen's HTTP surface. Every route below declares realm="audit"
# and (except login) requires_session=True; both are enforced centrally in
# routing.match / httphandler._authorize, so nothing in this file re-checks
# them. With no password configured, none of these paths exist at all -- for
# any method -- which is the whole access separation.
#
# This module reads the trail and presents it. It never recomputes a verdict
# and never re-evaluates content: every decision shown here was made by
# ethical_agent/ when the record was written.

AUDIT_SESSION_COOKIE = "ea_audit_session"


def _audit_log_path(state) -> Path:
    """Always the trail the server was started with -- never a path from the
    request. The chat handlers do accept a per-request audit_log because the
    config panel can point them somewhere else; doing the same here would
    hand an authenticated auditor a file-existence-and-contents oracle for
    anything the process can read. The screen displays this path, read-only,
    so the auditor knows exactly which trail they are looking at."""
    return Path(state.initial_config.get("audit_log") or "logs/audit.jsonl")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_event(state, session_id: Optional[str], event_type: str, payload: dict) -> None:
    logger = state.auditor_logger
    if logger is None:
        return
    logger.log({"session_id": session_id, "type": event_type, **payload})


# ---------------------------------------------------------------------------
# session
# ---------------------------------------------------------------------------


@routing.route("POST", "/api/audit/login", realm="audit")
def post_login(state, params, body):
    auth = state.audit_auth
    remaining = auth.lockout_remaining()
    if remaining > 0:
        _record_event(state, None, "auth_locked_out", {"retry_after_seconds": round(remaining)})
        raise ApiError(
            429,
            "too_many_attempts",
            f"muitas tentativas; tente novamente em {round(remaining)}s",
        )

    password = body.get("password")
    if not isinstance(password, str):
        raise bad_request("invalid_request", "campo 'password' ausente")

    if not auth.verify(password):
        lockout = auth.register_failure()
        _record_event(state, None, "auth_login_failed", {})
        if lockout > 0:
            raise ApiError(
                429,
                "too_many_attempts",
                f"muitas tentativas; tente novamente em {round(lockout)}s",
            )
        raise ApiError(401, "invalid_password", "senha incorreta")

    auth.register_success()
    session = auth.start_session()
    _record_event(
        state,
        session.session_id,
        "auth_login_succeeded",
        {"audit_log_path": str(_audit_log_path(state))},
    )
    cookie = (
        f"{AUDIT_SESSION_COOKIE}={session.token}; Path=/; HttpOnly; "
        f"SameSite=Strict; Max-Age={SESSION_TTL_SECONDS}"
    )
    # No Secure attribute, deliberately: this server is plain HTTP on
    # 127.0.0.1, and a Secure cookie would simply never be sent back.
    return 200, _session_payload(state, session.session_id), [("Set-Cookie", cookie)]


@routing.route("POST", "/api/audit/logout", realm="audit", requires_session=True)
def post_logout(state, params, body):
    state.audit_auth.revoke(params.get("_session_token"))
    expired = f"{AUDIT_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
    return 200, {"ok": True}, [("Set-Cookie", expired)]


@routing.route("GET", "/api/audit/session", realm="audit", requires_session=True)
def get_session(state, params, body):
    return _session_payload(state, params["_session_id"])


def _session_payload(state, session_id: str) -> dict:
    logger = state.auditor_logger
    return {
        "session_id": session_id,
        "expires_in_seconds": SESSION_TTL_SECONDS,
        "audit_log_path": str(_audit_log_path(state)),
        "auditor_log_path": str(logger.path) if logger is not None else None,
        "auditor_log_warning": logger.warning if logger is not None else None,
        "change_requests_log_path": (
            str(state.change_request_logger.path)
            if state.change_request_logger is not None
            else None
        ),
        # Served from the server's own catalog so the disclosure the auditor
        # reads is what the server can actually write, not a promise the page
        # makes about itself.
        "event_types": event_type_catalog(),
        "default_kinds": list(audit_view.DEFAULT_KINDS),
        "available_kinds": list(audit_view.RECORD_KINDS),
    }


@routing.route("GET", "/api/audit/session/events", realm="audit", requires_session=True)
def get_session_events(state, params, body):
    """Lets the auditor read back their own instrumentation. Reading it is
    itself recorded, and the screen says so -- anything else would be a
    transparency screen with a quiet exception in it."""
    session_id = params["_session_id"]
    limit = _int_param(params, "limit", default=100, minimum=1, maximum=500)
    logger = state.auditor_logger
    events: List[dict] = []
    if logger is not None and Path(logger.path).exists():
        for _offset, record in iter_records_reverse(Path(logger.path)):
            if record is None:
                continue
            if record.get("session_id") != session_id:
                continue
            events.append(record)
            if len(events) >= limit:
                break
    events.reverse()
    _record_event(state, session_id, "own_session_events_viewed", {"limit": limit})
    return {"events": events, "count": len(events)}


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------


@routing.route("GET", "/api/audit/records", realm="audit", requires_session=True)
def get_records(state, params, body):
    path = _audit_log_path(state)
    limit = _int_param(
        params,
        "limit",
        default=audit_view.DEFAULT_PAGE_LIMIT,
        minimum=1,
        maximum=audit_view.MAX_PAGE_LIMIT,
    )
    kinds = audit_view.parse_kinds(params.get("kinds"))
    cursor = _cursor_param(params)

    if not path.exists():
        return {
            "records": [],
            "next_cursor": None,
            "reached_start_of_file": True,
            "file_size": 0,
            "scan": {
                "lines_examined": 0,
                "budget": audit_view.AUDIT_PAGE_SCAN_LIMIT,
                "exhausted_budget": False,
                "filtered_out": 0,
                "unreadable_lines": 0,
            },
            "kinds": kinds,
            "available_kinds": list(audit_view.RECORD_KINDS),
        }

    file_size = path.stat().st_size
    since_size = _int_param(params, "since_size", default=None, minimum=0, maximum=None)
    if since_size is not None and file_size < since_size:
        # The trail shrank under us, so byte offsets from the previous page
        # mean nothing now. Refusing beats silently renumbering: an audit
        # tool that papers over its subject being rewritten is the wrong
        # tool. The screen restarts from the top and says why.
        raise ApiError(
            409,
            "stale_cursor",
            "a trilha encolheu desde a página anterior (de "
            f"{since_size} para {file_size} bytes); recomeçando do topo",
        )

    records = []
    examined = 0
    filtered_out = 0
    unreadable = 0
    last_offset: Optional[int] = None
    reached_start = True
    budget = audit_view.AUDIT_PAGE_SCAN_LIMIT

    for offset, record in iter_records_reverse(path, end_offset=cursor):
        if len(records) >= limit:
            reached_start = False
            break
        if examined >= budget:
            reached_start = False
            break
        examined += 1
        last_offset = offset
        if record is None:
            unreadable += 1
            filtered_out += 1
            continue
        kind = audit_view.classify_record_kind(record)
        if kinds is not None and kind not in kinds:
            filtered_out += 1
            continue
        records.append(audit_view.summarize_record(record, offset))

    # next_cursor always advances to the last line *examined*, not the last
    # one matched -- otherwise a page that filtered everything out would
    # hand back the cursor it was given and "load more" would spin forever
    # on a narrow filter over a long trail.
    next_cursor = None if reached_start or last_offset is None else str(last_offset)

    return {
        "records": records,
        "next_cursor": next_cursor,
        "reached_start_of_file": reached_start,
        "file_size": file_size,
        "scan": {
            "lines_examined": examined,
            "budget": budget,
            "exhausted_budget": examined >= budget,
            "filtered_out": filtered_out,
            "unreadable_lines": unreadable,
        },
        "kinds": kinds,
        "available_kinds": list(audit_view.RECORD_KINDS),
    }


@routing.route("GET", "/api/audit/records/{event_id}", realm="audit", requires_session=True)
def get_record(state, params, body):
    path = _audit_log_path(state)
    event_id = params["event_id"]
    if not path.exists():
        raise ApiError(404, "unknown_record", f"registro {event_id} não encontrado")

    offset = _int_param(params, "offset", default=None, minimum=0, maximum=None)

    # Fast path: the list already told us where this record starts, so read
    # that one line instead of scanning. The event_id is verified rather than
    # trusted -- an offset from a stale page must not silently return the
    # wrong record.
    if offset is not None:
        record = _read_record_at(path, offset)
        if record is not None and record.get("event_id") == event_id:
            return audit_view.detail_from_record(record, offset)

    for scanned, (line_offset, record) in enumerate(iter_records_reverse(path), start=1):
        if scanned > audit_view.AUDIT_PAGE_SCAN_LIMIT:
            # "I could not find it within my budget" and "it does not exist"
            # are different claims, and a tool for auditors must not merge
            # them into one comfortable answer.
            raise ApiError(
                404,
                "record_not_found_within_scan_budget",
                f"registro {event_id} não encontrado nas últimas "
                f"{audit_view.AUDIT_PAGE_SCAN_LIMIT} linhas da trilha",
            )
        if record is not None and record.get("event_id") == event_id:
            return audit_view.detail_from_record(record, line_offset)

    raise ApiError(404, "unknown_record", f"registro {event_id} não encontrado")


def _read_record_at(path: Path, offset: int) -> Optional[dict]:
    try:
        with path.open("rb") as handle:
            handle.seek(offset)
            raw = handle.readline()
    except OSError:
        return None
    if not raw:
        return None
    return _parse_line(raw.rstrip(b"\r\n").decode("utf-8", errors="replace"))


@routing.route(
    "GET", "/api/audit/conversations/{conversation_id}", realm="audit", requires_session=True
)
def get_conversation(state, params, body):
    """A decision is only judgeable in context, so records sharing a
    conversation_id have to be readable in sequence rather than as loose
    rows."""
    path = _audit_log_path(state)
    conversation_id = params["conversation_id"]
    if not path.exists():
        raise ApiError(404, "unknown_conversation", f"conversa {conversation_id} não encontrada")

    matched = []
    scanned = 0
    complete = False
    for offset, record in iter_records_reverse(path):
        scanned += 1
        if scanned > audit_view.AUDIT_PAGE_SCAN_LIMIT:
            break
        if record is None or record.get("conversation_id") != conversation_id:
            continue
        matched.append((offset, record))
        if record.get("turn_index") == 1:
            # Reached this conversation's first turn; nothing earlier to
            # find. Same early stop archive.build_readonly_transcript uses,
            # and what keeps this bounded on a months-long trail.
            #
            # Known limitation, stated rather than hidden: if the trail
            # somehow holds *two* turn_index == 1 records for one
            # conversation, the scan stops at the newer one and the older is
            # not collected, so turn_index_duplicates cannot report a
            # duplicate first turn (it does report duplicates at any later
            # turn). Detecting that would mean scanning past the start of
            # every conversation on the chance of a duplicate that
            # uuid4-keyed conversation ids make vanishingly unlikely.
            complete = True
            break

    if not matched:
        raise ApiError(404, "unknown_conversation", f"conversa {conversation_id} não encontrada")

    turns = [audit_view.summarize_record(record, offset) for offset, record in matched]
    turns.sort(key=lambda t: ((t.get("turn_index") or 0), t.get("timestamp") or ""))

    seen = {}
    duplicates = []
    for turn in turns:
        index = turn.get("turn_index")
        if index in seen:
            duplicates.append(index)
        seen[index] = True

    return {
        "conversation_id": conversation_id,
        "turns": turns,
        "complete": complete,
        "turn_index_duplicates": duplicates,
    }


# ---------------------------------------------------------------------------
# instrumentation
# ---------------------------------------------------------------------------


@routing.route("POST", "/api/audit/telemetry", realm="audit", requires_session=True)
def post_telemetry(state, params, body):
    session_id = params["_session_id"]
    events = body.get("events")
    if not isinstance(events, list):
        raise bad_request("invalid_request", "campo 'events' deve ser uma lista")

    accepted = 0
    dropped = 0
    last_seq = None
    for event in events[:200]:
        if not isinstance(event, dict):
            dropped += 1
            continue
        event_type = event.get("type")
        # Allow-list, not a deny-list: the page cannot introduce an event
        # type the auditor was never shown in the disclosure panel.
        if event_type not in EVENT_TYPES:
            dropped += 1
            continue
        seq = event.get("seq")
        client_ts = event.get("client_ts")
        _record_event(
            state,
            session_id,
            event_type,
            {
                "seq": seq if isinstance(seq, int) else None,
                "client_ts": client_ts if isinstance(client_ts, str) else None,
                **sanitize_payload(event.get("payload")),
            },
        )
        accepted += 1
        if isinstance(seq, int):
            last_seq = seq if last_seq is None else max(last_seq, seq)

    # The client compares last_seq against what it sent so a beacon lost on
    # page-hide becomes a visible telemetry_gap_detected event instead of a
    # silently shorter file. sendBeacon cannot read a response, so this is
    # the only way the loss can ever be noticed.
    return 202, {"accepted": accepted, "dropped": dropped, "last_seq": last_seq}


# ---------------------------------------------------------------------------
# the seam for the next change: policy editing
# ---------------------------------------------------------------------------


@routing.route("POST", "/api/audit/change-requests", realm="audit", requires_session=True)
def post_change_request(state, params, body):
    """"This should be different", anchored to one record and one rule.

    Records intent; changes nothing. The next change turns these into actual
    policy edits with versioning and history -- which is exactly why the
    payload is fixed now (event_id + rule_id + optional note) and why they
    go to their own file rather than into the behavioural telemetry.

    The note is optional in earnest: no validation, no required flag. An
    auditor forced to justify every marking produces justifications about
    being asked, not about the rule.
    """
    session_id = params["_session_id"]
    record_event_id = body.get("record_event_id")
    rule_id = body.get("rule_id")
    note = body.get("note")

    if not isinstance(record_event_id, str) or not record_event_id:
        raise bad_request("invalid_request", "campo 'record_event_id' ausente")
    if rule_id is not None and not isinstance(rule_id, str):
        raise bad_request("invalid_request", "campo 'rule_id' deve ser texto")
    if note is not None and not isinstance(note, str):
        raise bad_request("invalid_request", "campo 'note' deve ser texto")

    note = (note or "").strip()
    change_request_id = uuid.uuid4().hex
    logger = state.change_request_logger
    if logger is not None:
        logger.log(
            {
                "change_request_id": change_request_id,
                "session_id": session_id,
                "record_event_id": record_event_id,
                "rule_id": rule_id,
                "note": note,
                "audit_log_path": str(_audit_log_path(state)),
                "policy_versions_at_time": _policy_versions(state, record_event_id),
                # Stated in the record itself, not only on screen: whoever
                # reads this file later must not have to infer that nothing
                # was applied when it was written.
                "applied": False,
                "note_absent": not note,
            }
        )

    _record_event(
        state,
        session_id,
        "change_request_submitted",
        {
            "record_event_id": record_event_id,
            "rule_id": rule_id,
            "change_request_id": change_request_id,
            "has_note": bool(note),
        },
    )
    return 201, {
        "change_request_id": change_request_id,
        "applied": False,
        "message": (
            "Registrado como intenção. A política não foi alterada: a edição "
            "efetiva das regras chega na próxima etapa."
        ),
    }


def _policy_versions(state, record_event_id: str) -> Optional[dict]:
    """The config_versions of the record the request was made from, so a
    later reader knows which policy the auditor was actually judging."""
    path = _audit_log_path(state)
    if not path.exists():
        return None
    scanned = 0
    for _offset, record in iter_records_reverse(path):
        scanned += 1
        if scanned > audit_view.AUDIT_PAGE_SCAN_LIMIT:
            return None
        if record is not None and record.get("event_id") == record_event_id:
            return record.get("config_versions")
    return None


@routing.route("GET", "/api/audit/change-requests", realm="audit", requires_session=True)
def get_change_requests(state, params, body):
    logger = state.change_request_logger
    wanted = params.get("record")
    requests: List[dict] = []
    if logger is not None and Path(logger.path).exists():
        for _offset, record in iter_records_reverse(Path(logger.path)):
            if record is None:
                continue
            if wanted and record.get("record_event_id") != wanted:
                continue
            requests.append(record)
            if len(requests) >= 200:
                break
    requests.reverse()
    return {"change_requests": requests, "count": len(requests)}


# ---------------------------------------------------------------------------
# param helpers
# ---------------------------------------------------------------------------


def _int_param(params, name, default, minimum, maximum):
    raw = params.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise bad_request("invalid_request", f"parâmetro '{name}' deve ser um inteiro") from None
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _cursor_param(params) -> Optional[int]:
    raw = params.get("cursor")
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise bad_request("invalid_cursor", "cursor inválido") from None
    if value < 0:
        raise bad_request("invalid_cursor", "cursor inválido")
    return value
