from __future__ import annotations

from pathlib import Path

from ethical_agent import default_policy_path
from ethical_agent.evaluate import (
    evaluate_engine,
    format_report,
    load_dataset,
    resumo_da_divisao,
)

from . import routing
from .engine_factory import build_engine
from .errors import bad_request


def eval_dir() -> Path:
    return (default_policy_path().parents[1] / "eval").resolve()


def default_dataset_path() -> str:
    return str(eval_dir() / "dataset.json")


def _resolve_dataset(raw) -> str:
    """Confina o dataset a `eval/`: sem isto, qualquer JSON com um array
    `cases` era legível e as mensagens distinguiam os erros — um oráculo: `REGISTRO`, "Texto movido do código".
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
    """Espelha o `eval` da CLI e nunca toca no `AuditLogger`, porque roda um
    lote de casos sintéticos direto no motor: `REGISTRO`, "Texto movido do código".
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

    # Esta tela lê o dataset inteiro, mas `full` é uma metade como outra qualquer
    # e tem de se nomear: nenhum recall viaja sem a metade ao lado.
    divisao = resumo_da_divisao(cases, cases, "full")
    results = evaluate_engine(engine, cases, divisao=divisao)
    results["report_text"] = format_report(results)
    return results
