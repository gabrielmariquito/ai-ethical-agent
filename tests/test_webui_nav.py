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
SCREENS = ("chat.js", "check.js", "demo.js", "eval.js")


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
    # The first call is intentionally optionless -- that *is* the unknown
    # state. The second carries the answer. Losing either one is how the nav
    # goes back to lying: without the first there is no nav during the
    # fetch, without the second it never corrects itself.
    for name in SCREENS:
        source = (STATIC_JS / name).read_text(encoding="utf-8")
        calls = re.findall(r"renderNav\(els\.nav,[^)]*\)", source)
        assert len(calls) == 2, f"{name}: esperava 2 chamadas de renderNav, achei {len(calls)}"
        assert "auditEnabled" not in calls[0], f"{name}: a 1a chamada deve ser sem opção"
        assert "configPanel.auditScreenEnabled" in calls[1], f"{name}: a 2a deve passar a resposta"


def test_no_screen_passes_a_default_of_false():
    # `auditEnabled: false` as a placeholder would reintroduce the exact
    # claim this is about, just spelled differently.
    for name in SCREENS:
        source = (STATIC_JS / name).read_text(encoding="utf-8")
        assert "auditEnabled: false" not in source, name
