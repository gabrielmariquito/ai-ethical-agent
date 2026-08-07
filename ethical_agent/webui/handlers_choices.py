from __future__ import annotations

from ethical_agent.evaluate import PAPEIS_DAS_METADES
from ethical_agent.gui_choices import (
    ENGINE_COMPARE_LABEL,
    ENGINE_COMPARE_VALUE,
    ENGINE_LABELS,
    METADE_LABELS,
    STAGE_LABELS,
    engine_value,
    metade_value,
    stage_value,
)

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
        # Só a tela de Eval: os três motores MAIS a opção de comparar, que é
        # modo de apresentação e não motor. `engines` acima continua sendo o que
        # o painel compartilhado oferece -- a tela de conversa não sabe
        # construir "comparar", e oferecê-la ali seria oferecer um erro.
        "eval_engines": [
            {"label": label, "value": engine_value(label)} for label in ENGINE_LABELS
        ] + [{"label": ENGINE_COMPARE_LABEL, "value": ENGINE_COMPARE_VALUE}],
        # As metades com o papel de cada uma, para que a marcação de "reporte"
        # na caixa de holdout venha do servidor e não de um literal em JS.
        "halves": [
            {
                "label": label,
                "value": metade_value(label),
                "papel": PAPEIS_DAS_METADES.get(metade_value(label), ""),
            }
            for label in METADE_LABELS
        ],
        # CAREFUL: this is initial_config verbatim, served unauthenticated to
        # every screen. Nothing secret may ever be put in that dict -- the
        # audit password is deliberately kept out of it, in AuditAuth (see
        # server.make_server), and a test asserts it never appears here.
        "defaults": dict(state.initial_config),
        "dataset_default": default_dataset_path(),
        # Whether the audit screen exists at all, so nav.js can render its
        # item as a link or as disabled. Reveals only that a password was
        # configured, never the password.
        "audit_screen_enabled": state.realm_enabled("audit"),
    }
