from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable, Optional


class Stage(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


class Decision(str, Enum):
    ALLOW = "ALLOW"
    FLAG = "FLAG"
    REWRITE = "REWRITE"
    DENY = "DENY"

    @property
    def restrictiveness(self) -> int:
        return _RESTRICTIVENESS[self]

    @staticmethod
    def most_restrictive(decisions: Iterable["Decision"]) -> "Decision":
        result = Decision.ALLOW
        for decision in decisions:
            if decision.restrictiveness > result.restrictiveness:
                result = decision
        return result


_RESTRICTIVENESS = {
    Decision.ALLOW: 0,
    Decision.FLAG: 1,
    Decision.REWRITE: 2,
    Decision.DENY: 3,
}


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]


_SEVERITY_RANK = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}


# The closed vocabulary of ethical principles a rule or norm may claim.
#
# This is CHECKED, not merely declared: Rule.from_dict (policy.py) and the
# norm/concept loaders (ontology.py) reject anything outside it, listing the
# offending id. For a long time nothing read this frozenset, and the name
# promised a validation that did not happen -- a rule could say
# principle: "beneficencia" (misspelt) and load without a word, then group
# under a heading no report expects. A principle nobody recognises is a rule
# nobody can classify; failing to load is the right answer, the same way an
# invalid severity or scope already fails.
#
# `beneficence` is deliberately here and deliberately unused today: no rule in
# policies/core_policy.json and no norm in ontologies/relaieo_norms.json
# claims it. It is reserved -- shrinking a vocabulary because nothing has
# needed it yet is a policy decision, not a cleanup.
#
# NOT applied to the eval datasets. `eval/dataset*.json` also has a
# "principle" field, but that is a different vocabulary that happens to share
# a name: evaluate_engine reads it only to group the report, and its most
# common value is "benign", meaning "no principle applies -- this case should
# pass". Validating datasets against this set would be a category error.
KNOWN_PRINCIPLES = frozenset(
    {
        "non_maleficence",
        "beneficence",
        "privacy",
        "autonomy",
        "fairness",
        "transparency",
        "accountability",
        "security",
    }
)


@dataclass(frozen=True)
class Evidence:
    description: str
    matched_text: Optional[str] = None
    span: Optional[tuple] = None

    def to_dict(self) -> dict:
        return {
            "description": self.description,
            "matched_text": self.matched_text,
            "span": list(self.span) if self.span else None,
        }

    def without_matched_text(self) -> "Evidence":
        """Drop the literal matched substring, keeping only where it was found.

        Used for rules that redact their own match (e.g. PII rewrite rules):
        the point of redaction is defeated if the raw value survives in the
        verdict/audit trail via evidence.
        """
        return Evidence(description=self.description, span=self.span)


@dataclass
class RuleMatch:
    rule_id: str
    principle: str
    deontic: str
    severity: Severity
    effect: Decision
    rationale: str
    evidence: list = field(default_factory=list)
    hard: bool = False
    user_message: Optional[str] = None
    redacted: bool = False
    """True iff the rule producing this match has redact=True -- i.e. this
    match's own matched text must never be retained anywhere (trace, audit
    log), regardless of whether the same or another fired rule also carries
    a rewrite_template. See Verdict.suppresses_raw_content."""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "principle": self.principle,
            "deontic": self.deontic,
            "severity": self.severity.value,
            "effect": self.effect.value,
            "rationale": self.rationale,
            "hard": self.hard,
            "redacted": self.redacted,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class SuppressedMatch:
    rule_id: str
    reason: str
    evidence: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "reason": self.reason,
            "evidence": [e.to_dict() for e in self.evidence],
        }


@dataclass
class ActionContext:
    content: str
    stage: Stage = Stage.INPUT
    metadata: dict = field(default_factory=dict)


@dataclass
class Verdict:
    decision: Decision
    stage: Stage
    engine: str
    matches: list = field(default_factory=list)
    suppressed: list = field(default_factory=list)
    rewritten_content: Optional[str] = None
    reason: str = ""
    system_error: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def intervened(self) -> bool:
        return self.decision in (Decision.DENY, Decision.REWRITE)

    @property
    def suppresses_raw_content(self) -> bool:
        """True when this REWRITE was (at least partly) caused by a
        redact=True rule -- in that case pre-rewrite raw content must never
        be retained anywhere (trace/audit), even if another fired rule also
        has a rewrite_template (redaction is sticky: it wins). REWRITE
        caused purely by rewrite_template rules must NOT suppress raw
        content -- auditors need the original for those.
        """
        return self.decision is Decision.REWRITE and any(
            m.redacted for m in self.matches
        )

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "stage": self.stage.value,
            "engine": self.engine,
            "reason": self.reason,
            "system_error": self.system_error,
            "matches": [m.to_dict() for m in self.matches],
            "suppressed": [s.to_dict() for s in self.suppressed],
            "rewritten_content": self.rewritten_content,
            "created_at": self.created_at,
        }

    def explain(self) -> str:
        lines = [
            f"Decision: {self.decision.value} "
            f"(stage={self.stage.value}, engine={self.engine})"
        ]
        if self.reason:
            lines.append(f"Reason: {self.reason}")
        for match in self.matches:
            hard = " [HARD CONSTRAINT]" if match.hard else ""
            lines.append(
                f"- {match.rule_id}{hard} | principle={match.principle} | "
                f"deontic={match.deontic} | severity={match.severity.value} "
                f"-> {match.effect.value}"
            )
            if match.rationale:
                lines.append(f"    rationale: {match.rationale}")
            for ev in match.evidence[:5]:
                where = f" at {ev.span[0]}..{ev.span[1]}" if ev.span else ""
                matched = f" ({ev.matched_text!r})" if ev.matched_text else ""
                lines.append(f"    evidence: {ev.description}{matched}{where}")
        for sup in self.suppressed:
            lines.append(f"- {sup.rule_id} SUPPRESSED: {sup.reason}")
        if self.rewritten_content is not None:
            lines.append(f"Rewritten content: {self.rewritten_content!r}")
        return "\n".join(lines)
