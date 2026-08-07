"""Mapa rótulo ↔ valor dos seletores de engine/stage: os *valores* são contrato
com o resto do código e os *rótulos* são só para o usuário, traduzidos num
lugar só: versão longa em `997a6fe^`.
"""

from __future__ import annotations

from ethical_agent.types import Stage

ENGINE_LABELS = ("Rule", "KG", "Hybrid")
_ENGINE_VALUES = {"Rule": "rule", "KG": "kg", "Hybrid": "hybrid"}

STAGE_LABELS = ("Input", "Output")
_STAGE_VALUES = {"Input": Stage.INPUT.value, "Output": Stage.OUTPUT.value}

# Rodar os três e comparar é modo da tela de Eval, **não** um motor. Fica fora de
# `_ENGINE_VALUES` de propósito: se entrasse, `engine_value` deixaria de ser mapa
# puro de motor e o painel compartilhado — que a tela de conversa também usa —
# passaria a oferecer uma opção que a conversa não sabe construir.
ENGINE_COMPARE_LABEL = "Comparar as três"
ENGINE_COMPARE_VALUE = "comparar"

# As metades, com o mesmo desenho: os três valores da receita `divisao/v1` mais
# `ambas`, que é modo de apresentação (duas caixas) e não uma quarta metade.
# A correspondência com `evaluate.METADES` é fixada por teste e não por import:
# este é um módulo de rótulos, e importar `evaluate` arrastaria a cadeia inteira
# de motor e política para dentro dele.
METADE_AMBAS = "ambas"
METADE_LABELS = (
    "Inteiro",
    "Tune (ajuste)",
    "Holdout (publicável)",
    "Tune e holdout, separados",
)
_METADE_VALUES = {
    "Inteiro": "full",
    "Tune (ajuste)": "tune",
    "Holdout (publicável)": "holdout",
    "Tune e holdout, separados": METADE_AMBAS,
}


def engine_value(label: str) -> str:
    try:
        return _ENGINE_VALUES[label]
    except KeyError:
        raise ValueError(f"unknown engine label: {label!r}") from None


def engine_values() -> tuple:
    """Os valores canônicos, na ordem dos rótulos.

    É a lista que o `--engine` da CLI oferece e que `/api/eval` valida — uma
    fonte em vez das quatro cópias que existiam.
    """
    return tuple(engine_value(label) for label in ENGINE_LABELS)


def metade_value(label: str) -> str:
    try:
        return _METADE_VALUES[label]
    except KeyError:
        raise ValueError(f"unknown metade label: {label!r}") from None


def stage_value(label: str) -> str:
    try:
        return _STAGE_VALUES[label]
    except KeyError:
        raise ValueError(f"unknown stage label: {label!r}") from None
