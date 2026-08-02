from __future__ import annotations

from ethical_agent.gui_choices import ENGINE_LABELS, STAGE_LABELS, engine_value, stage_value

from . import routing
from .handlers_eval import default_dataset_path


@routing.route("GET", "/api/choices")
def get_choices(state, params, body):
    """Single source of truth for the <select> label->value mapping: the
    server renders {label, value} pairs once from gui_choices (the same
    module the CLI-era GUI used), the frontend just populates <select>
    options from this -- no engine/stage literals duplicated in JS."""
    return {
        "engines": [{"label": label, "value": engine_value(label)} for label in ENGINE_LABELS],
        "stages": [{"label": label, "value": stage_value(label)} for label in STAGE_LABELS],
        "defaults": dict(state.initial_config),
        "dataset_default": default_dataset_path(),
    }
