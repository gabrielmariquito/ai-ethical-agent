"""Quais arquivos de configuração governaram uma decisão, e um id único para o
conjunto: `config_versions` diz a versão **declarada**, que é a afirmação que
o autor pode errar, e o digest diz o que foi de fato carregado: versão longa em `997a6fe^`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

# A receita `config-id/v1` escrita por extenso, não implícita no código abaixo —
# receita implícita é o que transformou três assinaturas de linha de base em
# afirmações que ninguém recomputa — versão longa em `997a6fe^`.
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
