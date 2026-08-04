import pytest

from ethical_agent.gui_choices import (
    ENGINE_LABELS,
    STAGE_LABELS,
    engine_value,
    stage_value,
)
from ethical_agent.types import Stage


@pytest.mark.parametrize(
    "label, expected",
    [("Rule", "rule"), ("KG", "kg"), ("Hybrid", "hybrid")],
)
def test_engine_value_maps_display_label_to_canonical_value(label, expected):
    assert engine_value(label) == expected


@pytest.mark.parametrize(
    "label, expected",
    [("Input", Stage.INPUT.value), ("Output", Stage.OUTPUT.value)],
)
def test_stage_value_maps_display_label_to_stage_enum_value(label, expected):
    value = stage_value(label)
    assert value == expected
    assert Stage(value) is (Stage.INPUT if label == "Input" else Stage.OUTPUT)


def test_engine_value_covers_every_declared_label():
    for label in ENGINE_LABELS:
        assert engine_value(label)


def test_stage_value_covers_every_declared_label():
    for label in STAGE_LABELS:
        assert stage_value(label)


def test_engine_value_rejects_unknown_label():
    with pytest.raises(ValueError):
        engine_value("rule")  # canonical value, not the display label


def test_stage_value_rejects_unknown_label():
    with pytest.raises(ValueError):
        stage_value("input")  # canonical value, not the display label
