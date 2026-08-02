from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ._stdio import ensure_utf8_stdio
from .agent import GuardedAgent
from .audit import AuditLogger, build_check_audit_record
from .demo import DEMO_CASES, demo_scripted
from .engine import CompositeEngine, PolicyEngine, RuleBasedEngine
from .evaluate import evaluate_engine, format_report, load_dataset
from .kg_engine import KnowledgeGraphEngine
from .llm import LLMClient, MockLLM, describe_llm_provenance, resolve_llm
from .ollama_install import DEFAULT_LOCAL_MODEL, read_env_model
from .ontology import register_concept_condition
from .policy import Policy, default_policy_path
from .relaieo import (
    default_grounding_path,
    default_norms_path,
    default_relaieo_ttl,
    load_relaieo,
)
from .types import ActionContext, Stage

# Same reasoning as gui_app.py's DEFAULT_MODEL: if the wizard installed a
# local model it recorded it in <repo root>/.env (OLLAMA_MODEL=...); default
# to that instead of a model that was never actually pulled. `parent.parent`
# only lands on the repo root for an editable checkout (the wizard's own
# install flow) -- for a non-editable install it resolves inside
# site-packages, where no .env exists, so this just falls back to the
# previous hardcoded default.
_DEFAULT_MODEL = read_env_model(Path(__file__).resolve().parent.parent, DEFAULT_LOCAL_MODEL)


class _CliAuditLogger(AuditLogger):
    """AuditLogger that fails soft on the CLI: a write error is reported to
    stderr instead of crashing the command, and the first successful write
    in a process prints a one-time disclosure of where the trail lives.
    """

    def __init__(self, path):
        self._notice_shown = False
        super().__init__(path)

    def log(self, record: dict) -> Optional[str]:
        try:
            event_id = super().log(record)
        except Exception as exc:
            print(
                f"[audit] could not write audit record to {self.path} "
                f"({exc.__class__.__name__}: {exc}); continuing without "
                "logging this event",
                file=sys.stderr,
            )
            return None
        if not self._notice_shown:
            self._notice_shown = True
            print(
                f"[audit] writing to {self.path} (mandatory; "
                "see AUDIT_GUIDE.pt-BR.md)",
                file=sys.stderr,
            )
        return event_id


def _build_audit(args: argparse.Namespace) -> Optional[AuditLogger]:
    try:
        return _CliAuditLogger(args.audit_log)
    except Exception as exc:
        print(
            f"[audit] could not initialize audit log at {args.audit_log} "
            f"({exc.__class__.__name__}: {exc}); continuing without audit logging",
            file=sys.stderr,
        )
        return None


def _build_engine(args: argparse.Namespace) -> PolicyEngine:
    ontology = None
    if args.engine in ("kg", "hybrid"):
        ontology = load_relaieo(args.ontology, args.grounding, args.norms)
        register_concept_condition(ontology)
    if args.engine == "kg":
        return KnowledgeGraphEngine(ontology)
    rule_engine = RuleBasedEngine(Policy.from_file(args.policy))
    if args.engine == "rule":
        return rule_engine
    return CompositeEngine(
        [rule_engine, KnowledgeGraphEngine(ontology)], name="hybrid"
    )


def cmd_check(args: argparse.Namespace) -> int:
    engine = _build_engine(args)
    audit = _build_audit(args)
    stage = Stage(args.stage)
    verdict = engine.evaluate(ActionContext(content=args.text, stage=stage))

    if audit is not None:
        audit.log(build_check_audit_record(engine, verdict, stage, args.text))

    if args.json:
        print(json.dumps(verdict.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(verdict.explain())
    return 2 if verdict.intervened else 0


def cmd_eval(args: argparse.Namespace) -> int:
    # Intentionally never audited: this runs hundreds of synthetic dataset
    # cases directly against the engine, and logging them would swamp the
    # real usage trail with non-real data. args.audit_log exists on this
    # namespace (it's a global arg) but is never read here.
    engine = _build_engine(args)
    cases = load_dataset(args.dataset)
    results = evaluate_engine(engine, cases)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(format_report(results))
    return 0 if not results["mismatches"] else 1


def _build_llm(args: argparse.Namespace) -> tuple[LLMClient, dict]:
    llm, provenance = resolve_llm(args.model, args.mock)
    if provenance["kind"] == "mock_fallback":
        print(
            f"[Ollama unavailable ({provenance['fallback_reason']}); "
            "using MockLLM]",
            file=sys.stderr,
        )
    return llm, provenance


def cmd_process(args: argparse.Namespace) -> int:
    engine = _build_engine(args)
    llm, llm_provenance = _build_llm(args)
    audit = _build_audit(args)
    agent = GuardedAgent(
        engine=engine, llm=llm, audit=audit, llm_provenance=llm_provenance
    )
    result = agent.process(args.text)

    if args.json:
        print(
            json.dumps(
                {
                    "status": result.status,
                    "message": result.message,
                    "response": result.response,
                    "llm_provenance": llm_provenance,
                    "input_verdict": result.input_verdict.to_dict(),
                    "output_verdict": (
                        result.output_verdict.to_dict()
                        if result.output_verdict is not None
                        else None
                    ),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(describe_llm_provenance(llm_provenance))
        print(result.message)
        if args.verbose:
            print("-" * 72)
            print("Input verdict:")
            print(_indent(result.input_verdict.explain()))
            if result.output_verdict is not None:
                print("Output verdict:")
                print(_indent(result.output_verdict.explain()))

    return 0 if result.status == "ok" else 2


def cmd_demo(args: argparse.Namespace) -> int:
    engine = _build_engine(args)
    audit = _build_audit(args)

    agent = GuardedAgent(engine=engine, llm=MockLLM(demo_scripted), audit=audit, source="demo")

    for text in DEMO_CASES:
        result = agent.process(text)
        print("=" * 72)
        print(f"USER     : {text}")
        print(f"STATUS   : {result.status.upper()}")
        print(f"RESPONSE : {result.message}")
        print("-" * 72)
        print("Input verdict:")
        print(_indent(result.input_verdict.explain()))
        if result.output_verdict is not None:
            print("Output verdict:")
            print(_indent(result.output_verdict.explain()))
    print("=" * 72)
    print("(Responses generated by MockLLM; plug OllamaClient for a real model.)")
    return 0


def _indent(text: str, prefix: str = "    ") -> str:
    return "\n".join(prefix + line for line in text.splitlines())


DEFAULT_WEB_PORT = 8765


def cmd_serve(args: argparse.Namespace) -> int:
    # Lazy import: webui/ is only needed for this one subcommand, so the
    # other subcommands (check/eval/demo/process) don't pay its import cost.
    from .webui.server import make_server

    initial_config = {
        "policy": args.policy,
        "ontology": args.ontology,
        "grounding": args.grounding,
        "norms": args.norms,
        "engine": args.engine,
        "audit_log": args.audit_log,
        "model": _DEFAULT_MODEL,
        # Web-UI-only default -- the CLI's own `process --mock` stays an
        # explicit opt-in flag, untouched (see cmd_process below). resolve_llm
        # already falls back to MockLLM (kind="mock_fallback") if the real
        # model can't be reached, so this doesn't risk a hard failure; it
        # just means someone opening the chat for the first time gets a real
        # answer when Ollama is there, instead of a canned string they'd have
        # to notice and turn off manually.
        "mock": False,
    }
    server = make_server(args.port, initial_config)
    print(
        f"Serving at http://127.0.0.1:{args.port} "
        "(127.0.0.1 apenas -- não acessível pela rede). Ctrl+C to stop"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def main(argv=None) -> int:
    ensure_utf8_stdio()
    parser = argparse.ArgumentParser(
        prog="ethical_agent",
        description="Neuro-symbolic ethical guardrail (rule-based + knowledge graph).",
    )
    parser.add_argument(
        "--policy",
        default=str(default_policy_path()),
        help="path to the policy JSON (default: policies/core_policy.json)",
    )
    parser.add_argument(
        "--ontology",
        default=str(default_relaieo_ttl()),
        help="path to the RelAIEO ontology (default: ontologies/relaieo.ttl)",
    )
    parser.add_argument(
        "--grounding",
        default=str(default_grounding_path()),
        help="path to the grounding lexicon (default: ontologies/relaieo_grounding.json)",
    )
    parser.add_argument(
        "--norms",
        default=str(default_norms_path()),
        help="path to the KG norms (default: ontologies/relaieo_norms.json)",
    )
    parser.add_argument(
        "--engine",
        choices=["rule", "kg", "hybrid"],
        default="hybrid",
        help="engine to use (default: hybrid = rule-based + knowledge graph)",
    )
    parser.add_argument(
        "--audit-log",
        default="logs/audit.jsonl",
        help=(
            "path to the audit JSONL log written by check/process/demo "
            "(default: logs/audit.jsonl); ignored by eval, which never audits"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="evaluate one piece of content")
    p_check.add_argument("text")
    p_check.add_argument(
        "--stage", choices=[s.value for s in Stage], default="input"
    )
    p_check.add_argument("--json", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_eval = sub.add_parser("eval", help="run the evaluation harness")
    p_eval.add_argument(
        "--dataset",
        default=str(default_policy_path().parents[1] / "eval" / "dataset.json"),
    )
    p_eval.add_argument("--json", action="store_true")
    p_eval.set_defaults(func=cmd_eval)

    p_demo = sub.add_parser("demo", help="offline demo of the guarded pipeline")
    p_demo.set_defaults(func=cmd_demo)

    p_process = sub.add_parser(
        "process", help="run one prompt through the full guarded pipeline (LLM included)"
    )
    p_process.add_argument("text")
    p_process.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Ollama model to use (default: {_DEFAULT_MODEL})",
    )
    p_process.add_argument(
        "--mock",
        action="store_true",
        help="skip Ollama entirely and use a fixed MockLLM response",
    )
    p_process.add_argument(
        "--verbose", action="store_true", help="also print the full verdict explanation"
    )
    p_process.add_argument("--json", action="store_true")
    p_process.set_defaults(func=cmd_process)

    p_serve = sub.add_parser(
        "serve", help="run the local web interface (stdlib http.server, 127.0.0.1 only)"
    )
    p_serve.add_argument(
        "--port",
        type=int,
        default=DEFAULT_WEB_PORT,
        help=f"port to listen on, 127.0.0.1 only (default: {DEFAULT_WEB_PORT})",
    )
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
