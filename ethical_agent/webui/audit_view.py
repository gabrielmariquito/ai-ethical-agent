from __future__ import annotations

from typing import Any, Dict, List, Optional

from ethical_agent.llm import describe_llm_provenance

from .dto import classify_intervention

# Molda um registro já escrito para a tela — puro, sem I/O e sem recomputar
# veredito —, com a estratificação em três camadas como ponto da tela e a
# redação pt-BR no frontend: versão longa em `997a6fe^`.
SYNTHETIC_ENGINE = "SYNTHETIC-SAMPLE-DATA"
DEMO_SOURCE = "demo"

KIND_WEB_CHAT = "web_chat"
KIND_CLI_PROCESS = "cli_process"
KIND_DEMO = "demo"
KIND_CHECK = "check"
KIND_SYNTHETIC = "synthetic"

RECORD_KINDS = (KIND_WEB_CHAT, KIND_CLI_PROCESS, KIND_DEMO, KIND_CHECK, KIND_SYNTHETIC)

# A visão padrão é deliberadamente estreita, e o custo do filtro fica sempre na
# tela — filtro de custo invisível é filtro que engana: versão longa em `997a6fe^`.
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

# Toda chave que esta tela sabe posicionar; o resto sai verbatim em
# `unknown_fields` da camada 3 em vez de ser descartado — leitor de registro
# histórico que descarta em silêncio não é ferramenta de auditoria: versão longa em `997a6fe^`.
KNOWN_RECORD_KEYS = frozenset(
    {
        "event_id",
        "timestamp",
        "status",
        "engine",
        "config_versions",
        "configuration",
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
    """Qual atividade produziu este registro, distinguível só por presença
    porque é tudo que o escritor deixou — e a ordem importa, porque o
    sintético também não tem "message": versão longa em `997a6fe^`.
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
    """Onde neste registro uma regra `redact` limpou o próprio `matched_text`;
    `redacted_stages` fica porque a camada 2 precisa saber em que estágio a
    redação ocorreu antes de oferecer um antes/depois: versão longa em `997a6fe^`.
    """
    redacted_stages: List[str] = []

    for key, stage in (("input_verdict", "input"), ("output_verdict", "output")):
        verdict = record.get(key)
        if not isinstance(verdict, dict):
            continue
        for match in verdict.get("matches") or []:
            if match.get("redacted") and stage not in redacted_stages:
                redacted_stages.append(stage)

    return {"redacted_stages": redacted_stages}


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

    # O que a camada 1 pode dizer sobre o *porquê*: contagem não é razão, e a
    # natureza da preocupação tem de sobreviver aqui ou o corte está no lugar
    # errado — versão longa em `997a6fe^`.
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

    configuration = record.get("configuration")
    config_id = configuration.get("config_id") if isinstance(configuration, dict) else None

    layer3 = {
        "event_id": record.get("event_id"),
        "engine": record.get("engine"),
        "config_versions": record.get("config_versions"),
        "config_versions_shape": config_versions_shape(record.get("config_versions")),
        # Which files governed the decision, and one id for the set. Absent on
        # every record written before this existed, and on audit_tools.py's
        # synthetic samples -- the screen says "registro anterior à
        # procedência" there instead of leaving a hole, the same way it does
        # for a structurally absent raw_response.
        "configuration": configuration if isinstance(configuration, dict) else None,
        "config_id": config_id,
        # The auditor's actual question is "were these two records decided
        # under the same rules?", and that is answered by comparing ids by
        # eye. 64 hex characters are not comparable by eye; 12 are, and the
        # full value stays one line below for anyone who needs it.
        "config_id_short": config_id[:12] if isinstance(config_id, str) else None,
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
