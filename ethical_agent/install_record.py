"""O que o instalador de fato fez, escrito para o desinstalador, que sem isto
teria de adivinhar: versão longa em `997a6fe^`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

RECORD_NAME = ".ethical-agent-install.json"
RECORD_VERSION = 1


@dataclass(frozen=True)
class InstallRecord:
    created_at: str = ""
    # find_ollama_exe() is not None, evaluated before the wizard acted. None
    # means the wizard never got as far as looking (LLM step declined or the
    # project install failed).
    ollama_was_present_before: Optional[bool] = None
    ollama_exe: Optional[str] = None
    # Set only when `ollama pull` actually ran and succeeded -- not when the
    # model was already there.
    model_pulled: Optional[str] = None
    env_keys: Tuple[str, ...] = ()
    # %TEMP%/OllamaSetup.exe. Recorded so the uninstaller can report the
    # leftover; never removed (it is outside the project directory).
    installer_download: Optional[str] = None


def record_path(root: Path) -> Path:
    return root / RECORD_NAME


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def read_record(root: Path) -> Optional[InstallRecord]:
    """Returns None for missing, unreadable, corrupt or unrecognised files.

    Every one of those means the same thing to the caller -- "no information"
    -- and none of them is worth failing an uninstall over.
    """
    try:
        raw = record_path(root).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != RECORD_VERSION:
        return None

    env_keys = data.get("env_keys")
    if not isinstance(env_keys, list) or not all(isinstance(k, str) for k in env_keys):
        env_keys = []

    def _opt_str(key: str) -> Optional[str]:
        value = data.get(key)
        return value if isinstance(value, str) else None

    def _opt_bool(key: str) -> Optional[bool]:
        value = data.get(key)
        return value if isinstance(value, bool) else None

    return InstallRecord(
        created_at=_opt_str("created_at") or "",
        ollama_was_present_before=_opt_bool("ollama_was_present_before"),
        ollama_exe=_opt_str("ollama_exe"),
        model_pulled=_opt_str("model_pulled"),
        env_keys=tuple(env_keys),
        installer_download=_opt_str("installer_download"),
    )


def write_record(
    root: Path,
    record: InstallRecord,
    now: Callable[[], datetime] = _utc_now,
) -> Optional[Path]:
    """Funde os campos não-vazios de `record` com o que está em disco, em vez
    de sobrescrever, porque o wizard aprende esses fatos em momentos
    diferentes: versão longa em `997a6fe^`.
    """
    try:
        existing = read_record(root) or InstallRecord()
        updates = {}
        for key, value in asdict(record).items():
            if value is None or value == "" or value == ():
                continue
            updates[key] = value
        merged = replace(existing, **updates)
        if not merged.created_at:
            merged = replace(merged, created_at=now().isoformat())

        payload = {"version": RECORD_VERSION, **asdict(merged)}
        payload["env_keys"] = list(merged.env_keys)
        payload["updated_at"] = now().isoformat()

        path = record_path(root)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path
    except Exception:  # noqa: BLE001 -- bookkeeping never breaks an install
        return None


def describe_record(record: Optional[InstallRecord]) -> List[str]:
    """pt-BR lines about what the installer recorded, for the preview screen."""
    if record is None:
        return ["Não há registro de instalação -- este projeto foi instalado "
                "antes desta versão do desinstalador, ou à mão."]
    lines = []
    if record.created_at:
        lines.append(f"Instalado em {record.created_at}")
    if record.ollama_was_present_before is True:
        lines.append("O Ollama já existia nesta máquina antes desta instalação.")
    elif record.ollama_was_present_before is False:
        lines.append("Não havia Ollama localizável antes desta instalação.")
    if record.model_pulled:
        lines.append(f"Modelo baixado por este instalador: {record.model_pulled}")
    if record.env_keys:
        lines.append(f"Chaves gravadas no .env: {', '.join(record.env_keys)}")
    return lines
