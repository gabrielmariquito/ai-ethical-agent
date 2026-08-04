"""Moldagem pura de registro para a tela de auditoria, cujo ponto é que uma
trilha de meses traz formas que a tela não previu e ela tem de degradar
legivelmente: `REGISTRO`, "Texto movido do código".
"""
from __future__ import annotations

import pytest

from ethical_agent.webui import audit_view
from ethical_agent.webui.dto import classify_intervention


def verdict(decision="ALLOW", stage="input", matches=None, suppressed=None, **extra):
    base = {
        "decision": decision,
        "stage": stage,
        "engine": "hybrid",
        "reason": "motivo",
        "system_error": False,
        "matches": matches or [],
        "suppressed": suppressed or [],
        "rewritten_content": None,
    }
    base.update(extra)
    return base


def match(rule_id="R-1", effect="DENY", redacted=False, matched_text="trecho", **extra):
    base = {
        "rule_id": rule_id,
        "principle": "security",
        "deontic": "prohibition",
        "severity": "high",
        "effect": effect,
        "rationale": "porque sim",
        "hard": False,
        "redacted": redacted,
        "evidence": [{"description": "keyword", "matched_text": matched_text, "span": [0, 6]}],
    }
    base.update(extra)
    return base


# --------------------------------------------------------------- record kind


def test_classify_record_kind_for_each_of_the_five_shapes():
    assert audit_view.classify_record_kind({"conversation_id": "c", "message": "m"}) == "web_chat"
    assert audit_view.classify_record_kind({"message": "m", "input": "i"}) == "cli_process"
    assert audit_view.classify_record_kind({"source": "demo", "message": "m"}) == "demo"
    # A check never calls process(), so it has no "message" key at all.
    assert audit_view.classify_record_kind({"input": "i", "input_verdict": {}}) == "check"
    assert (
        audit_view.classify_record_kind({"engine": audit_view.SYNTHETIC_ENGINE}) == "synthetic"
    )


def test_synthetic_is_recognised_before_check_because_it_also_lacks_message():
    # Ordering guard: a synthetic record has no "message" either, so if the
    # check branch ran first it would be mislabelled and would then show up
    # under a filter the auditor believes excludes fabricated data.
    record = {"engine": audit_view.SYNTHETIC_ENGINE, "config_versions": {"synthetic": True}}
    assert "message" not in record
    assert audit_view.classify_record_kind(record) == "synthetic"


def test_synthetic_engine_constant_matches_audit_tools():
    # conftest.py puts the repo root on sys.path, so the root-level script is
    # importable. The literal is duplicated (audit_tools.py is not part of
    # the package); this is what keeps the copies from drifting.
    import audit_tools

    assert audit_view.SYNTHETIC_ENGINE == audit_tools.SYNTHETIC_ENGINE
    assert audit_view.DEMO_SOURCE == audit_tools.DEMO_SOURCE


# ------------------------------------------------------------- intervention


@pytest.mark.parametrize(
    "record,expected",
    [
        ({"input_verdict": verdict("DENY")}, "blocked_input"),
        (
            {"input_verdict": verdict(), "output_verdict": verdict("DENY", "output")},
            "blocked_output",
        ),
        ({"input_verdict": verdict("REWRITE")}, "rewrite"),
        ({"input_verdict": verdict()}, "none"),
    ],
)
def test_intervention_reuses_dto_classify_intervention(record, expected):
    assert audit_view.record_intervention(record) == expected
    # Same answer as the one shared rule, by construction rather than by
    # coincidence -- dto.classify_intervention's docstring names a second
    # implementation of this as drift this project has already suffered.
    assert expected == classify_intervention(
        (record.get("input_verdict") or {}).get("decision", "ALLOW"),
        (record.get("output_verdict") or {}).get("decision"),
    )


def test_check_output_deny_without_input_verdict_classifies_as_blocked_output():
    # A check on the output stage has no input_verdict at all; defaulting the
    # missing one to ALLOW is what makes this land on blocked_output.
    record = {"output_verdict": verdict("DENY", "output")}
    assert audit_view.record_intervention(record) == "blocked_output"


def test_gravity_separates_deny_from_rewrite():
    # The whole reason gravity exists: a block and an e-mail redaction are
    # both "interventions", and a list that renders them alike tells an
    # auditor nothing about where to start.
    assert audit_view.intervention_gravity("blocked_input", False) == "deny"
    assert audit_view.intervention_gravity("blocked_output", False) == "deny"
    assert audit_view.intervention_gravity("rewrite", False) == "rewrite"
    assert audit_view.intervention_gravity("none", True) == "error"
    assert audit_view.intervention_gravity("none", False) == "none"


def test_system_error_does_not_mask_a_block():
    # A denied record that also had a system error is still, first, a block.
    assert audit_view.intervention_gravity("blocked_input", True) == "deny"


# ------------------------------------------------------------------- layers


def test_detail_handles_all_three_config_versions_shapes_plus_synthetic():
    flat_rule = {"policy_schema_version": "1.0", "policy_version": "0.2.1"}
    flat_kg = {"ontology_schema_version": "1.0", "ontology_norms_version": "0.2.0"}
    nested = {"rule-based": flat_rule, "knowledge-graph": flat_kg}

    assert audit_view.config_versions_shape(flat_rule) == "flat"
    assert audit_view.config_versions_shape(flat_kg) == "flat"
    # hybrid is the default engine, so nested is most of a real trail.
    assert audit_view.config_versions_shape(nested) == "nested"
    assert audit_view.config_versions_shape({"synthetic": True}) == "synthetic"
    assert audit_view.config_versions_shape({}) == "unknown"
    assert audit_view.config_versions_shape(None) == "unknown"

    for shape in (flat_rule, flat_kg, nested):
        detail = audit_view.detail_from_record({"config_versions": shape}, 0)
        assert detail["layer3"]["config_versions"] == shape


def test_detail_survives_unknown_llm_provenance_kind():
    # describe_llm_provenance raises ValueError on a kind it does not know.
    # That is right for a live turn and wrong for a reader of old records:
    # the screen must degrade, never 500.
    record = {"llm_provenance": {"kind": "kind-do-futuro", "model": "x"}}
    detail = audit_view.detail_from_record(record, 0)
    assert detail["layer3"]["llm_provenance_text"] is None
    # ...and the raw value is still there, so the auditor can see what it was.
    assert detail["layer3"]["llm_provenance"] == {"kind": "kind-do-futuro", "model": "x"}


def test_known_llm_provenance_kinds_still_render():
    for provenance in (
        {"kind": "mock_requested"},
        {"kind": "real", "model": "llama3.2:3b", "backend": "ollama_local"},
        {"kind": "mock_fallback", "fallback_reason": "ConnectionError: x"},
    ):
        detail = audit_view.detail_from_record({"llm_provenance": provenance}, 0)
        assert detail["layer3"]["llm_provenance_text"]


def test_unknown_record_fields_are_surfaced_not_dropped():
    # The schema has grown before (conversation_id/turn_index arrived in
    # Etapa 1) and will grow again. A reader that silently discards what it
    # was not written for is not an audit tool.
    record = {"event_id": "e", "campo_novo": {"a": 1}, "outro": "x"}
    detail = audit_view.detail_from_record(record, 0)
    assert detail["layer3"]["unknown_fields"] == {"campo_novo": {"a": 1}, "outro": "x"}


def test_known_fields_do_not_leak_into_unknown_fields():
    record = {
        "event_id": "e",
        "timestamp": "t",
        "status": "ok",
        "engine": "hybrid",
        "config_versions": {},
        "message": "m",
        "input": "i",
        "input_verdict": verdict(),
        "output_verdict": verdict(stage="output"),
        "raw_response": "r",
        "rewritten_input": "ri",
        "rewritten_output": "ro",
        "llm_error": None,
        "source": "demo",
        "llm_provenance": {"kind": "mock_requested"},
        "conversation_id": "c",
        "turn_index": 1,
    }
    detail = audit_view.detail_from_record(record, 0)
    assert detail["layer3"]["unknown_fields"] == {}


def test_layer1_handles_record_with_neither_input_nor_message():
    # Real shape: an output-stage `check`. Saying so beats a blank row the
    # auditor has to click to understand.
    record = {"event_id": "e", "output_verdict": verdict("ALLOW", "output")}
    detail = audit_view.detail_from_record(record, 0)
    assert detail["layer1"]["asked"] is None
    assert detail["layer1"]["asked_present"] is False
    assert detail["layer1"]["answered_present"] is False

    summary = audit_view.summarize_record(record, 0)
    assert summary["preview"] == ""
    assert summary["preview_field"] is None


def test_preview_falls_back_to_message_when_there_is_no_input():
    record = {"message": "resposta entregue"}
    summary = audit_view.summarize_record(record, 0)
    assert summary["preview_field"] == "message"
    assert summary["preview"] == "resposta entregue"


def test_matched_text_policy_reports_which_stage_was_redacted():
    # Tudo que sobrou deste helper; o que a tela ainda precisa é o estágio,
    # porque só reescrita de *saída* tem "texto antes da reescrita": `REGISTRO`, "Texto movido do código".
    redacted = {
        "output_verdict": verdict(
            "REWRITE",
            "output",
            matches=[match("R-PRIV-002", effect="REWRITE", redacted=True, matched_text=None)],
        )
    }
    policy = audit_view.detail_from_record(redacted, 0)["layer2"]["matched_text_policy"]
    assert policy["redacted_stages"] == ["output"]


def test_a_record_with_no_redaction_reports_no_stage():
    deny = {"input_verdict": verdict("DENY", matches=[match(effect="DENY")])}
    policy = audit_view.detail_from_record(deny, 0)["layer2"]["matched_text_policy"]
    assert policy["redacted_stages"] == []


def test_the_note_only_fields_are_gone():
    # Removing the note without removing what fed it would leave the payload
    # carrying five fields nobody reads.
    deny = {"input_verdict": verdict("DENY", matches=[match(effect="DENY")])}
    policy = audit_view.detail_from_record(deny, 0)["layer2"]["matched_text_policy"]
    assert set(policy) == {"redacted_stages"}


def test_raw_response_presence_is_reported_distinctly_from_its_value():
    # "absent from the record" and "present but null" are different claims,
    # and the screen says different things about them.
    with_raw = audit_view.detail_from_record({"raw_response": "texto"}, 0)
    assert with_raw["layer2"]["texts"]["raw_response_present"] is True
    assert with_raw["layer2"]["texts"]["raw_response"] == "texto"

    without = audit_view.detail_from_record({}, 0)
    assert without["layer2"]["texts"]["raw_response_present"] is False
    assert without["layer2"]["texts"]["raw_response"] is None


def test_layer1_never_carries_rule_ids_or_spans():
    # Layer 1's contract: judgeable without vocabulary. A rule id or a
    # character offset appearing here would defeat the gradation the whole
    # screen exists to study.
    record = {
        "input": "pedido",
        "message": "resposta",
        "input_verdict": verdict("DENY", matches=[match()]),
    }
    layer1 = audit_view.detail_from_record(record, 0)["layer1"]
    flat = repr(layer1)
    assert "R-1" not in flat
    assert "span" not in flat
    assert "evidence" not in flat
    # ...but it does say how many, so the reader knows there is more below.
    assert layer1["rule_count"] == 1
    # Nor the engine-vocabulary reason string, which is the tempting thing to
    # promote here and reads "rule-based: DENY (1 rule(s) triggered (R-1))".
    assert "reason" not in layer1


def test_layer1_says_why_in_plain_words_not_only_how_many():
    # A count is not a reason. If the nature of the concern only exists at
    # layer 2, the reader has to open layer 2 to learn the basics, which is
    # the split being in the wrong place.
    record = {
        "input": "pedido",
        "input_verdict": verdict(
            "DENY", matches=[match(principle="privacy", deontic="prohibition", hard=True)]
        ),
    }
    layer1 = audit_view.detail_from_record(record, 0)["layer1"]
    assert layer1["principles"] == ["privacy"]
    assert layer1["deontics"] == ["prohibition"]
    assert layer1["has_hard_rule"] is True
    # Still no vocabulary the reader has to have been taught.
    assert "R-1" not in repr(layer1)


def test_layer1_deduplicates_principles_and_keeps_first_seen_order():
    record = {
        "input_verdict": verdict(
            "DENY",
            matches=[
                match("R-1", principle="privacy"),
                match("R-2", principle="security"),
                match("R-3", principle="privacy"),
            ],
        )
    }
    layer1 = audit_view.detail_from_record(record, 0)["layer1"]
    assert layer1["principles"] == ["privacy", "security"]


def test_deciding_rule_count_is_narrower_than_rule_count_across_both_stages():
    # rule_count spans both verdicts but deciding_stage names one. Pairing
    # the total with a single stage word would say something false about the
    # rules that applied at the other stage.
    record = {
        "input_verdict": verdict("REWRITE", matches=[match("R-1", effect="REWRITE")]),
        "output_verdict": verdict("DENY", "output", matches=[match("R-2", effect="DENY")]),
    }
    layer1 = audit_view.detail_from_record(record, 0)["layer1"]
    assert layer1["deciding_stage"] == "output"
    assert layer1["rule_count"] == 2
    assert layer1["deciding_rule_count"] == 1


def test_deciding_stage_points_at_the_verdict_that_caused_the_intervention():
    record = {
        "input_verdict": verdict("ALLOW"),
        "output_verdict": verdict("REWRITE", "output", matches=[match(effect="REWRITE")]),
    }
    layer1 = audit_view.detail_from_record(record, 0)["layer1"]
    assert layer1["deciding_stage"] == "output"

    record = {"input_verdict": verdict("DENY", matches=[match()])}
    layer1 = audit_view.detail_from_record(record, 0)["layer1"]
    assert layer1["deciding_stage"] == "input"


def test_suppressed_matches_are_counted_for_layer1():
    record = {
        "input_verdict": verdict(
            "REWRITE",
            matches=[match(effect="REWRITE")],
            suppressed=[{"rule_id": "R-SEC-002", "reason": "exception matched", "evidence": []}],
        )
    }
    layer1 = audit_view.detail_from_record(record, 0)["layer1"]
    assert layer1["suppressed_count"] == 1


def test_raw_record_is_passed_through_verbatim():
    record = {"event_id": "e", "qualquer": "coisa"}
    detail = audit_view.detail_from_record(record, 7)
    assert detail["raw"] == record
    assert detail["offset"] == 7


# ------------------------------------------------------------------ filters


def test_parse_kinds_defaults_to_web_conversations_only():
    assert audit_view.parse_kinds(None) == ["web_chat"]
    assert audit_view.DEFAULT_KINDS == ("web_chat",)


def test_parse_kinds_all_means_no_filtering():
    assert audit_view.parse_kinds("all") is None


def test_parse_kinds_ignores_unknown_values_instead_of_erroring():
    # A hand-edited URL degrades to the safe narrow view rather than 500ing
    # in the middle of a study session.
    assert audit_view.parse_kinds("inventado") == ["web_chat"]
    assert audit_view.parse_kinds("") == ["web_chat"]
    assert audit_view.parse_kinds("demo,inventado") == ["demo"]
    assert audit_view.parse_kinds("web_chat,demo") == ["web_chat", "demo"]
