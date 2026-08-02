from __future__ import annotations

from typing import Any, Dict, List, Optional

from ethical_agent.llm import describe_llm_provenance

from .dto import classify_intervention

# Shapes an already-written audit record for the audit screen. Pure: no I/O,
# no verdict recomputation, no re-evaluation of content. Everything here
# *reads* fields that were decided and serialized when the record was
# written; if a number looks wrong on screen, the bug is upstream in
# agent.py/engine.py, not here.
#
# The layering is the point of the screen, and therefore of this module.
# Showing an auditor all of a record at once drowns them; showing too little
# stops them judging. So:
#
#   layer 1  what happened          -- always visible, plain language, built
#                                      only from fields whose meaning needs
#                                      no vocabulary (the text asked, the
#                                      text delivered, status, counts)
#   layer 2  the claim and its proof -- rule_id, rationale, evidence with
#                                      matched text and position, suppressed
#                                      exceptions, original vs rewritten
#   layer 3  what produced the claim -- engine, config versions, model
#                                      provenance, position in a conversation
#
# Note what this module does NOT do: it never hides content. Blocked output
# and pre-redaction values are absent from the record itself, by a retention
# decision taken in earlier rounds (agent.py:136-161). If either ever shows
# up here, that is a retention bug upstream, not a presentation bug to patch
# with a filter.
#
# The pt-BR wording lives in the frontend (static/js/audit/audit-layers.js),
# the way verdict-view.js already renders labels for dto.classify_intervention's
# neutral strings. This module returns structure; the screen names it.

# Mirrors audit_tools.py's synthetic marker. Duplicated rather than imported
# because audit_tools.py is a root-level script, not part of the package --
# a test asserts the two literals still agree.
SYNTHETIC_ENGINE = "SYNTHETIC-SAMPLE-DATA"
DEMO_SOURCE = "demo"

KIND_WEB_CHAT = "web_chat"
KIND_CLI_PROCESS = "cli_process"
KIND_DEMO = "demo"
KIND_CHECK = "check"
KIND_SYNTHETIC = "synthetic"

RECORD_KINDS = (KIND_WEB_CHAT, KIND_CLI_PROCESS, KIND_DEMO, KIND_CHECK, KIND_SYNTHETIC)

# The default view is deliberately narrow: only real conversations held
# through the web chat. A study session's time is the scarcest resource in
# this whole design, and a trail with months of demo/check/dev runs in it
# spends that time on noise. Every other kind stays one click away behind
# "mostrar tudo", and the count of what the filter is hiding is always on
# screen -- a filter whose cost is invisible is a filter that misleads.
DEFAULT_KINDS = (KIND_WEB_CHAT,)

# Per-request scan budget for one page of the list. Deliberately NOT
# archive.MAX_SCAN_LINES: that one is a single-shot cap for the chat sidebar
# ("give up and show what you have"), whereas this is a page size for a
# reader that can and does continue from a cursor. Reusing it would have
# silently coupled two unrelated policies.
AUDIT_PAGE_SCAN_LIMIT = 5_000
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200

PREVIEW_CHARS = 160

# Every record key this screen knows how to place in a layer. Anything else
# a record carries is surfaced verbatim in layer 3 under "unknown_fields"
# rather than dropped -- a reader of historical records that silently
# discards fields it was not written for is not an audit tool. The schema
# has grown before (conversation_id/turn_index arrived in Etapa 1) and will
# grow again.
KNOWN_RECORD_KEYS = frozenset(
    {
        "event_id",
        "timestamp",
        "status",
        "engine",
        "config_versions",
        "message",
        "input",
        "input_verdict",
        "output_verdict",
        "raw_response",
        "rewritten_input",
        "rewritten_output",
        "llm_error",
        "source",
        "llm_provenance",
        "conversation_id",
        "turn_index",
    }
)


def classify_record_kind(record: dict) -> str:
    """Which activity produced this record. Distinguishable by presence
    alone, because that is all the writer left behind:

      engine == SYNTHETIC-SAMPLE-DATA -> audit_tools.py gerar
      source == "demo"                -> a demo run
      has conversation_id             -> a web chat turn
      has no "message" key            -> a `check` (never calls process())
      otherwise                       -> the CLI's single-turn `process`

    Order matters: a synthetic record also has no "message", so it has to be
    recognised before the check branch or it would be mislabelled.
    """
    if record.get("engine") == SYNTHETIC_ENGINE:
        return KIND_SYNTHETIC
    if record.get("source") == DEMO_SOURCE:
        return KIND_DEMO
    if "conversation_id" in record:
        return KIND_WEB_CHAT
    if "message" not in record:
        return KIND_CHECK
    return KIND_CLI_PROCESS


def record_intervention(record: dict) -> str:
    """Delegates to dto.classify_intervention, which takes plain decision
    strings precisely so it can be applied to a serialized record. Its
    docstring names re-implementing this rule as a drift this project has
    already been bitten by; this is the third caller and still the one rule.
    """
    input_verdict = record.get("input_verdict") or {}
    output_verdict = record.get("output_verdict")
    return classify_intervention(
        input_verdict.get("decision", "ALLOW"),
        (output_verdict or {}).get("decision") if output_verdict else None,
    )


def is_system_error(record: dict) -> bool:
    if record.get("status") == "system_error":
        return True
    for key in ("input_verdict", "output_verdict"):
        verdict = record.get(key)
        if isinstance(verdict, dict) and verdict.get("system_error"):
            return True
    return False


def intervention_gravity(intervention: str, system_error: bool) -> str:
    """A block and an e-mail redaction are both "interventions", and reading
    a list where they look alike tells an auditor nothing about where to
    start. This is the axis the list styles on -- see app-level CSS, which
    also varies weight and label, never hue alone.
    """
    if intervention in ("blocked_input", "blocked_output"):
        return "deny"
    if intervention == "rewrite":
        return "rewrite"
    if system_error:
        return "error"
    return "none"


def safe_provenance_text(provenance: Optional[dict]) -> Optional[str]:
    """describe_llm_provenance raises ValueError on a kind it does not know.
    That is right for a live turn (the value was just built) and wrong for a
    reader of months-old records: an unrecognised kind must degrade to "no
    rendered text", never take the screen down with a 500."""
    if not isinstance(provenance, dict):
        return None
    try:
        return describe_llm_provenance(provenance)
    except (ValueError, KeyError, TypeError):
        return None


def config_versions_shape(config_versions: Any) -> str:
    """config_versions has three real shapes plus a synthetic one, depending
    on which engine wrote the record (PolicyEngine.describe_config): flat for
    rule-based, flat for knowledge-graph, and nested-by-child-engine for
    hybrid/composite, which is the default engine and therefore most of the
    trail. The screen has to render all of them."""
    if not isinstance(config_versions, dict) or not config_versions:
        return "unknown"
    if config_versions.get("synthetic") is True:
        return "synthetic"
    if any(isinstance(value, dict) for value in config_versions.values()):
        return "nested"
    return "flat"


def _rule_ids(record: dict) -> List[str]:
    ids: List[str] = []
    for key in ("input_verdict", "output_verdict"):
        verdict = record.get(key)
        if not isinstance(verdict, dict):
            continue
        for match in verdict.get("matches") or []:
            rule_id = match.get("rule_id")
            if rule_id and rule_id not in ids:
                ids.append(rule_id)
    return ids


def _deciding_verdict(record: dict, intervention: str):
    """Which of the two verdicts is the one the auditor is being asked to
    judge. Returns (stage_name, verdict_dict) or (None, None)."""
    input_verdict = record.get("input_verdict")
    output_verdict = record.get("output_verdict")
    if intervention == "blocked_input":
        return "input", input_verdict
    if intervention == "blocked_output":
        return "output", output_verdict
    if intervention == "rewrite":
        for stage, verdict in (("input", input_verdict), ("output", output_verdict)):
            if isinstance(verdict, dict) and verdict.get("decision") == "REWRITE":
                return stage, verdict
    if isinstance(output_verdict, dict):
        return "output", output_verdict
    if isinstance(input_verdict, dict):
        return "input", input_verdict
    return None, None


def summarize_record(record: dict, offset: int) -> dict:
    """One row of the list."""
    intervention = record_intervention(record)
    system_error = is_system_error(record)

    # A `check` on the output stage has neither input nor message. Saying so
    # beats rendering a blank row the auditor has to click to understand.
    preview_field = None
    preview_source = ""
    if record.get("input"):
        preview_field, preview_source = "input", record["input"]
    elif record.get("message"):
        preview_field, preview_source = "message", record["message"]

    return {
        "event_id": record.get("event_id"),
        "offset": offset,
        "timestamp": record.get("timestamp"),
        "kind": classify_record_kind(record),
        "status": record.get("status"),
        "engine": record.get("engine"),
        "intervention": intervention,
        "gravity": intervention_gravity(intervention, system_error),
        "system_error": system_error,
        "conversation_id": record.get("conversation_id"),
        "turn_index": record.get("turn_index"),
        "rule_ids": _rule_ids(record),
        "preview": preview_source[:PREVIEW_CHARS],
        "preview_field": preview_field,
    }


def _matched_text_policy(record: dict) -> dict:
    """Drives the in-screen explanation of a deliberate asymmetry, described
    at the point the auditor meets it rather than in a manual.

    evidence[].matched_text on a DENY constraint DOES carry the excerpt of
    the blocked content, on purpose: without seeing what was blocked, an
    auditor cannot judge whether blocking it was right, which is the entire
    task. Rules with redact=true still scrub their own matched_text
    (Evidence.without_matched_text, applied in engine.py), because such a
    rule exists precisely to remove that value. Presented side by side with
    no explanation the pair reads as an inconsistency; it is one policy.

    `faces` is what the screen renders from: the *one* note it draws, and
    which of the policy's two faces this particular record shows. Two
    independent flags invited two independent notes, and two notes are
    exactly the misreading -- an auditor scanning collapsed headings sees
    "the excerpt is kept" next to "the excerpt is removed" and files a bug.
    One list, one note, criterion stated first.
    """
    any_with_text = False
    any_redacted = False
    redacted_rule_ids: List[str] = []
    deny_rule_ids_with_text: List[str] = []
    # Which stage the redaction happened at. The screen needs this to say the
    # right thing about raw_response: it is only ever "the text before the
    # rewrite" when the *output* was the thing rewritten.
    redacted_stages: List[str] = []

    for key, stage in (("input_verdict", "input"), ("output_verdict", "output")):
        verdict = record.get(key)
        if not isinstance(verdict, dict):
            continue
        for match in verdict.get("matches") or []:
            has_text = any(
                (ev or {}).get("matched_text") for ev in (match.get("evidence") or [])
            )
            if has_text:
                any_with_text = True
                if match.get("effect") == "DENY" and match.get("rule_id"):
                    deny_rule_ids_with_text.append(match["rule_id"])
            if match.get("redacted"):
                any_redacted = True
                if stage not in redacted_stages:
                    redacted_stages.append(stage)
                if match.get("rule_id"):
                    redacted_rule_ids.append(match["rule_id"])

    # Order is the reading order of the note, not an accident: the kept
    # excerpt is the case the auditor can see, so it is named before the one
    # they cannot.
    faces: List[str] = []
    if deny_rule_ids_with_text:
        faces.append("deny_keeps")
    if any_redacted:
        faces.append("redact_removes")

    return {
        "any_evidence_with_text": any_with_text,
        "any_redacted_rule": any_redacted,
        "redacted_rule_ids": redacted_rule_ids,
        "redacted_stages": redacted_stages,
        "deny_rule_ids_with_text": deny_rule_ids_with_text,
        "faces": faces,
    }


def detail_from_record(record: dict, offset: int) -> dict:
    intervention = record_intervention(record)
    system_error = is_system_error(record)
    deciding_stage, deciding_verdict = _deciding_verdict(record, intervention)
    deciding = deciding_verdict if isinstance(deciding_verdict, dict) else {}

    rule_count = 0
    suppressed_count = 0
    for key in ("input_verdict", "output_verdict"):
        verdict = record.get(key)
        if isinstance(verdict, dict):
            rule_count += len(verdict.get("matches") or [])
            suppressed_count += len(verdict.get("suppressed") or [])

    llm_provenance = record.get("llm_provenance")

    # What layer 1 is allowed to say about *why*. A count is not a reason:
    # "one rule applied" tells the reader how many and when, then sends them
    # to layer 2 for the thing they actually came for. The nature of the
    # concern has to survive at layer 1 or the split is in the wrong place.
    #
    # Note what is deliberately NOT promoted here. Verdict.reason reads
    # "rule-based: DENY (1 rule(s) triggered (R-INJ-001)) | knowledge-graph:
    # ALLOW (no rule matched)" -- engine names, English, rule ids, i.e. every
    # kind of vocabulary layer 1 exists to do without. match.rationale is a
    # real sentence but also English, and carries appended RelAIEO
    # provocations. principle and deontic are short closed vocabularies, so
    # they translate the way gravity and kind already do.
    principles: List[str] = []
    deontics: List[str] = []
    has_hard_rule = False
    deciding_matches = deciding.get("matches") or []
    for match in deciding_matches:
        principle = match.get("principle")
        if principle and principle not in principles:
            principles.append(principle)
        deontic = match.get("deontic")
        if deontic and deontic not in deontics:
            deontics.append(deontic)
        if match.get("hard"):
            has_hard_rule = True

    layer1 = {
        "timestamp": record.get("timestamp"),
        "status": record.get("status"),
        "intervention": intervention,
        "gravity": intervention_gravity(intervention, system_error),
        "system_error": system_error,
        "deciding_stage": deciding_stage,
        "asked": record.get("input"),
        "asked_present": "input" in record,
        "answered": record.get("message"),
        "answered_present": "message" in record,
        "principles": principles,
        "deontics": deontics,
        "has_hard_rule": has_hard_rule,
        "rule_count": rule_count,
        # rule_count spans both verdicts; deciding_stage names one. Saying
        # "2 rules applied before the model was called" when one of them
        # applied after would be a plain falsehood, so the stage sentence is
        # built from this narrower count instead.
        "deciding_rule_count": len(deciding_matches),
        "suppressed_count": suppressed_count,
        "rewritten_input_present": "rewritten_input" in record,
        "rewritten_output_present": "rewritten_output" in record,
    }

    layer2 = {
        "input_verdict": record.get("input_verdict"),
        "output_verdict": record.get("output_verdict"),
        "texts": {
            # Present only when the record retained it. On a redaction
            # rewrite it is structurally absent (Verdict.suppresses_raw_content
            # kept it out at write time), and the screen says so in that spot
            # instead of leaving a silent hole.
            "raw_response": record.get("raw_response"),
            "raw_response_present": "raw_response" in record,
            "rewritten_input": record.get("rewritten_input"),
            "rewritten_output": record.get("rewritten_output"),
        },
        "matched_text_policy": _matched_text_policy(record),
    }

    layer3 = {
        "event_id": record.get("event_id"),
        "engine": record.get("engine"),
        "config_versions": record.get("config_versions"),
        "config_versions_shape": config_versions_shape(record.get("config_versions")),
        "llm_provenance": llm_provenance,
        "llm_provenance_text": safe_provenance_text(llm_provenance),
        "conversation_id": record.get("conversation_id"),
        "turn_index": record.get("turn_index"),
        "llm_error": record.get("llm_error"),
        "source": record.get("source"),
        "unknown_fields": {
            key: value for key, value in record.items() if key not in KNOWN_RECORD_KEYS
        },
    }

    return {
        "event_id": record.get("event_id"),
        "offset": offset,
        "kind": classify_record_kind(record),
        "layer1": layer1,
        "layer2": layer2,
        "layer3": layer3,
        # The record verbatim. An artifact whose subject is transparency
        # that hid its own substrate would undercut its own claim; the chat
        # already offers the same thing through "Copiar registro".
        "raw": record,
    }


def parse_kinds(raw: Optional[str]) -> Optional[List[str]]:
    """Query-param parsing for ?kinds=. "all" means no filtering (None);
    a comma-separated list is filtered to known kinds; anything empty or
    unrecognised falls back to the default view rather than erroring, so a
    hand-edited URL degrades to the safe narrow list."""
    if raw is None:
        return list(DEFAULT_KINDS)
    value = raw.strip().lower()
    if value == "all":
        return None
    wanted = [k for k in (part.strip() for part in value.split(",")) if k in RECORD_KINDS]
    return wanted or list(DEFAULT_KINDS)
