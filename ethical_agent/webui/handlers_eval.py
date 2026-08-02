from __future__ import annotations

from pathlib import Path

from ethical_agent import default_policy_path
from ethical_agent.evaluate import evaluate_engine, format_report, load_dataset

from . import routing
from .engine_factory import build_engine
from .errors import bad_request


def eval_dir() -> Path:
    return (default_policy_path().parents[1] / "eval").resolve()


def default_dataset_path() -> str:
    return str(eval_dir() / "dataset.json")


def _resolve_dataset(raw) -> str:
    """Confines the dataset to eval/.

    Without this, `dataset` is whatever the request names, and post_eval
    opens it: any JSON on disk with a `cases` array is readable, and even for
    a file that does not parse the error tells "no such file" apart from "bad
    JSON" apart from "no cases" -- a file-existence oracle for anything the
    process can read. handlers_browse.py has ALLOWED_ROOTS and
    handlers_audit._audit_log_path refuses a request-supplied path for
    exactly this reason; being behind the audit session does not change it,
    because that is precisely the caller _audit_log_path declines to trust.
    """
    if raw is None or raw == "":
        return default_dataset_path()
    if not isinstance(raw, str):
        raise bad_request("invalid_request", "'dataset' must be a string")
    root = eval_dir()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    # Rejected, never silently redirected: taking only the basename would let
    # "/etc/passwd/dataset.json" quietly become eval/dataset.json and report
    # success for a file the caller never asked about. The screen sends the
    # absolute path /api/choices advertised, so both forms have to be
    # accepted -- but only inside eval/.
    try:
        candidate.relative_to(root)
    except ValueError:
        raise bad_request("invalid_request", "'dataset' must name a file in eval/") from None
    if not candidate.is_file():
        # Same wording whatever the reason. Distinguishing "outside eval/"
        # from "not a file" would answer questions about the filesystem.
        raise bad_request("invalid_request", "'dataset' must name a file in eval/")
    return str(candidate)


@routing.route(
    "POST", "/api/eval", realm="audit", requires_session=True, hidden_without_session=True
)
def post_eval(state, params, body):
    """Mirrors the CLI's `ethical_agent eval` / the former gui_app.py's
    EvalTab exactly. Intentionally never touches AuditLogger, matching
    cmd_eval's own comment: this runs a batch of synthetic dataset cases
    directly against the engine, and logging them would swamp the real
    usage trail with non-real data. `config` here is only ever read for
    policy/ontology/grounding/norms/engine -- never for audit_log, even if
    a caller's shared config object happens to carry one.

    Behind the audit realm, and the most clearly so of the three tools: every
    mismatch it returns carries the case's content, the rules that fired and
    the engine's reason, so one request maps hundreds of content->rule pairs
    at once. A dataset is a map of where the policy gives.
    """
    dataset = _resolve_dataset(body.get("dataset"))
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
