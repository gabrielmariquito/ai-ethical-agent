from __future__ import annotations

import json
import re
from typing import Optional

from .engine import PolicyEngine
from .llm import LLMClient
from .policy import Policy
from .types import ActionContext, Decision, RuleMatch, Severity, Verdict

_PROMPT = """You are a strict AI ethics policy classifier.

The system enforces the following policy rules:
{rules}

Content to classify (stage: {stage}):
\"\"\"{content}\"\"\"

Instructions:
- Decide whether the content violates any rule above.
- Be strict; prefer DENY over ALLOW when unsure.
- REWRITE only when a safe reformulation preserves the user's legitimate intent.

Respond ONLY with JSON:
{{
  "decision": "ALLOW | DENY | REWRITE",
  "reason": "short explanation",
  "safe_request": "rewritten content when decision is REWRITE, else empty",
  "confidence": 0.0
}}"""

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class LLMJudgeEngine(PolicyEngine):
    name = "llm-judge"

    def __init__(self, llm: LLMClient, policy: Policy):
        self.llm = llm
        self.policy = policy

    def _rules_digest(self) -> str:
        lines = []
        for rule in self.policy.constraints + self.policy.rules:
            kind = "HARD CONSTRAINT" if rule.hard else rule.deontic
            lines.append(
                f"- [{rule.id}] ({rule.principle}, {kind}) {rule.description}"
            )
        return "\n".join(lines)

    def evaluate(self, action: ActionContext) -> Verdict:
        prompt = _PROMPT.format(
            rules=self._rules_digest(),
            stage=action.stage.value,
            content=action.content,
        )
        try:
            raw = self.llm.chat([{"role": "user", "content": prompt}])
            parsed = self._parse(raw)
        except Exception as exc:
            return self._deny(action, f"judge failure (fail closed): {exc}")

        if parsed is None:
            return self._deny(action, "unparseable judge response (fail closed)")

        decision_raw = str(parsed.get("decision", "DENY")).upper()
        reason = str(parsed.get("reason", ""))
        confidence = parsed.get("confidence")
        safe_request = parsed.get("safe_request") or None

        if decision_raw == "ALLOW":
            return Verdict(
                decision=Decision.ALLOW,
                stage=action.stage,
                engine=self.name,
                reason=f"judge: {reason} (confidence={confidence})",
            )
        if decision_raw == "REWRITE" and safe_request:
            decision = Decision.REWRITE
        else:
            decision = Decision.DENY
            safe_request = None

        match = RuleMatch(
            rule_id="LLM-JUDGE",
            principle="meta",
            deontic="judgment",
            severity=Severity.MEDIUM,
            effect=decision,
            rationale=f"{reason} (confidence={confidence})",
        )
        return Verdict(
            decision=decision,
            stage=action.stage,
            engine=self.name,
            matches=[match],
            rewritten_content=safe_request,
            reason=f"judge: {reason}",
        )

    @staticmethod
    def _parse(raw: str) -> Optional[dict]:
        block = _JSON_BLOCK.search(raw)
        if not block:
            return None
        try:
            data = json.loads(block.group(0))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _deny(self, action: ActionContext, reason: str) -> Verdict:
        return Verdict(
            decision=Decision.DENY,
            stage=action.stage,
            engine=self.name,
            reason=reason,
        )
