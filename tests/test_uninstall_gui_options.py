"""Toda coisa removível que o plano oferece chega a um checkbox na tela,
porque `variables.get(cand.key)` pula em silêncio o que não conhece e
`Choices` tem default `False` — a caixa que não é desenhada vira "a pessoa
não pediu" até o fim: versão longa em `997a6fe^`.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from ethical_agent.uninstall import Choices

REPO = Path(__file__).resolve().parent.parent
GUI_SOURCE = (REPO / "uninstall_gui.py").read_text(encoding="utf-8")
LIB_SOURCE = (REPO / "ethical_agent" / "uninstall.py").read_text(encoding="utf-8")


def _keys_appended_to(list_name: str) -> set[str]:
    """As chaves que `build_plan` põe em `mandatory` ou em `optional`, lidas do
    próprio fonte e não de uma execução, que só veria o subconjunto que esta
    máquina tem. Pela lista de destino e não pela posição no arquivo: um
    `mandatory.append` pode morar em qualquer ponto da função, e classificar
    por posição já deixou passar um item obrigatório escrito lá embaixo.
    """
    tree = ast.parse(LIB_SOURCE)
    build_plan = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "build_plan"
    )
    keys: set[str] = set()
    for node in ast.walk(build_plan):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (
            isinstance(func, ast.Attribute)
            and func.attr == "append"
            and isinstance(func.value, ast.Name)
            and func.value.id == list_name
        ):
            continue
        for arg in node.args:
            if not (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)):
                continue
            if arg.func.id != "Candidate":
                continue
            for kw in arg.keywords:
                if kw.arg == "key" and isinstance(kw.value, ast.Constant):
                    keys.add(kw.value.value)
    return keys


def _optional_keys_build_plan_can_emit() -> set[str]:
    keys = _keys_appended_to("optional")
    assert keys, "nenhum optional.append(Candidate(key=...)) -- build_plan mudou de forma?"
    return keys


def _gui_variables_map() -> dict[str, str]:
    """The `variables` dict OptionsPage builds: candidate key -> tk var name."""
    start = GUI_SOURCE.index("        variables = {")
    block = GUI_SOURCE[start : GUI_SOURCE.index("}", start)]
    return dict(re.findall(r'"(\w+)":\s*self\.app\.(\w+)', block))


def _mandatory_keys() -> set[str]:
    """Removed without asking, so they are deliberately absent from the
    screen's dict. Read from the source the same way, so this stays honest if
    something moves between mandatory and optional."""
    keys = _keys_appended_to("mandatory")
    assert keys, "nenhum mandatory.append(Candidate(key=...)) -- build_plan mudou de forma?"
    return keys


def test_every_optional_candidate_has_a_checkbox():
    # The one that matters. A key build_plan can offer and the screen cannot
    # draw is a removal the person is never given the chance to authorise.
    offered = _optional_keys_build_plan_can_emit() - _mandatory_keys()
    wired = set(_gui_variables_map())
    missing = sorted(offered - wired)
    assert not missing, (
        f"build_plan pode oferecer {missing}, e OptionsPage não tem variável para essas "
        f"chaves -- o `variables.get(cand.key)` devolve None e a caixa some sem aviso"
    )


def test_no_checkbox_is_wired_to_a_key_the_plan_never_offers():
    # The other direction: a var left behind after its candidate was removed
    # is a control that can never be reached, and reads as a live option to
    # anyone maintaining this.
    offered = _optional_keys_build_plan_can_emit()
    stale = sorted(set(_gui_variables_map()) - offered)
    assert not stale, f"OptionsPage tem variável para chaves que o plano não emite: {stale}"


def test_every_wired_variable_exists_on_the_app():
    for key, attr in _gui_variables_map().items():
        assert f"self.{attr} = tk.BooleanVar(" in GUI_SOURCE, (
            f"a caixa de {key!r} aponta para self.app.{attr}, que __init__ não cria"
        )


@pytest.mark.parametrize("field", [f for f in Choices.__dataclass_fields__ if f != "move_logs_to"])
def test_every_choices_flag_is_filled_from_a_variable(field):
    # Choices defaults every flag to False, which is what makes a lost
    # checkbox silent rather than loud. So each flag has to be read from a
    # variable in choices(), not left to the default.
    body = GUI_SOURCE[GUI_SOURCE.index("    def choices(self)") :]
    body = body[: body.index("\n    def ")]
    assert re.search(rf"\b{field}=self\.\w+\.get\(\)", body), (
        f"Choices.{field} não é preenchido em choices() -- fica no default False"
    )


def test_the_option_set_is_what_the_screen_and_the_plan_agree_on():
    # Stated as one sentence for whoever reads the failure: the four removals
    # the uninstaller offers today. `audit_password` saiu desta lista quando o
    # `.audit-password` virou remoção obrigatória -- ver
    # test_a_senha_da_auditoria_sai_sem_perguntar_e_sem_flag.
    assert set(_gui_variables_map()) == {
        "logs",
        "ollama",
        "model",
        "env",
    }
