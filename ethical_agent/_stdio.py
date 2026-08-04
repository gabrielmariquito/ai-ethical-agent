"""Faz `stdout`/`stderr` conseguirem imprimir qualquer caractere Unicode, em
código, porque sob cp1252 um `print` fora da página levanta
`UnicodeEncodeError`: `REGISTRO`, "Texto movido do código".
"""
from __future__ import annotations

import sys


def ensure_utf8_stdio() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except Exception:
            pass
