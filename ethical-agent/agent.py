from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .audit import AuditLogger
from .engine import PolicyEngine
from .llm import LLMClient
from .types import ActionContext, Decision, Stage, Verdict

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant operating behind an ethical guardrail. "
    "Answer helpfully and honestly within safety constraints."
)

DEFAULT_REFUSAL = (
    "Request denied by the ethical guardrail.\n{reasons}"
)

DEFAULT_ESCALATION = (
    "This request was withheld and flagged for human review by the ethical "
    "guardrail.\n{reasons}"
)

DEFAULT_OUTPUT_REFUSAL = (
    "The generated response was withheld because it violated the ethical "
    "policy.\n{reasons}"
)


@dataclass
class AgentResult:
    status: str
    message: str
    response: Optional[str]
    input_verdict: Verdict
    output_verdict: Optional[Verdict] = None
    trace: dict = field(default_factory=dict)


class GuardedAgent:
    def __init__(
        self,
        engine: PolicyEngine,
        llm: Optional[LLMClient] = None,
        audit: Optional[AuditLogger] = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        refusal_template: str = DEFAULT_REFUSAL,
        escalation_template: str = DEFAULT_ESCALATION,
        output_refusal_template: str = DEFAULT_OUTPUT_REFUSAL,
    ):
        self.engine = engine
        self.llm = llm
        self.audit = audit
        self.system_prompt = system_prompt
        self.refusal_template = refusal_template
        self.escalation_template = escalation_template
        self.output_refusal_template = output_refusal_template

    def check(
        self,
        content: str,
        stage: Stage = Stage.INPUT,
        metadata: Optional[dict] = None,
    ) -> Verdict:
        action = ActionContext(content=content, stage=stage, metadata=metadata or {})
        try:
            return self.engine.evaluate(action)
        except Exception as exc:
            return Verdict(
                decision=Decision.DENY,
                stage=stage,
                engine=self.engine.name,
                reason=f"engine error (fail closed): {exc}",
            )

    def process(self, user_input: str, metadata: Optional[dict] = None) -> AgentResult:
        if self.llm is None:
            raise RuntimeError(
                "GuardedAgent.process requires an LLMClient; "
                "use check() for guardrail-only evaluation"
            )

        trace: dict = {"input": user_input}

        input_verdict = self.check(user_input, Stage.INPUT, metadata)
        trace["input_verdict"] = input_verdict.to_dict()

        if input_verdict.decision is Decision.DENY:
            result = AgentResult(
                status="denied",
                message=self._render(self.refusal_template, input_verdict),
                response=None,
                input_verdict=input_verdict,
                trace=trace,
            )
            return self._finish(result)

        if input_verdict.decision is Decision.ESCALATE:
            result = AgentResult(
                status="escalated",
                message=self._render(self.escalation_template, input_verdict),
                response=None,
                input_verdict=input_verdict,
                trace=trace,
            )
            return self._finish(result)

        safe_input = user_input
        if input_verdict.decision is Decision.REWRITE and input_verdict.rewritten_content:
            safe_input = input_verdict.rewritten_content
            trace["rewritten_input"] = safe_input

        response = self.llm.chat(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": safe_input},
            ]
        )
        trace["raw_response"] = response

        output_verdict = self.check(response, Stage.OUTPUT, metadata)
        trace["output_verdict"] = output_verdict.to_dict()

        if output_verdict.decision in (Decision.DENY, Decision.ESCALATE):
            result = AgentResult(
                status="denied",
                message=self._render(self.output_refusal_template, output_verdict),
                response=response,
                input_verdict=input_verdict,
                output_verdict=output_verdict,
                trace=trace,
            )
            return self._finish(result)

        final = response
        if output_verdict.decision is Decision.REWRITE and output_verdict.rewritten_content:
            final = output_verdict.rewritten_content
            trace["rewritten_output"] = final

        result = AgentResult(
            status="ok",
            message=final,
            response=response,
            input_verdict=input_verdict,
            output_verdict=output_verdict,
            trace=trace,
        )
        return self._finish(result)

    @staticmethod
    def _render(template: str, verdict: Verdict) -> str:
        reasons = []
        for match in verdict.matches:
            reasons.append(
                f"- [{match.rule_id}] {match.principle}: "
                f"{match.rationale or match.effect.value}"
            )
        if not reasons and verdict.reason:
            reasons.append(f"- {verdict.reason}")
        text = template.replace("{reasons}", "\n".join(reasons))
        notices = [m.user_message for m in verdict.matches if m.user_message]
        if notices:
            text += "\n\n" + "\n".join(dict.fromkeys(notices))
        return text

    def _finish(self, result: AgentResult) -> AgentResult:
        if self.audit is not None:
            self.audit.log(
                {
                    "status": result.status,
                    "engine": self.engine.name,
                    **result.trace,
                }
            )
        return result
