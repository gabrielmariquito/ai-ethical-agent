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
    """Uma das quatro situações que a interface tem de distinguir visualmente,
    mais uma quinta para falha de LLM; a ordem importa, e DENY vence REWRITE: `REGISTRO`, "Texto movido do código".
    """
    if input_decision == Decision.DENY.value:
        return "blocked_input"
    if output_decision == Decision.DENY.value:
        return "blocked_output"
    if input_decision == Decision.REWRITE.value or output_decision == Decision.REWRITE.value:
        return "rewrite"
    return "none"


def _response_safe_for_display(result: AgentResult) -> Optional[str]:
    """`AgentResult.response` não é suprimido por `agent.py` quando a saída foi
    redigida, então é anulado aqui sempre que o veredito suprime conteúdo
    bruto — espelhando a regra que a trilha já aplica: `REGISTRO`, "Texto movido do código".
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
    """Campos comuns a toda visão JSON de um `AgentResult`, com cada chamador
    acrescentando os seus.
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
    """A visão do chat sobre um veredito: qual regra, com que fundamento e quão
    grave — e nada sobre *como* a regra decide, porque cada um desses campos
    é um passo de um bypass: `REGISTRO`, "Texto movido do código".
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
