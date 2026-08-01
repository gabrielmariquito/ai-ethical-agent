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
