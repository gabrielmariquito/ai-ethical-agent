from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from .conditions import Condition, ConditionError, condition_from_dict
from .types import Decision, Severity, Stage

SCHEMA_VERSION = "1.0"

_VALID_DEONTICS = {"prohibition", "obligation"}
_VALID_EFFECTS = {Decision.DENY, Decision.ESCALATE, Decision.REWRITE, Decision.FLAG}


class PolicyError(ValueError):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("invalid policy:\n" + "\n".join(f"- {e}" for e in errors))


@dataclass
class Rule:
    id: str
    principle: str
    description: str
    deontic: str
    severity: Severity
    scopes: frozenset
    condition: Condition
    effect: Decision
    rationale: str = ""
    references: list = field(default_factory=list)
    exceptions: Optional[Condition] = None
    rewrite_template: Optional[str] = None
    redact: bool = False
    user_message: Optional[str] = None
    hard: bool = False

    def applies_to(self, stage: Stage) -> bool:
        return stage in self.scopes

    @classmethod
    def from_dict(cls, data: dict, hard: bool = False) -> "Rule":
        errors: List[str] = []
        rule_id = data.get("id") or "<missing id>"

        principle = data.get("principle", "")
        if not principle:
            errors.append(f"{rule_id}: missing 'principle'")

        deontic = data.get("deontic", "prohibition")
        if deontic not in _VALID_DEONTICS:
            errors.append(
                f"{rule_id}: deontic must be one of {sorted(_VALID_DEONTICS)}, "
                f"got {deontic!r}"
            )

        try:
            severity = Severity(data.get("severity", "medium"))
        except ValueError:
            errors.append(f"{rule_id}: invalid severity {data.get('severity')!r}")
            severity = Severity.MEDIUM

        raw_scopes = data.get("scopes", ["input"])
        scopes = set()
        for raw in raw_scopes:
            try:
                scopes.add(Stage(raw))
            except ValueError:
                errors.append(f"{rule_id}: invalid scope {raw!r}")
        if not scopes:
            errors.append(f"{rule_id}: at least one scope is required")

        condition: Optional[Condition] = None
        try:
            condition = condition_from_dict(data.get("condition", {}))
        except ConditionError as exc:
            errors.append(f"{rule_id}: condition error: {exc}")

        if hard:
            effect = Decision.DENY
            if data.get("effect") not in (None, "DENY"):
                errors.append(
                    f"{rule_id}: hard constraints always DENY; "
                    f"remove effect {data.get('effect')!r}"
                )
            if data.get("exceptions") is not None:
                errors.append(f"{rule_id}: hard constraints admit no exceptions")
        else:
            try:
                effect = Decision(data.get("effect", "DENY"))
            except ValueError:
                errors.append(f"{rule_id}: invalid effect {data.get('effect')!r}")
                effect = Decision.DENY
            if effect not in _VALID_EFFECTS:
                errors.append(
                    f"{rule_id}: effect must be one of "
                    f"{sorted(e.value for e in _VALID_EFFECTS)}"
                )

        exceptions: Optional[Condition] = None
        if not hard and data.get("exceptions") is not None:
            try:
                exceptions = condition_from_dict(data["exceptions"])
            except ConditionError as exc:
                errors.append(f"{rule_id}: exceptions error: {exc}")

        rewrite_template = data.get("rewrite_template")
        redact = bool(data.get("redact", False))
        if effect is Decision.REWRITE and not (rewrite_template or redact):
            errors.append(
                f"{rule_id}: REWRITE effect requires 'rewrite_template' and/or "
                f"'redact: true'"
            )
        if (rewrite_template or redact) and effect is not Decision.REWRITE:
            errors.append(
                f"{rule_id}: 'rewrite_template'/'redact' only apply to REWRITE effect"
            )

        if errors:
            raise PolicyError(errors)

        return cls(
            id=data["id"],
            principle=principle,
            description=data.get("description", ""),
            deontic=deontic,
            severity=severity,
            scopes=frozenset(scopes),
            condition=condition,
            effect=effect,
            rationale=data.get("rationale", ""),
            references=list(data.get("references", [])),
            exceptions=exceptions,
            rewrite_template=rewrite_template,
            redact=redact,
            user_message=data.get("user_message"),
            hard=hard,
        )


@dataclass
class Policy:
    schema_version: str
    metadata: dict
    constraints: List[Rule]
    rules: List[Rule]

    @classmethod
    def from_dict(cls, data: dict) -> "Policy":
        errors: List[str] = []
        schema_version = data.get("schema_version", SCHEMA_VERSION)

        constraints: List[Rule] = []
        rules: List[Rule] = []
        for raw in data.get("constraints", []):
            if not raw.get("id"):
                errors.append("constraint without 'id'")
                continue
            try:
                constraints.append(Rule.from_dict(raw, hard=True))
            except PolicyError as exc:
                errors.extend(exc.errors)
        for raw in data.get("rules", []):
            if not raw.get("id"):
                errors.append("rule without 'id'")
                continue
            try:
                rules.append(Rule.from_dict(raw, hard=False))
            except PolicyError as exc:
                errors.extend(exc.errors)

        seen = set()
        for rule in constraints + rules:
            if rule.id in seen:
                errors.append(f"duplicate rule id: {rule.id}")
            seen.add(rule.id)

        if not constraints and not rules:
            errors.append("policy defines no constraints and no rules")

        if errors:
            raise PolicyError(errors)

        return cls(
            schema_version=schema_version,
            metadata=data.get("metadata", {}),
            constraints=constraints,
            rules=rules,
        )

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "Policy":
        path = Path(path)
        with path.open(encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise PolicyError([f"{path}: invalid JSON: {exc}"]) from exc
        return cls.from_dict(data)

    def rules_for(self, stage: Stage) -> List[Rule]:
        ordered = [r for r in self.constraints if r.applies_to(stage)]
        ordered.extend(r for r in self.rules if r.applies_to(stage))
        return ordered

    def get(self, rule_id: str) -> Optional[Rule]:
        for rule in self.constraints + self.rules:
            if rule.id == rule_id:
                return rule
        return None


def default_policy_path() -> Path:
    return Path(__file__).resolve().parents[1] / "policies" / "core_policy.json"
