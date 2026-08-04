from __future__ import annotations

import sys
import threading
from typing import List, Optional

from ethical_agent import AuditLogger

# O comportamento do próprio auditor, em arquivos próprios: a trilha do agente
# é o objeto de estudo, e escrever o que o auditor faz dentro dela
# contaminaria o que ela descreve — são dois arquivos, não um:
# `REGISTRO`, "Texto movido do código".

DEFAULT_AUDITOR_SESSION_LOG = "logs/auditor_sessions.jsonl"
DEFAULT_CHANGE_REQUESTS_LOG = "logs/policy_change_requests.jsonl"

# The single source of truth for what may be written. The screen fetches
# this list from the server and shows it to the auditor in plain pt-BR, so
# the disclosure is server-truth rather than a claim the page makes about
# itself; and an unlisted type is rejected, so the file cannot quietly grow
# a field the auditor was never told about.
EVENT_TYPES = (
    "session_started",
    "session_ended",
    "list_page_loaded",
    "filter_changed",
    "record_opened",
    "record_closed",
    "record_dwell_tick",
    "layer_expanded",
    "layer_collapsed",
    "conversation_opened",
    "conversation_turn_focused",
    "change_request_submitted",
    "own_session_events_viewed",
    "telemetry_gap_detected",
)

# Written by the server itself rather than by the page, so they exist even
# when there is no session yet.
SERVER_EVENT_TYPES = (
    "auth_login_succeeded",
    "auth_login_failed",
    "auth_locked_out",
)

ALL_EVENT_TYPES = EVENT_TYPES + SERVER_EVENT_TYPES

# Plain-language description of each event, shown to the auditor inside the
# "this session is being recorded" strip. Instrumenting someone silently in
# an application about transparency would be self-refuting, so the list is
# part of the product, not a comment.
EVENT_TYPE_DESCRIPTIONS = {
    "session_started": "início da sessão de auditoria",
    "session_ended": "fim da sessão, e quanto tempo durou",
    "list_page_loaded": "uma página da lista de registros foi carregada",
    "filter_changed": "você mudou o filtro da lista",
    "record_opened": "você abriu um registro (e se já tinha aberto antes)",
    "record_closed": "você fechou um registro, e quanto tempo ficou nele",
    "record_dwell_tick": "você trocou de aba com um registro aberto",
    "layer_expanded": "você abriu uma camada de detalhe, e em que ordem",
    "layer_collapsed": "você fechou uma camada de detalhe",
    "conversation_opened": "você abriu a conversa completa de um registro",
    "conversation_turn_focused": "você navegou para outro turno da conversa",
    "change_request_submitted": "você marcou que uma regra deveria ser diferente",
    "own_session_events_viewed": "você leu os seus próprios eventos desta sessão",
    "telemetry_gap_detected": "algum evento se perdeu no caminho até o servidor",
    "auth_login_succeeded": "entrada na tela de auditoria",
    "auth_login_failed": "tentativa de entrada com senha incorreta",
    "auth_locked_out": "bloqueio temporário após tentativas seguidas",
}

# Fields the page is allowed to send inside an event payload. An allow-list
# rather than a deny-list: it is what makes "no personal identification"
# checkable instead of merely intended. Nothing here can carry a name, an
# address, or free text -- note that change_request_submitted sends has_note,
# a boolean, while the note itself goes to the change-requests file.
ALLOWED_PAYLOAD_KEYS = frozenset(
    {
        "audit_log_path",
        "kinds",
        "from_kinds",
        "to_kinds",
        "reason",
        "duration_ms",
        "visible_duration_ms",
        "cursor",
        "limit",
        "returned",
        "lines_examined",
        "exhausted_budget",
        "filtered_out",
        "record_event_id",
        "record_kind",
        "intervention",
        "gravity",
        "open_index",
        "revisit",
        "times_seen_before",
        "from",
        "dwell_ms",
        "visible_dwell_ms",
        "visible_dwell_ms_so_far",
        "layers_expanded_in_order",
        "layer",
        "order_index",
        "ms_since_open",
        "ms_open",
        "conversation_id",
        "turn_count",
        "turn_index",
        "from_record_event_id",
        "complete",
        "rule_id",
        "change_request_id",
        "has_note",
        "expected_seq",
        "received_seq",
        "lost",
    }
)


class _FailSoftLogger(AuditLogger):
    """`AuditLogger` que reporta falha de escrita em vez de levantar: perder um
    evento de instrumentação nunca pode derrubar a tela que o auditor está
    usando — o estudo é a leitura, não a telemetria sobre ela: `REGISTRO`, "Texto movido do código".
    """

    def __init__(self, path, lock: threading.Lock):
        self._lock = lock
        self.warning: Optional[str] = None
        self.written = 0
        super().__init__(path)

    def log(self, record: dict) -> Optional[str]:
        with self._lock:
            try:
                event_id = super().log(record)
            except Exception as exc:  # noqa: BLE001 -- mirrors the other loggers' broad catch
                self.warning = (
                    f"[auditor] could not write to {self.path} "
                    f"({exc.__class__.__name__}: {exc}); continuing without "
                    "recording this event"
                )
                print(self.warning, file=sys.stderr)
                return None
            self.written += 1
            return event_id


class AuditorSessionLogger(_FailSoftLogger):
    """logs/auditor_sessions.jsonl -- what the auditor did, never what the
    agent decided."""


class ChangeRequestLogger(_FailSoftLogger):
    """logs/policy_change_requests.jsonl -- "this rule should be different",
    anchored to a record and a rule. Read by the next change; writes nothing
    to policies/ and changes no decision today."""


def sanitize_payload(payload: Optional[dict]) -> dict:
    """Keeps only allow-listed keys, and only JSON scalars/short lists. The
    page is trusted code, but this file is a research artifact that will be
    read by people who need to be able to say what is in it without auditing
    the JavaScript."""
    if not isinstance(payload, dict):
        return {}
    clean = {}
    for key, value in payload.items():
        if key not in ALLOWED_PAYLOAD_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value[:200] if isinstance(value, str) else value
        elif isinstance(value, list):
            clean[key] = [v for v in value if isinstance(v, (str, int, float, bool))][:50]
    return clean


def event_type_catalog() -> List[dict]:
    return [
        {"type": name, "description": EVENT_TYPE_DESCRIPTIONS.get(name, name)}
        for name in ALL_EVENT_TYPES
    ]
