from __future__ import annotations

from ethical_agent import default_policy_path
from ethical_agent.evaluate import evaluate_engine, format_report, load_dataset

from . import routing
from .engine_factory import build_engine
from .errors import bad_request


def default_dataset_path() -> str:
    return str(default_policy_path().parents[1] / "eval" / "dataset.json")


@routing.route("POST", "/api/eval")
def post_eval(state, params, body):
    """Mirrors the CLI's `ethical_agent eval` / the former gui_app.py's
    EvalTab exactly. Intentionally never touches AuditLogger, matching
    cmd_eval's own comment: this runs a batch of synthetic dataset cases
    directly against the engine, and logging them would swamp the real
    usage trail with non-real data. `config` here is only ever read for
    policy/ontology/grounding/norms/engine -- never for audit_log, even if
    a caller's shared config object happens to carry one.
    """
    dataset = body.get("dataset") or default_dataset_path()
    config = body.get("config") or {}
    if not isinstance(config, dict):
        raise bad_request("invalid_request", "'config' must be an object")

    policy = config.get("policy", state.initial_config["policy"])
    ontology = config.get("ontology", state.initial_config["ontology"])
    grounding = config.get("grounding", state.initial_config["grounding"])
    norms = config.get("norms", state.initial_config["norms"])
    engine_kind = config.get("engine", state.initial_config["engine"])

    try:
        engine = build_engine(policy, ontology, grounding, norms, engine_kind)
    except Exception as exc:  # noqa: BLE001 -- bad config path/JSON, not a server bug
        raise bad_request("engine_build_failed", f"{exc.__class__.__name__}: {exc}") from exc

    try:
        cases = load_dataset(dataset)
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise bad_request("dataset_load_failed", f"{exc.__class__.__name__}: {exc}") from exc

    results = evaluate_engine(engine, cases)
    results["report_text"] = format_report(results)
    return results
