from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Sequence, Tuple

from .policy import Policy, Rule
from .types import (
    ActionContext,
    Decision,
    Evidence,
    RuleMatch,
    SuppressedMatch,
    Verdict,
)


class PolicyEngine(ABC):
    name: str = "abstract"

    @abstractmethod
    def evaluate(self, action: ActionContext) -> Verdict:
        ...


class RuleBasedEngine(PolicyEngine):
    name = "rule-based"

    def __init__(self, policy: Policy):
        self.policy = policy

    def evaluate(self, action: ActionContext) -> Verdict:
        fired: List[Tuple[Rule, List[Evidence]]] = []
        suppressed: List[SuppressedMatch] = []

        for rule in self.policy.rules_for(action.stage):
            evidence = rule.condition.evaluate(action.content)
            if not evidence:
                continue
            if rule.exceptions is not None and not rule.hard:
                exception_evidence = rule.exceptions.evaluate(action.content)
                if exception_evidence:
                    reasons = ", ".join(
                        e.matched_text or e.description for e in exception_evidence[:3]
                    )
                    suppressed.append(
                        SuppressedMatch(
                            rule_id=rule.id,
                            reason=f"exception matched: {reasons}",
                            evidence=exception_evidence,
                        )
                    )
                    continue
            fired.append((rule, evidence))

        decision = Decision.most_restrictive(rule.effect for rule, _ in fired)
        matches = [
            RuleMatch(
                rule_id=rule.id,
                principle=rule.principle,
                deontic=rule.deontic,
                severity=rule.severity,
                effect=rule.effect,
                rationale=rule.rationale,
                evidence=evidence,
                hard=rule.hard,
                user_message=rule.user_message,
            )
            for rule, evidence in fired
        ]
        matches.sort(
            key=lambda m: (m.effect.restrictiveness, m.severity.rank), reverse=True
        )

        rewritten = None
        if decision is Decision.REWRITE:
            rewritten = self._apply_rewrites(action.content, fired)

        return Verdict(
            decision=decision,
            stage=action.stage,
            engine=self.name,
            matches=matches,
            suppressed=suppressed,
            rewritten_content=rewritten,
            reason=self._summarise(matches, suppressed),
        )

    @staticmethod
    def _summarise(
        matches: Sequence[RuleMatch], suppressed: Sequence[SuppressedMatch]
    ) -> str:
        if not matches and not suppressed:
            return "no rule matched"
        parts = []
        hard_count = sum(1 for m in matches if m.hard)
        if hard_count:
            parts.append(f"{hard_count} hard constraint(s) violated")
        soft = [m for m in matches if not m.hard]
        if soft:
            ids = ", ".join(m.rule_id for m in soft)
            parts.append(f"{len(soft)} rule(s) triggered ({ids})")
        if suppressed:
            ids = ", ".join(s.rule_id for s in suppressed)
            parts.append(f"{len(suppressed)} rule(s) suppressed by exception ({ids})")
        return "; ".join(parts)

    @staticmethod
    def _apply_rewrites(
        content: str, fired: Sequence[Tuple[Rule, List[Evidence]]]
    ) -> str:
        rewrite_rules = [
            (rule, evidence)
            for rule, evidence in fired
            if rule.effect is Decision.REWRITE
        ]

        result = content
        redactions: List[Tuple[int, int, str]] = []
        for rule, evidence in rewrite_rules:
            if not rule.redact:
                continue
            for item in evidence:
                if item.span is not None:
                    redactions.append((item.span[0], item.span[1], rule.id))
        redactions.sort(reverse=True)
        last_start = len(result) + 1
        for start, end, rule_id in redactions:
            if end > last_start:
                continue
            result = f"{result[:start]}[REDACTED:{rule_id}]{result[end:]}"
            last_start = start

        template_rules = [r for r, _ in rewrite_rules if r.rewrite_template]
        if template_rules:
            rule = max(template_rules, key=lambda r: r.severity.rank)
            if "{content}" in rule.rewrite_template:
                result = rule.rewrite_template.replace("{content}", result)
            else:
                result = rule.rewrite_template
        return result


class CompositeEngine(PolicyEngine):
    name = "composite"

    def __init__(self, engines: Sequence[PolicyEngine], name: Optional[str] = None):
        if not engines:
            raise ValueError("CompositeEngine requires at least one engine")
        self.engines = list(engines)
        if name:
            self.name = name

    def evaluate(self, action: ActionContext) -> Verdict:
        verdicts: List[Verdict] = []
        for engine in self.engines:
            try:
                verdicts.append(engine.evaluate(action))
            except Exception as exc:
                verdicts.append(
                    Verdict(
                        decision=Decision.DENY,
                        stage=action.stage,
                        engine=engine.name,
                        reason=f"engine error (fail closed): {exc}",
                    )
                )

        decision = Decision.most_restrictive(v.decision for v in verdicts)
        matches = [m for v in verdicts for m in v.matches]
        suppressed = [s for v in verdicts for s in v.suppressed]
        rewritten = None
        if decision is Decision.REWRITE:
            rewritten = next(
                (
                    v.rewritten_content
                    for v in verdicts
                    if v.decision is Decision.REWRITE and v.rewritten_content
                ),
                None,
            )
        reason = " | ".join(
            f"{v.engine}: {v.decision.value} ({v.reason})" for v in verdicts
        )
        return Verdict(
            decision=decision,
            stage=action.stage,
            engine=self.name,
            matches=matches,
            suppressed=suppressed,
            rewritten_content=rewritten,
            reason=reason,
        )
