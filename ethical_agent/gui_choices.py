"""Label <-> value mapping for the web interface's engine/stage selectors.

The *values* are a contract with the rest of the code (they get passed to
build_engine / Stage()); the displayed *labels* are only for the user. This
module is the single place that translates one into the other, so relabeling
a selector never silently changes what the code receives.
webui/handlers_choices.py renders the {label, value} pairs from here.

Written originally for the Tkinter GUI's Combobox widgets. It has no tkinter
dependency -- which is why it outlived that GUI unchanged, and why it can be
tested without a display.
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
