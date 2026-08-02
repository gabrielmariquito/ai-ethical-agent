from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from .types import Decision, Stage, Verdict


class AuditLogger:
    def __init__(self, path: Union[str, Path] = "logs/audit.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, record: dict) -> str:
        event_id = str(uuid.uuid4())
        enriched = {
            "event_id": event_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **record,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(enriched, ensure_ascii=False) + "\n")
        return event_id


# ---------------------------------------------------------------------------
# The three sentences the audit trail says to a human. Built here, in one
# place, and nowhere else.
#
# They used to be written out four times -- _CliAuditLogger and _build_audit in
# __main__.py, _WebAuditLogger in webui/state.py, build_audit in
# webui/engine_factory.py -- each an independent copy of the same wording. That
# is the shape that let check_audit_record and resolve_llm drift apart before
# they were consolidated, and these strings are load-bearing: AUDIT_GUIDE
# quotes the first two verbatim, and the mandatory-trail claim in README rests
# on the disclosure actually appearing.
#
# What is deliberately NOT unified is what each caller *does* with the text.
# The CLI prints to stderr and stops there; the web server also keeps the
# string on the logger instance so the browser can show it, because a browser
# tab has no visible stderr (see engine_factory.audit_notice_lines). That
# difference is real and documented -- only the wording is shared.


def audit_write_failure_message(path, exc: BaseException) -> str:
    """A record could not be written. Never fatal: the caller reports this and
    continues, because losing the trail must not change a verdict."""
    return (
        f"[audit] could not write audit record to {path} "
        f"({exc.__class__.__name__}: {exc}); continuing without "
        "logging this event"
    )


def audit_first_write_notice(path) -> str:
    """One-time disclosure, on the first successful write of a process, of
    where the trail lives. Quoted verbatim in AUDIT_GUIDE.pt-BR.md."""
    return f"[audit] writing to {path} (mandatory; see AUDIT_GUIDE.pt-BR.md)"


def audit_init_failure_message(path, exc: BaseException) -> str:
    """The logger itself could not be constructed (bad path, permissions).
    The command still runs, without a trail."""
    return (
        f"[audit] could not initialize audit log at {path} "
        f"({exc.__class__.__name__}: {exc}); continuing without audit logging"
    )


def build_check_audit_record(engine, verdict: Verdict, stage: Stage, text: str) -> dict:
    """Builds the audit record for a single stateless `check` (no LLM call).

    Shared by the CLI's `cmd_check` and the GUI's Check tab so the two
    front-ends cannot independently drift on what content gets retained --
    in particular, raw content is withheld when the verdict's REWRITE was
    caused by a redact:true rule (verdict.suppresses_raw_content), matching
    the same rule GuardedAgent.process() applies to trace["raw_response"].
    """
    record = {
        "status": "denied" if verdict.decision is Decision.DENY else "ok",
        "engine": engine.name,
        "config_versions": engine.describe_config(),
    }
    if stage is Stage.INPUT:
        record["input"] = text
        record["input_verdict"] = verdict.to_dict()
    else:
        record["output_verdict"] = verdict.to_dict()
        if verdict.decision is not Decision.DENY and not verdict.suppresses_raw_content:
            record["raw_response"] = text
    return record
