"""Which configuration files governed a decision, and a single id for the set.

`config_versions` (PolicyEngine.describe_config) says which *declared* versions
were in memory. That answers "what did the author intend", and it is the
question an author can answer wrongly: editing a rule without bumping
`metadata.version` produces two runs that claim the same version and decide
differently, and the trail cannot tell them apart.

So every artifact carries **both**:

  version -- declared, read from the object loaded in memory
  sha256  -- digest of the file **on disk**, read at write time

The asymmetry is the point. The declared version is what the author meant; the
digest is what was actually loaded. Only the digest catches an edit without a
version bump, and only the declared version survives when there is no file at
all (Policy.from_dict, every test fixture): path omitted => digest "", declared
version kept.

`config_id` is one digest for the whole set. Same `config_id` means the
configuration was identical byte for byte, which means two records are directly
comparable. It is deliberately NOT per engine: the configuration governing a
decision is one thing no matter how many engines voted, and a per-engine
`config_id` would rebuild the nesting problem one level down.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

# ---------------------------------------------------------------------------
# The recipe, written out. Not implicit in the code below -- an implicit recipe
# is what turned three baseline signatures into claims nobody can recompute.
#
# config-id/v1
# ------------
# 1. Each artifact contributes the triple (role, version, sha256).
#    `version` is the one declared in memory; `""` when there is none.
#    `sha256` is the digest of the file on disk; `""` when there is no path.
# 2. `path` does NOT enter the digest. A path is environment, not rule:
#    including it would make two machines with byte-identical configuration
#    produce different config_ids, destroying the one question this exists to
#    answer. It stays visible in artifacts[].
# 3. The triples are sorted, as lists, by (role, version, sha256).
# 4. Canonical document:
#        {"artifacts": [[role, version, sha256], ...], "recipe": "config-id/v1"}
#    serialised with json.dumps(sort_keys=True, separators=(",", ":"),
#    ensure_ascii=False) and encoded UTF-8.
# 5. config_id = sha256(document).hexdigest() -- 64 hex, stored whole.
# 6. The recipe constant is *inside* the hashed document, so changing the
#    recipe necessarily changes every config_id instead of silently producing
#    a different quantity under the same name.
CONFIG_ID_RECIPE = "config-id/v1"

_CHUNK = 1 << 16


def file_sha256(path: Union[str, Path, None]) -> tuple:
    """(digest, error). No path is not an error -- it is the from_dict case."""
    if path is None:
        return "", None
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            for bloco in iter(lambda: handle.read(_CHUNK), b""):
                digest.update(bloco)
    except OSError as exc:
        # Distinct from "no path": the configuration claims a file and the file
        # cannot be read. Never fatal -- losing provenance must not change a
        # verdict, the same rule audit_write_failure_message states -- but it
        # must not look like the from_dict case either.
        return "", f"{exc.__class__.__name__}: {exc}"
    return digest.hexdigest(), None


@dataclass(frozen=True)
class ConfigArtifact:
    role: str
    version: Optional[str]
    path: Optional[str]

    def to_dict(self) -> dict:
        digest, erro = file_sha256(self.path)
        entrada = {
            "role": self.role,
            "version": self.version,
            "sha256": digest,
            "path": self.path,
        }
        if erro:
            entrada["digest_error"] = erro
        return entrada


def _triplas(entradas: List[dict]) -> List[list]:
    return sorted([e["role"], e["version"] or "", e["sha256"]] for e in entradas)


def config_id(entradas: List[dict]) -> str:
    """See the recipe at the top of this module."""
    documento = {"recipe": CONFIG_ID_RECIPE, "artifacts": _triplas(entradas)}
    bruto = json.dumps(documento, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False)
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()


def build_configuration(engine) -> dict:
    """The single top-level `configuration` block of an audit record.

    Built once from the engine's flat artifact list, never per child engine --
    see the module docstring.
    """
    vistos = set()
    entradas = []
    for artefato in engine.config_artifacts():
        chave = (artefato.role, artefato.path)
        if chave in vistos:
            continue
        vistos.add(chave)
        entradas.append(artefato.to_dict())
    entradas.sort(key=lambda e: (e["role"], e["path"] or ""))
    return {
        "config_id": config_id(entradas),
        "config_id_recipe": CONFIG_ID_RECIPE,
        "artifacts": entradas,
    }
