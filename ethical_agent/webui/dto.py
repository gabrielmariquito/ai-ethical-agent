from __future__ import annotations

from typing import List, Optional

from ethical_agent import Decision
from ethical_agent.agent import AgentResult
from ethical_agent.llm import describe_llm_provenance

# Pure functions only: turn ethical_agent objects (Verdict, AgentResult) into
# JSON-safe dicts for the HTTP layer. Nothing here computes a guardrail
# decision -- it only reads fields that Verdict/AgentResult already expose
# (.decision, .to_dict(), .suppresses_raw_content).


def classify_intervention(input_decision: str, output_decision: Optional[str]) -> str:
    """One of the four situations the chat UI must distinguish visually,
    plus a fifth ("system_error", surfaced separately in turn_result_to_dict)
    for an LLM failure. Order matters: a DENY always wins over a REWRITE
    (matches AgentResult.status, which is "denied" in both DENY cases).

    Takes plain decision strings (Decision.value), not Verdict objects, on
    purpose: this is the one classification rule the whole webui package
    uses, for both a live turn (called from turn_result_to_dict, right below,
    off the real Verdict objects) and an archived one reconstructed from
    logs/audit.jsonl (called from archive.py, off the already-serialized
    dicts a Verdict.to_dict() call produced when the record was written --
    there's no live Verdict object to read .decision off of there). Two
    separate implementations of "what counts as an intervention" is exactly
    the kind of drift this project has been bitten by before.
    """
    if input_decision == Decision.DENY.value:
        return "blocked_input"
    if output_decision == Decision.DENY.value:
        return "blocked_output"
    if input_decision == Decision.REWRITE.value or output_decision == Decision.REWRITE.value:
        return "rewrite"
    return "none"


def _response_safe_for_display(result: AgentResult) -> Optional[str]:
    """AgentResult.response (unlike .message) is *not* suppressed by
    agent.py itself when the output was redacted -- it always holds the
    pre-redaction text whenever status != "denied", the same way the CLI's
    `process --json` exposes it (arguably useful there for whoever is
    calibrating a redact rule). The web chat's "copy record" button has no
    such audience: it's for reading a decision, not tuning a policy, so it
    must never be able to hand back the exact content a redact:true rule
    exists to hide. Applies the same test build_check_audit_record /
    GuardedAgent._finish already apply to the audit trail's raw_response, at
    one more site.
    """
    output_verdict = result.output_verdict
    if output_verdict is not None and output_verdict.suppresses_raw_content:
        return None
    return result.response


def _is_system_error(result: AgentResult) -> bool:
    output_verdict = result.output_verdict
    return (
        result.status == "system_error"
        or result.input_verdict.system_error
        or (output_verdict is not None and output_verdict.system_error)
    )


def agent_result_summary(result: AgentResult) -> dict:
    """Fields shared by every JSON view of an AgentResult -- a live chat
    turn (turn_result_to_dict, below) and a demo case (handlers_demo.py):
    status, message, both verdicts, the intervention classification, and
    whether an LLM failure happened. Each caller adds its own extra fields
    on top (turn_index/llm_provenance/response for chat; text for demo)
    instead of re-deriving this shaping a second time.
    """
    output_verdict = result.output_verdict
    return {
        "status": result.status,
        "message": result.message,
        "input_verdict": result.input_verdict.to_dict(),
        "output_verdict": output_verdict.to_dict() if output_verdict is not None else None,
        "intervention": classify_intervention(
            result.input_verdict.decision.value,
            output_verdict.decision.value if output_verdict is not None else None,
        ),
        "system_error": _is_system_error(result),
    }


_MATCH_FIELDS_FOR_CHAT = ("rule_id", "principle", "deontic", "severity", "effect", "hard")


def _verdict_without_evidence(verdict: Optional[dict]) -> Optional[dict]:
    """The chat's view of a verdict: which rule, on what grounds, how grave --
    and nothing about *how* the rule decides.

    The employee is told a rule applied, its principle, its deontic force and
    its severity. Not the excerpt that matched, not where in their text it
    matched, not the condition. Each of those is a step of a bypass: the
    excerpt names the trigger, the span narrows it, and the condition -- for a
    rule with a `not` clause -- hands over the phrase that switches the rule
    off. The evaluator's screens (Check, Demo, Eval, /audit) keep all of it,
    which is what the audit realm now separates.

    `rationale` stays: it is prose written by the policy author about why the
    norm exists, which is what someone whose message was intervened on is
    owed. `suppressed` goes entirely -- its `reason` carries the exception
    text that matched, i.e. a working bypass, already found.

    Applied here rather than in verdict-view.js because chat.js's "Copiar
    registro" serializes the whole turn object to the clipboard: hiding this
    in the renderer would leave it one Ctrl+V away. Same reason
    _response_safe_for_display sits at this layer.
    """
    if verdict is None:
        return None
    trimmed = dict(verdict)
    trimmed["matches"] = [
        {
            **{k: m.get(k) for k in _MATCH_FIELDS_FOR_CHAT},
            "rationale": m.get("rationale"),
        }
        for m in verdict.get("matches") or []
    ]
    trimmed["suppressed"] = []
    return trimmed


def turn_result_to_dict(
    result: AgentResult,
    llm_provenance: dict,
    turn_index: int,
    audit_notices: List[str],
) -> dict:
    summary = agent_result_summary(result)
    summary["input_verdict"] = _verdict_without_evidence(summary["input_verdict"])
    summary["output_verdict"] = _verdict_without_evidence(summary["output_verdict"])
    summary.update(
        {
            "response": _response_safe_for_display(result),
            "llm_provenance": llm_provenance,
            "llm_provenance_text": describe_llm_provenance(llm_provenance),
            "turn_index": turn_index,
            "audit_notices": audit_notices,
        }
    )
    return summary
