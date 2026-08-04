"""Source-text guards on nav.js's three-state audit item.

The suite never executes JS, so this reads the module as text. Crude, and
deliberately so: it cannot check that the nav looks right, only that the
specific mistake it was fixed for cannot come back unnoticed.

That mistake: `Boolean(options.auditEnabled)` collapsed "nobody has asked the
server yet" into "the server says no". Every screen renders the nav once
before fetching /api/choices and again after, so the first render asserted
"Auditoria -- desativada" as fact, before asking. When anything went wrong in
between, it kept asserting it. An operator staring at a nav that said
"desativada" next to a startup banner that said "habilitada" had no way to
tell a real disagreement from a render that had simply not caught up.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

STATIC_JS = Path(__file__).resolve().parent.parent / "ethical_agent" / "webui" / "static" / "js"
NAV = STATIC_JS / "nav.js"
# The evaluator's tools moved under js/tools/ so one prefix gates them (see
# httphandler.GATED_ASSET_PREFIXES).
SCREENS = ("chat.js", "tools/check.js", "tools/demo.js", "tools/eval.js")


@pytest.fixture(scope="module")
def nav() -> str:
    return NAV.read_text(encoding="utf-8")


def test_undefined_is_not_coerced_into_false(nav):
    # The whole bug in one expression. Coercing is fine once undefined has
    # been ruled out -- what must never come back is coercing *first*, which
    # is what turned "not asked yet" into "the server says no".
    assignment = nav[nav.index("const auditEnabled") : nav.index("navEl.innerHTML")]
    assert "options.auditEnabled === undefined" in assignment
    assert assignment.index("=== undefined") < assignment.index("Boolean(")


def test_the_badge_is_the_claim_and_only_a_known_false_makes_it(nav):
    # "desativada" is a statement about the server. It may only be rendered
    # once the server has actually answered.
    assert "const known = enabled !== undefined;" in nav
    assert "if (item.badge && known)" in nav


def test_the_disabled_branch_still_looks_inert_in_both_unknown_and_false(nav):
    # Unknown must not become a live link to a screen that may 404 -- it is
    # the badge that waits, not the link.
    disabled = nav[nav.index("} else {") :]
    assert 'setAttribute("aria-disabled", "true")' in disabled
    assert 'setAttribute("tabindex", "-1")' in disabled


def test_every_screen_renders_the_nav_before_it_knows_and_again_after():
    # A primeira chamada renderiza o estado desconhecido e a segunda traz a
    # resposta; perder qualquer uma é como a nav volta a mentir. A primeira pode
    # trazer `sessionActive`, nunca `auditEnabled`: versão longa em `997a6fe^`.
    for name in SCREENS:
        source = (STATIC_JS / name).read_text(encoding="utf-8")
        calls = re.findall(r"renderNav\(els\.nav,[^)]*\)", source)
        assert len(calls) == 2, f"{name}: esperava 2 chamadas de renderNav, achei {len(calls)}"
        assert "auditEnabled" not in calls[0], f"{name}: a 1a chamada não pode afirmar auditEnabled"
        assert "configPanel.auditScreenEnabled" in calls[1], f"{name}: a 2a deve passar a resposta"


def test_no_screen_passes_a_default_of_false():
    # `auditEnabled: false` as a placeholder would reintroduce the exact
    # claim this is about, just spelled differently.
    for name in SCREENS:
        source = (STATIC_JS / name).read_text(encoding="utf-8")
        assert "auditEnabled: false" not in source, name


# ------------------------------------ the evaluator's items are absent, not
# ------------------------------------------------------- visibly disabled


def test_session_gated_items_are_skipped_entirely(nav):
    # An area that does not exist for this reader is not announced to them.
    # `continue` -- not the disabled branch -- is what makes the item absent
    # rather than inert-with-a-badge.
    guard = nav[nav.index("for (const item of ITEMS)") : nav.index("const li =")]
    assert "item.needsSession" in guard
    assert "continue;" in guard


def test_only_a_definite_yes_shows_them(nav):
    # Same discipline the badge follows: undefined is not a claim. Rendering
    # the tools while the answer is unknown would flash items that then
    # disappear -- worse than arriving late.
    guard = nav[nav.index("for (const item of ITEMS)") : nav.index("const li =")]
    assert "sessionActive === true" in guard
    assert "auditEnabled &&" in guard


def test_the_badge_stays_exclusive_to_auditoria(nav):
    # Quatro itens inertes seriam quatro anúncios de áreas que o leitor não
    # pode abrir; a Auditoria mantém o distintivo porque o operador precisa
    # saber que a área existe.
    items = nav[nav.index("const ITEMS = [") : nav.index("];", nav.index("const ITEMS = ["))]
    assert items.count("badge:") == 1
    assert "badge:" in [line for line in items.splitlines() if "/audit" in line][0]


def test_the_session_probe_reuses_the_existing_endpoint(nav):
    # No new endpoint and no second permission axis: /api/audit/session
    # already answers 404 / 401 / 200 for exactly the three states.
    assert '"/api/audit/session"' in nav
    probe = nav[nav.index("export async function probeSessionActive") :]
    probe = probe[: probe.index("export function renderNav")]
    assert "if (!auditEnabled) return false;" in probe, "não perguntar quando o realm está desligado"
    assert "return undefined;" in probe, "falha de rede não é uma resposta"
