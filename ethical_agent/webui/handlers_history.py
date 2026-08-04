from __future__ import annotations

from . import routing
from .archive import build_readonly_transcript, summarize_conversations
from .errors import not_found


def _audit_log(state, params: dict) -> str:
    return params.get("audit_log") or state.initial_config["audit_log"]


@routing.route("GET", "/api/chat/history")
def get_history(state, params, body):
    """Lista de conversas passadas, vinda da trilha e nunca do `ConversationStore`
    (em memória, efêmero): é a única fonte da barra lateral, então sobrevive a
    um reinício.
    """
    return summarize_conversations(_audit_log(state, params))


@routing.route("GET", "/api/chat/history/{conversation_id}")
def get_history_conversation(state, params, body):
    """Read-only reconstruction of one past conversation. Deliberately not
    fed back into agent.process() anywhere -- see archive.py's module
    docstring and the plan's rationale for why this stays view-only."""
    turns = build_readonly_transcript(_audit_log(state, params), params["conversation_id"])
    if turns is None:
        raise not_found(
            "unknown_conversation",
            f"no archived conversation with id {params['conversation_id']!r}",
        )
    return {"conversation_id": params["conversation_id"], "turns": turns}
