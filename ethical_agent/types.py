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
    ESCALATE = "ESCALATE"
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
    Decision.ESCALATE: 3,
    Decision.DENY: 4,
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

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "principle": self.principle,
            "deontic": self.deontic,
            "severity": self.severity.value,
            "effect": self.effect.value,
            "rationale": self.rationale,
            "hard": self.hard,
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
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def intervened(self) -> bool:
        return self.decision in (Decision.DENY, Decision.REWRITE, Decision.ESCALATE)

    def to_dict(self) -> dict:
        return {
            "decision": self.decision.value,
            "stage": self.stage.value,
            "engine": self.engine,
            "reason": self.reason,
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
