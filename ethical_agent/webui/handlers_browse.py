from __future__ import annotations

from pathlib import Path
from typing import List

from . import routing
from .errors import bad_request

# Nota de segurança: este endpoint lista diretórios da máquina, e o bind em
# 127.0.0.1 limita quem alcança mas não é fronteira por si —
# versão longa em `997a6fe^`.

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWED_ROOTS = [REPO_ROOT, Path.home().resolve()]


def _is_within_allowed_roots(path: Path) -> bool:
    for root in ALLOWED_ROOTS:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _resolve_allowed(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser() if raw_path else REPO_ROOT
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise bad_request("invalid_path", f"could not resolve path: {exc}") from exc
    if not _is_within_allowed_roots(resolved):
        allowed = ", ".join(str(root) for root in ALLOWED_ROOTS)
        raise bad_request(
            "path_not_allowed",
            f"browsing is restricted to {allowed} and their subdirectories",
        )
    return resolved


@routing.route("GET", "/api/browse")
def browse(state, params, body):
    resolved = _resolve_allowed(params.get("path", ""))
    if not resolved.is_dir():
        raise bad_request("not_a_directory", f"{resolved} is not a directory")

    entries: List[dict] = []
    try:
        for child in resolved.iterdir():
            if child.name.startswith("."):
                continue
            entries.append({"name": child.name, "is_dir": child.is_dir()})
    except OSError as exc:
        raise bad_request("listing_failed", f"could not list {resolved}: {exc}") from exc
    entries.sort(key=lambda e: (not e["is_dir"], e["name"].lower()))

    parent = resolved.parent
    parent_allowed = parent != resolved and _is_within_allowed_roots(parent)

    return {
        "path": str(resolved),
        "parent": str(parent) if parent_allowed else None,
        "entries": entries,
    }
