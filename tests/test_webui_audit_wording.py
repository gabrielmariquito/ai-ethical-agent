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


# ------------------------------------------------- the asymmetry is one note


def test_the_asymmetry_is_built_as_a_single_note(layers):
    # It used to be two <details> gated on two independent flags. Collapsed --
    # which is how they start -- "Por que o trecho bloqueado aparece aqui?"
    # sitting next to "Por que este trecho não aparece?" is a contradiction
    # with no visible resolution, and an auditor reports that as a bug.
    assert layers.count("function asymmetryNote(") == 1
    assert layers.count("asymmetryNote(") == 2  # the definition and one call
    assert "ASYMMETRY_DENY" not in layers
    assert "ASYMMETRY_REDACTED" not in layers


def test_the_note_is_gated_on_faces_not_on_two_independent_flags(layers):
    assert "const faces = policy.faces || [];" in layers
    assert "if (faces.length > 0) {" in layers
    # The old gates, either of which could fire without the other.
    assert "deny_rule_ids_with_text && policy.deny_rule_ids_with_text.length" not in layers
    assert "if (policy.any_redacted_rule) {" not in layers


def test_every_summary_names_both_faces_or_the_criterion(layers):
    # The summary is the only line guaranteed to be read: <details> starts
    # closed. A summary that states just one face leaves the criterion unsaid
    # for any record that only shows that face.
    start = layers.index("const ASYMMETRY_SUMMARIES")
    block = layers[start : layers.index("};", start)]
    lines = [line for line in block.splitlines() if line.strip().startswith(("deny", "redact", "both"))]
    assert len(lines) == 3, "expected exactly the three summary variants"
    for line in lines:
        assert "—" in line, f"summary states one face with no counterpart: {line.strip()}"


def test_the_criterion_is_stated_as_one_rule(layers):
    # Sliced to the next declaration, not to the next ";" -- the prose itself
    # contains semicolons.
    start = layers.index("const ASYMMETRY_CRITERION")
    criterion = layers[start : layers.index("const ASYMMETRY_FACES", start)]
    assert "motivo da intervenção" in criterion
    assert "mesma regra" in criterion


def test_the_note_no_longer_depends_on_render_order(layers):
    # The old redacted body said "logo acima", true only because the other
    # note happened to be appended first -- a layout coupling with no test.
    assert "logo acima" not in layers


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
