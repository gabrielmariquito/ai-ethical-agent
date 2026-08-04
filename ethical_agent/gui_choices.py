"""Mapa rótulo ↔ valor dos seletores de engine/stage: os *valores* são contrato
com o resto do código e os *rótulos* são só para o usuário, traduzidos num
lugar só: `REGISTRO`, "Texto movido do código".
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
