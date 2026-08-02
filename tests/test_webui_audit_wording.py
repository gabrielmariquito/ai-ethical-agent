"""Source-text guards on the audit screen's pt-BR wording.

The audit screen's product *is* its text, and until now none of it was under
test: the suite never executes JS (no jsdom, no browser driver), and the only
existing references to these files assert that they are packaged and that
their static path is behind the login -- never what they say.

So these read the modules as text. That is a crude instrument and it is meant
to be: it cannot check that the wording reads well, only that the specific
structural mistakes these files were just fixed for cannot come back
unnoticed. Each assertion below corresponds to a defect that shipped.

If a rewrite makes one of these fail for a good reason, change the assertion
deliberately -- do not delete it. The failure mode being guarded is a
plausible-looking edit that quietly restores the old shape.
"""
from __future__ import annotations

from pathlib import Path

import pytest

STATIC_JS = Path(__file__).resolve().parent.parent / "ethical_agent" / "webui" / "static" / "js"
AUDIT_LAYERS = STATIC_JS / "audit" / "audit-layers.js"
VERDICT_VIEW = STATIC_JS / "verdict-view.js"


@pytest.fixture(scope="module")
def layers() -> str:
    return AUDIT_LAYERS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def verdict_view() -> str:
    return VERDICT_VIEW.read_text(encoding="utf-8")


# ------------------------------------------------- the asymmetry note is gone
#
# Five tests lived here, all about the shape of an in-screen note explaining
# why a blocked excerpt is kept and a redacted one is not. The note was
# removed from layer 2; the explanation lives in AUDIT_GUIDE.pt-BR.md, Passo
# 3. Those tests were deleted rather than adapted -- they had no object left.
# What replaces them is one guard that the note does not come back, plus the
# marking at the point of absence, which is a label and stays (see the
# verdict-view section at the bottom of this file).


def test_the_asymmetry_note_stays_removed(layers):
    for gone in (
        "asymmetryNote",
        "ASYMMETRY_CRITERION",
        "ASYMMETRY_FACES",
        "ASYMMETRY_SUMMARIES",
        "ASYMMETRY_SPAN_NOTE",
        "policy.faces",
    ):
        assert gone not in layers, gone


# --------------------------------------------- layer 1 answers why, not just
# ------------------------------------------------------------- how many


def test_layer1_renders_the_principle_before_the_count(layers):
    assert "PRINCIPLE_LABELS" in layers
    assert "A decisão foi por uma questão de" in layers
    why = layers[layers.index("// 3. Why.") :]
    principle_at = why.index("A decisão foi por uma questão de")
    count_at = why.index("normas da política se aplicaram")
    assert principle_at < count_at, "the count is answering before the concern does"


def test_layer1_uses_the_deciding_count_for_the_stage_sentence(layers):
    # rule_count spans both verdicts; deciding_stage names one. Pairing them
    # states something false about the rules that applied at the other stage.
    why = layers[layers.index("// 3. Why.") :]
    stage_sentence = why[: why.index("ea-audit-layer1__pointer")]
    assert "l1.deciding_rule_count" in stage_sentence
    assert "l1.rule_count === 1" not in stage_sentence


def test_layer1_never_renders_the_engine_reason_string(layers):
    # Verdict.reason reads "rule-based: DENY (1 rule(s) triggered (R-INJ-001))
    # | knowledge-graph: ALLOW (no rule matched)" -- engine names, English,
    # rule ids. It is the tempting field to promote and the wrong one.
    assert "l1.reason" not in layers
    assert "layer1.reason" not in layers


def test_principle_labels_cover_every_principle_the_policies_use(layers):
    repo = Path(__file__).resolve().parent.parent
    used = set()
    for directory in ("policies", "ontologies"):
        for path in (repo / directory).rglob("*"):
            if path.suffix not in {".json", ".ttl"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if '"principle"' in line:
                    used.add(line.split('"principle"')[1].strip(' :,"').strip('"'))
    start = layers.index("const PRINCIPLE_LABELS")
    block = layers[start : layers.index("};", start)]
    missing = sorted(p for p in used if p and f"{p}:" not in block)
    # The fallback returns the raw key, so a miss does not crash -- it prints
    # "non_maleficence" at layer 1, which is exactly the untranslated
    # vocabulary layer 1 exists to do without.
    assert not missing, f"principles with no pt-BR label: {missing}"


# ------------------------------------- the absence is marked where it happens


def test_redacted_evidence_says_so_instead_of_rendering_silence(verdict_view):
    # matched_text arrives null by design on a redact rule. Going straight
    # from description to span makes the rule working look like the record
    # failing, and leaves the audit note pointing at nothing on screen.
    assert "removido pela própria redação" in verdict_view
    assert "function renderEvidence(evidence, redacted)" in verdict_view
    assert "renderEvidence(match.evidence, match.redacted)" in verdict_view


# ------------------------------------------- "antes e depois" da saída
#
# WHAT THESE DO NOT GUARANTEE, stated plainly because the instrument is
# crude: they read JavaScript as text. They cannot tell you the branch
# renders, that the DOM nests correctly, that the label is visible, or that
# the wording reads well -- only that the structural decisions below are
# still in the file. A rewrite that keeps every string and breaks the render
# passes all of them.
#
# They exist anyway because of a measured gap: across 109 real records in
# logs/audit.jsonl, the "Ver o texto original" branch rendered zero times.
# It needs a record carrying BOTH rewritten_output and raw_response, i.e. an
# output-stage rewrite by template with no redact rule alongside (redaction
# is sticky -- Verdict.suppresses_raw_content -- and correctly withholds the
# raw value). Real traffic has only produced the redact case. So this is the
# one branch of the audit screen that no test and no usage exercises, and a
# break here would stay silent until someone opened the screen on a record
# that has never yet existed. test_webui_audit_view.py covers the DTO that
# feeds it; nothing covered the consumer.


@pytest.fixture(scope="module")
def before_after(layers: str) -> str:
    """Just the output-rewrite branch: `if (rewroteOutput) {` up to the
    `else if (redactedOutput)` that follows it."""
    start = layers.index("    if (rewroteOutput) {")
    return layers[start : layers.index("    } else if (redactedOutput) {", start)]


def test_the_original_is_offered_only_for_an_output_rewrite(layers):
    # raw_response is the answer to the *already rewritten* prompt, so on an
    # input rewrite it is not an "original" of anything and offering it there
    # would mislabel the evidence. The input branch must not touch it.
    start = layers.index("    if (rewroteInput) {")
    input_branch = layers[start : layers.index("    if (rewroteOutput) {", start)]
    assert "raw_response" not in input_branch


def test_the_branch_distinguishes_absent_from_present_and_null(before_after):
    # detail_from_record reports the two separately on purpose: a record
    # without the key and a record with an explicit null are different facts,
    # and only the first is the redaction case the absence note explains.
    # Gating on presence alone would render an empty quote for the second.
    assert "texts.raw_response_present && texts.raw_response !== null" in before_after


def test_both_texts_carry_their_own_label(before_after):
    # The delivered text has always had one. The original did not: with the
    # <details> open, the quote's only identification was the summary line
    # above it, which the reader has to remember having clicked.
    assert 'el("p", "ea-audit-label", "Resposta entregue à pessoa:")' in before_after
    assert 'el("p", "ea-audit-label", "Resposta original do modelo:")' in before_after


def test_the_missing_original_is_explained_rather_than_left_blank(before_after):
    # The absence is the redaction working. Saying nothing here reads as the
    # screen hiding something, which is the opposite of the claim it makes.
    assert "ea-audit-absent" in before_after
    assert "Não é esta tela que o esconde." in before_after


def test_the_label_did_not_become_a_second_note(before_after):
    # This block gets a label, not an explanation of its own. Scoped to the
    # branch: a whole-file count of a helper name is brittle enough that a
    # *comment* mentioning the helper trips it, which is exactly what happened
    # to the asymmetry test this file used to carry.
    assert before_after.count('el("details"') == 1
