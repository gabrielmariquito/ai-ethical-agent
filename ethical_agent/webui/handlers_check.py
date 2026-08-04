from __future__ import annotations

from ethical_agent import ActionContext, Stage, build_check_audit_record

from . import routing
from .engine_factory import audit_notice_lines, build_audit, build_engine
from .errors import bad_request


def _require_str(body: dict, field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise bad_request("invalid_request", f"'{field}' is required and must be a non-empty string")
    return value


@routing.route(
    "POST", "/api/check", realm="audit", requires_session=True, hidden_without_session=True
)
def post_check(state, params, body):
    """Espelha o `check` da CLI: avalia UM conteúdo contra o guardrail, sem
    chamada de LLM, pelo `build_check_audit_record` compartilhado: `REGISTRO`, "Texto movido do código".
    """
    text = _require_str(body, "text")
    stage_raw = body.get("stage") or "input"
    config = body.get("config") or {}
    if not isinstance(config, dict):
        raise bad_request("invalid_request", "'config' must be an object")

    try:
        stage = Stage(stage_raw)
    except ValueError as exc:
        raise bad_request("invalid_request", f"unknown stage {stage_raw!r}") from exc

    policy = config.get("policy", state.initial_config["policy"])
    ontology = config.get("ontology", state.initial_config["ontology"])
    grounding = config.get("grounding", state.initial_config["grounding"])
    norms = config.get("norms", state.initial_config["norms"])
    engine_kind = config.get("engine", state.initial_config["engine"])
    audit_log = config.get("audit_log", state.initial_config["audit_log"])

    try:
        engine = build_engine(policy, ontology, grounding, norms, engine_kind)
    except Exception as exc:  # noqa: BLE001 -- bad config path/JSON, not a server bug
        raise bad_request("engine_build_failed", f"{exc.__class__.__name__}: {exc}") from exc

    audit, init_warning = build_audit(audit_log, state.audit_lock)

    verdict = engine.evaluate(ActionContext(content=text, stage=stage))
    if audit is not None:
        audit.log(build_check_audit_record(engine, verdict, stage, text))

    return {
        "verdict": verdict.to_dict(),
        "intervened": verdict.intervened,
        "system_error": verdict.system_error,
        "audit_notices": audit_notice_lines(audit, init_warning),
    }
