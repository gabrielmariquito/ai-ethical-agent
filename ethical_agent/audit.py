from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from .provenance import build_configuration
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


# As três frases que a trilha diz a um humano, construídas aqui e em nenhum
# outro lugar; eram escritas quatro vezes, e o AUDIT_GUIDE cita duas delas
# literalmente — versão longa em `997a6fe^`.


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
    """Monta o registro de um `check` isolado, compartilhado pelas duas frentes
    para que não divirjam sobre o que é retido — em particular o conteúdo
    bruto é omitido quando a REWRITE veio de regra `redact`: versão longa em `997a6fe^`.
    """
    record = {
        "status": "denied" if verdict.decision is Decision.DENY else "ok",
        "engine": engine.name,
        "config_versions": engine.describe_config(),
        "configuration": build_configuration(engine),
    }
    if stage is Stage.INPUT:
        record["input"] = text
        record["input_verdict"] = verdict.to_dict()
    else:
        record["output_verdict"] = verdict.to_dict()
        if verdict.decision is not Decision.DENY and not verdict.suppresses_raw_content:
            record["raw_response"] = text
    return record
