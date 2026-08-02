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

DEFAULT_OUTPUT_REFUSAL = (
    "The generated response was withheld because it violated the ethical "
    "policy.\n{reasons}"
)

GENERIC_SYSTEM_ERROR_REASON = (
    "the request was denied as a precaution because it could not be safely "
    "evaluated (internal error); see the audit log for details"
)

LLM_FAILURE_REASON = (
    "the request was denied as a precaution because the model failed to "
    "generate a response (internal error); see the audit log for details"
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
        output_refusal_template: str = DEFAULT_OUTPUT_REFUSAL,
        source: Optional[str] = None,
    ):
        self.engine = engine
        self.llm = llm
        self.audit = audit
        self.system_prompt = system_prompt
        self.refusal_template = refusal_template
        self.output_refusal_template = output_refusal_template
        self.source = source

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
                system_error=True,
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

        safe_input = user_input
        if input_verdict.decision is Decision.REWRITE and input_verdict.rewritten_content:
            safe_input = input_verdict.rewritten_content
            trace["rewritten_input"] = safe_input

        try:
            response = self.llm.chat(
                [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": safe_input},
                ]
            )
        except Exception as exc:
            trace["llm_error"] = f"{exc.__class__.__name__}: {exc}"
            result = AgentResult(
                status="system_error",
                message=f"Request denied by the ethical guardrail.\n- {LLM_FAILURE_REASON}",
                response=None,
                input_verdict=input_verdict,
                trace=trace,
            )
            return self._finish(result)

        output_verdict = self.check(response, Stage.OUTPUT, metadata)
        trace["output_verdict"] = output_verdict.to_dict()

        if output_verdict.decision is Decision.DENY:
            # The generated content is exactly what the policy blocked: it must
            # never be retained in the result or the audit trail, in memory or
            # in code, beyond this point.
            result = AgentResult(
                status="denied",
                message=self._render(self.output_refusal_template, output_verdict),
                response=None,
                input_verdict=input_verdict,
                output_verdict=output_verdict,
                trace=trace,
            )
            return self._finish(result)

        if not output_verdict.suppresses_raw_content:
            # A redact rule's whole purpose is scrubbing its match from the
            # content; storing the pre-redaction response here would smuggle
            # the raw value back into the audit trail. Non-redacting
            # rewrites (rewrite_template) are not redactions and keep the
            # original so audits can compare original vs. rewritten.
            trace["raw_response"] = response

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
        if not reasons:
            if verdict.system_error:
                reasons.append(f"- {GENERIC_SYSTEM_ERROR_REASON}")
            elif verdict.reason:
                reasons.append(f"- {verdict.reason}")
        text = template.replace("{reasons}", "\n".join(reasons))
        notices = [m.user_message for m in verdict.matches if m.user_message]
        if notices:
            text += "\n\n" + "\n".join(dict.fromkeys(notices))
        return text

    def _finish(self, result: AgentResult) -> AgentResult:
        if self.audit is not None:
            record = {
                "status": result.status,
                "engine": self.engine.name,
                "config_versions": self.engine.describe_config(),
                **result.trace,
            }
            if self.source is not None:
                record["source"] = self.source
            self.audit.log(record)
        return result
