"""Makes stdout/stderr able to print any Unicode character, in-code.

On Windows, when `PYTHONUTF8` isn't set, `sys.stdout`/`sys.stderr` default to
the process locale's codepage (cp1252), which cannot encode most of Unicode --
`print()`ing a character outside it raises `UnicodeEncodeError` and, for a
single `print()` of a whole payload (e.g. `eval --json`), aborts before
anything is written. Reconfiguring here means every entry point works
correctly by default, without depending on the user (or their shell profile)
knowing to set `PYTHONUTF8=1` first.
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
