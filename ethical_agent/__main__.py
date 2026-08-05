from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from ._stdio import ensure_utf8_stdio
from .agent import GuardedAgent
from .audit import (
    AuditLogger,
    audit_first_write_notice,
    audit_init_failure_message,
    audit_write_failure_message,
    build_check_audit_record,
)
from .demo import DEMO_CASES, demo_scripted
from .engine import CompositeEngine, PolicyEngine, RuleBasedEngine
from .evaluate import (
    METADES,
    evaluate_engine,
    format_report,
    load_dataset,
    resumo_da_divisao,
    selecionar_metade,
)
from .frames import FramesRecusa, default_frames_path, register_refusal_condition
from .kg_engine import KnowledgeGraphEngine
from .llm import LLMClient, MockLLM, describe_llm_provenance, resolve_llm
from .ollama_install import DEFAULT_LOCAL_MODEL, read_env_model
from .ontology import register_concept_condition
from .policy import Policy, default_policy_path
from .relaieo import (
    default_grounding_path,
    default_harm_grounding_path,
    default_harm_norms_path,
    default_harm_ttl,
    default_norms_path,
    default_relaieo_ttl,
    load_relaieo,
)
from .types import ActionContext, Stage

# Se o wizard instalou um modelo local ele o gravou no `.env`; usar isso evita
# defaultar para um modelo que nunca foi baixado — versão longa em `997a6fe^`.
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
            # Printed and dropped: on the CLI stderr is the only surface there
            # is. The web logger keeps the same string around as well, because
            # a browser tab has no stderr to look at.
            print(audit_write_failure_message(self.path, exc), file=sys.stderr)
            return None
        if not self._notice_shown:
            self._notice_shown = True
            print(audit_first_write_notice(self.path), file=sys.stderr)
        return event_id


def _build_audit(args: argparse.Namespace) -> Optional[AuditLogger]:
    try:
        return _CliAuditLogger(args.audit_log)
    except Exception as exc:
        print(audit_init_failure_message(args.audit_log, exc), file=sys.stderr)
        return None


def _build_engine(args: argparse.Namespace) -> PolicyEngine:
    ontology = None
    # Carregado antes dos dois ramos: normas de dano declaram guarda de frame, e
    # sob `--engine kg` a camada precisa existir do mesmo jeito. Motor sem
    # frames não suprime -- ausência de detector não pode virar isenção.
    frames = FramesRecusa.from_file(args.frames)
    if args.engine in ("kg", "hybrid"):
        ontology = load_relaieo(
            args.ontology, args.grounding, args.norms,
            args.harm_ontology, args.harm_grounding, args.harm_norms,
        )
        register_concept_condition(ontology)
    if args.engine == "kg":
        return KnowledgeGraphEngine(ontology, frames=frames)
    # Registrar antes de `Policy.from_file`: o dispatch de condições resolve o
    # tipo na carga, e um tipo ainda não registrado é erro de política.
    register_refusal_condition(frames)
    rule_engine = RuleBasedEngine(Policy.from_file(args.policy), frames=frames)
    if args.engine == "rule":
        return rule_engine
    return CompositeEngine(
        [rule_engine, KnowledgeGraphEngine(ontology, frames=frames)], name="hybrid"
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


def dataset_curado() -> Path:
    """O conjunto curado in-distribution, que nunca é dividido, resolvido pelo
    pacote e não por nome de arquivo.
    """
    return (default_policy_path().parents[1] / "eval" / "dataset.json").resolve()


def cmd_eval(args: argparse.Namespace) -> int:
    # Deliberadamente nunca auditado: são centenas de casos sintéticos direto no
    # motor, e registrá-los afogaria a trilha de uso real.
    if args.half != "full" and Path(args.dataset).resolve() == dataset_curado():
        print(
            f"erro: {args.dataset} não é dividido -- é o conjunto curado "
            "in-distribution, escrito pelo autor das próprias regras. Ele é "
            "reportado inteiro e separado, nunca somado nem promediado com os "
            "datasets externos. Use --half full (ou omita) para este dataset.",
            file=sys.stderr,
        )
        return 2

    engine = _build_engine(args)
    cases = load_dataset(args.dataset)
    da_metade = selecionar_metade(cases, args.half)
    divisao = resumo_da_divisao(da_metade, cases, args.half)
    results = evaluate_engine(engine, da_metade, divisao=divisao)
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
    from .ollama_install import env_audit_password_present
    from .webui.auth import (
        ENV_PASSWORD_VAR,
        AuditPasswordError,
        dotenv_password_present,
        load_audit_password,
    )
    from .webui.server import PortInUseError, make_server

    try:
        audit_password, password_source, password_warnings = load_audit_password(
            args.audit_password_file
        )
    except AuditPasswordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for warning in password_warnings:
        print(warning, file=sys.stderr)

    initial_config = {
        "policy": args.policy,
        "ontology": args.ontology,
        "grounding": args.grounding,
        "norms": args.norms,
        "engine": args.engine,
        "audit_log": args.audit_log,
        "model": _DEFAULT_MODEL,
        # Default só da interface web; o `--mock` da CLI continua opt-in explícito e
        # `resolve_llm` já cai para `MockLLM` sozinho.
        "mock": False,
    }
    # The password goes in as its own argument, never through initial_config:
    # handlers_choices.py serves that dict verbatim to the chat screen.
    try:
        server = make_server(
            args.port,
            initial_config,
            audit_password=audit_password,
            auditor_session_log=args.auditor_session_log,
            change_requests_log=args.change_requests_log,
        )
    except PortInUseError:
        # Até isto ser pego, um segundo `serve` em porta ocupada não falhava no
        # Windows: ligava ao lado do primeiro e deixava o navegador falando com o
        # processo antigo — versão longa em `997a6fe^`.
        from .uninstall import web_ui_running

        print(f"error: a porta {args.port} já está em uso.", file=sys.stderr)
        if web_ui_running(args.port):
            # A 200 from /api/choices, so it is this project's server and
            # not a stranger's process -- the distinction uninstall.py's
            # helper exists to make, borrowed here for the same reason.
            print(
                "       Já há um servidor deste projeto respondendo nela. "
                "Encerre-o (Ctrl+C na janela dele) antes de subir outro --\n"
                "       se ele foi iniciado com outra configuração, é a dele "
                "que o navegador vê, não a desta.",
                file=sys.stderr,
            )
        else:
            print(
                "       Outro programa está escutando nessa porta.",
                file=sys.stderr,
            )
        print(f"       Ou escolha outra porta: --port {args.port + 1}", file=sys.stderr)
        return 2
    print(
        f"Serving at http://127.0.0.1:{args.port} "
        "(127.0.0.1 apenas -- não acessível pela rede). Ctrl+C to stop"
    )
    if audit_password:
        # The source, never the value.
        print(f"Auditoria: habilitada em /audit (senha de {password_source})")
        # The flag is the only thing that can outrank .env, and naming what
        # it displaced is news the operator can act on: they typed it, in
        # this invocation, so the surprise is bounded to one command line.
        if password_source.startswith("--audit-password-file") and dotenv_password_present():
            print(
                f"           atenção: o .audit-password também tem uma senha, e "
                f"não é a que está valendo ({password_source} tem precedência)"
            )
        # And the flag also silences the stale-variable refusal, which would
        # leave a displaced source unmentioned -- the exact shape of the gap
        # this project logged as D-9. Naming it here is what closes it.
        if password_source.startswith("--audit-password-file") and env_audit_password_present():
            print(
                f"           atenção: ${ENV_PASSWORD_VAR} está definida no "
                "ambiente e não é lida como senha (só o .audit-password e esta "
                "flag são fontes); pode apagá-la"
            )
        print(f"           sessões do auditor em {args.auditor_session_log}")
        print(
            "           a senha separa papéis; não é segurança "
            "(ver AUDIT_GUIDE.pt-BR.md, Passo 8)"
        )
    else:
        # Never says "defina ETHICAL_AGENT_AUDIT_PASSWORD" any more: doing
        # that would produce exit 2 on the next run, which is a banner
        # instructing someone into the error it exists to prevent. (This
        # branch is also unreachable with the variable set -- that state
        # refuses before here -- so it has no reason to mention it.)
        print(
            "Auditoria: desabilitada (/audit não existe). Para habilitar, rode "
            "o instalador (python wizard_gui.py) e preencha o campo de senha, "
            "que grava o hash dela no .audit-password da raiz, ou use "
            "--audit-password-file ARQUIVO"
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
        "--frames",
        default=str(default_frames_path()),
        help="path to the refusal frame triggers (default: frames/refusal_frames.json)",
    )
    parser.add_argument(
        "--harm-ontology",
        default=str(default_harm_ttl()),
        help="path to our harm taxonomy (default: ontologies/harm_taxonomy.ttl)",
    )
    parser.add_argument(
        "--harm-grounding",
        default=str(default_harm_grounding_path()),
        help="path to the harm lexicon (default: ontologies/harm_grounding.json)",
    )
    parser.add_argument(
        "--harm-norms",
        default=str(default_harm_norms_path()),
        help="path to the harm norms (default: ontologies/harm_norms.json)",
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
        default=str(dataset_curado()),
        help="dataset to evaluate (default: the curated in-distribution set)",
    )
    p_eval.add_argument(
        "--half",
        choices=list(METADES),
        default="full",
        help="which half of the dataset to read (recipe divisao/v1). The half "
             "is always named in the output, including for 'full' -- a recall "
             "number without its half named is a claim without provenance.",
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
    p_serve.add_argument(
        "--audit-password-file",
        help=(
            "file whose contents are the password for the /audit screen. "
            "Outranks the only other source, ETHICAL_AGENT_AUDIT_PASSWORD in "
            ".env (what the graphical installer writes). The environment "
            "variable of that name is NOT a source: if it is set and "
            "disagrees with the password in effect, serve refuses to start "
            "rather than ignore it, and this flag is what starts anyway. "
            "With no source at all the audit screen does not exist. There is "
            "deliberately no --audit-password VALUE flag: it would land in "
            "the process list and shell history"
        ),
    )
    p_serve.add_argument(
        "--auditor-session-log",
        default="logs/auditor_sessions.jsonl",
        help=(
            "where the auditor's own session is recorded (default: "
            "logs/auditor_sessions.jsonl); must not be the same file as "
            "--audit-log, which is the agent's trail"
        ),
    )
    p_serve.add_argument(
        "--change-requests-log",
        default="logs/policy_change_requests.jsonl",
        help=(
            '"this rule should be different" markings made from the audit '
            "screen (default: logs/policy_change_requests.jsonl); read by the "
            "policy-editing change, writes nothing to policies/ today"
        ),
    )
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
