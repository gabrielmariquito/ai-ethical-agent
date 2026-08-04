from __future__ import annotations

import threading
from typing import Optional

from ethical_agent import GuardedAgent
from ethical_agent.demo import interactive_mock_response

from . import routing
from .dto import turn_result_to_dict
from .engine_factory import audit_notice_lines, build_audit, build_engine, build_llm
from .errors import bad_request, not_found
from .progress import ProgressReportingLLM


@routing.route("POST", "/api/chat/new")
def new_conversation(state, params, body):
    return {"conversation_id": state.conversations.create()}


@routing.route("GET", "/api/chat/conversations/{conversation_id}")
def get_conversation(state, params, body):
    """Usado só na reconciliação do frontend após recarga: o navegador nunca
    confia no espelho de `sessionStorage` sem conferir aqui, e a rota não é
    `/api/chat/{id}` porque o curinga engoliria os literais irmãos: versão longa em `997a6fe^`.
    """
    turn_count = state.conversations.turn_count(params["conversation_id"])
    if turn_count is None:
        return {"exists": False, "turn_count": 0}
    return {"exists": True, "turn_count": turn_count}


def _require_str(body: dict, field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise bad_request("invalid_request", f"'{field}' is required and must be a non-empty string")
    return value


def _config_value(config: dict, initial_config: dict, key: str):
    return config[key] if key in config else initial_config[key]


@routing.route("POST", "/api/chat/message")
def post_message(state, params, body):
    conversation_id = _require_str(body, "conversation_id")
    text = _require_str(body, "text")
    config = body.get("config") or {}
    if not isinstance(config, dict):
        raise bad_request("invalid_request", "'config' must be an object")

    if not state.conversations.exists(conversation_id):
        raise not_found("unknown_conversation", f"no conversation with id {conversation_id!r}")

    job_id = state.jobs.create()
    thread = threading.Thread(
        target=_run_turn,
        args=(state, conversation_id, text, config, job_id),
        daemon=True,
    )
    thread.start()
    return 202, {"job_id": job_id}


def _run_turn(state, conversation_id: str, text: str, config: dict, job_id: str) -> None:
    conv_lock = state.conversations.conversation_lock(conversation_id)
    if conv_lock is None:
        # The conversation existed at request time but is gone now (can only
        # happen if something external cleared server state mid-flight) --
        # report it the same way an unknown conversation would be, just via
        # the job's error phase instead of an HTTP 404, since the client
        # already moved past the synchronous request.
        state.jobs.set_error(
            job_id,
            {"error": "unknown_conversation", "message": "conversation vanished before the turn started"},
        )
        return

    with conv_lock:
        try:
            history_list = state.conversations.history_list(conversation_id)
            snapshot = list(history_list)
            turn_index = len(snapshot) + 1

            policy = _config_value(config, state.initial_config, "policy")
            ontology = _config_value(config, state.initial_config, "ontology")
            grounding = _config_value(config, state.initial_config, "grounding")
            norms = _config_value(config, state.initial_config, "norms")
            engine_kind = _config_value(config, state.initial_config, "engine")
            audit_log = _config_value(config, state.initial_config, "audit_log")
            model = _config_value(config, state.initial_config, "model")
            mock = bool(_config_value(config, state.initial_config, "mock"))

            engine = build_engine(policy, ontology, grounding, norms, engine_kind)
            audit, init_warning = build_audit(audit_log, state.audit_lock)
            raw_llm, llm_provenance = build_llm(model, mock, responses=interactive_mock_response)

            def on_phase(phase: str) -> None:
                state.jobs.set_phase(job_id, phase)

            llm = ProgressReportingLLM(raw_llm, on_phase)

            agent = GuardedAgent(engine=engine, llm=llm, audit=audit, llm_provenance=llm_provenance)
            result = agent.process(
                text,
                history=snapshot,
                conversation_id=conversation_id,
                turn_index=turn_index,
            )

            # Invariante herdada do antigo `gui_app.py`: acrescenta incondicionalmente,
            # antes de qualquer serialização que possa levantar.
            history_list.append(result)

            notices = audit_notice_lines(audit, init_warning)
            payload = turn_result_to_dict(result, llm_provenance, turn_index, notices)
        except Exception as exc:  # noqa: BLE001 -- never leave a job stuck mid-phase
            kind = (
                "engine_build_failed"
                if isinstance(exc, (FileNotFoundError, ValueError, OSError))
                else "internal_error"
            )
            state.jobs.set_error(job_id, {"error": kind, "message": f"{exc.__class__.__name__}: {exc}"})
            return

    state.jobs.set_done(job_id, payload)


@routing.route("GET", "/api/chat/jobs/{job_id}")
def get_job(state, params, body):
    job = state.jobs.get(params["job_id"])
    if job is None:
        raise not_found("unknown_job", f"no job with id {params['job_id']!r}")
    response: dict = {"phase": job["phase"]}
    if job["phase"] == "done":
        response["result"] = job["result"]
    elif job["phase"] == "error":
        response["error"] = job["error"]
    return response
