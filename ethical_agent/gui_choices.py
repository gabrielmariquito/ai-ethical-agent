"""Label <-> value mapping for gui_app.py's Combobox widgets.

Combobox *values* are a contract with the rest of the code (they get passed
to build_engine / Stage()); the displayed *labels* are just for the user.
This module is the single place that translates one into the other, so
relabeling a combo in gui_app.py never silently changes what the code
receives. It has no tkinter dependency so it can be tested without a display.
"""

from __future__ import annotations

from ethical_agent.types import Stage

ENGINE_LABELS = ("Rule", "KG", "Hybrid")
_ENGINE_VALUES = {"Rule": "rule", "KG": "kg", "Hybrid": "hybrid"}

STAGE_LABELS = ("Input", "Output")
_STAGE_VALUES = {"Input": Stage.INPUT.value, "Output": Stage.OUTPUT.value}


def engine_value(label: str) -> str:
    try:
        return _ENGINE_VALUES[label]
    except KeyError:
        raise ValueError(f"unknown engine label: {label!r}") from None


def stage_value(label: str) -> str:
    try:
        return _STAGE_VALUES[label]
    except KeyError:
        raise ValueError(f"unknown stage label: {label!r}") from None
