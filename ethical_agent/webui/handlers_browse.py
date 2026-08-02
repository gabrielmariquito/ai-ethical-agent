from __future__ import annotations

from pathlib import Path
from typing import List

from . import routing
from .errors import bad_request

# ---------------------------------------------------------------------------
# Security note: this endpoint lists directory contents on the machine the
# server runs on. The bind is 127.0.0.1-only (server.py), which limits who
# can even reach it, but that alone isn't a boundary on *what* it can list --
# without a restriction here, any process on the same machine able to speak
# to the port could enumerate the whole filesystem. Two protections:
#
# 1. Every requested path is resolved (Path.resolve(), which also collapses
#    ".." segments and follows symlinks) and then must be that resolved path
#    itself, or a descendant of it, for at least one entry in ALLOWED_ROOTS
#    -- the repo root and the user's home directory. That covers the normal
#    cases (repo-relative default policy/ontology paths, or a file elsewhere
#    under the user's profile) without exposing the rest of the disk. A path
#    outside both is rejected with 400, not silently clamped to a boundary --
#    the user can still just type an absolute path directly into the config
#    field for anything genuinely outside this, since Browse is a
#    convenience, not the only way to set a path.
# 2. Only name + is_dir are ever returned -- no size, mtime, permissions, or
#    file contents.
# ---------------------------------------------------------------------------

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
