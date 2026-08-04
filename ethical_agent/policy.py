from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from .conditions import Condition, ConditionError, condition_from_dict
from .provenance import ConfigArtifact
from .types import KNOWN_PRINCIPLES, Decision, Severity, Stage

SCHEMA_VERSION = "1.0"

_VALID_DEONTICS = {"prohibition", "obligation"}
_VALID_EFFECTS = {Decision.DENY, Decision.REWRITE, Decision.FLAG}

# `suppressed_effect` admite um valor que `effect` não admite: ALLOW — como
# *efeito* seria uma regra que não decide, como *sucessor* é a única forma de
# dizer "esta isenção libera de propósito" — versão longa em `997a6fe^`.
_VALID_SUPPRESSED_EFFECTS = _VALID_EFFECTS | {Decision.ALLOW}


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
    suppressed_effect: Optional[Decision] = None
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
        elif principle not in KNOWN_PRINCIPLES:
            # Verificado, não apenas declarado: `KNOWN_PRINCIPLES` passou muito tempo sem
            # leitor, e uma grafia errada carregava sem uma palavra — versão longa em `997a6fe^`.
            errors.append(
                f"{rule_id}: unknown principle {principle!r}, "
                f"expected one of {sorted(KNOWN_PRINCIPLES)}"
            )

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

        # Default `None`, e deliberadamente não um valor que rebaixa: um default que
        # rebaixasse daria a todo bloco `exceptions` um sucessor que o autor nunca
        # escreveu — versão longa em `997a6fe^`.
        suppressed_effect: Optional[Decision] = None
        raw_suppressed = data.get("suppressed_effect")
        if raw_suppressed is not None:
            if hard:
                errors.append(
                    f"{rule_id}: hard constraints admit no exceptions, "
                    f"so 'suppressed_effect' has nothing to succeed"
                )
            try:
                suppressed_effect = Decision(raw_suppressed)
            except ValueError:
                errors.append(
                    f"{rule_id}: invalid suppressed_effect {raw_suppressed!r}"
                )
            else:
                if suppressed_effect not in _VALID_SUPPRESSED_EFFECTS:
                    errors.append(
                        f"{rule_id}: suppressed_effect must be one of "
                        f"{sorted(e.value for e in _VALID_SUPPRESSED_EFFECTS)}"
                    )
                if not hard and data.get("exceptions") is None:
                    errors.append(
                        f"{rule_id}: 'suppressed_effect' without 'exceptions' -- "
                        f"nothing can demote this rule, so the successor is dead "
                        f"letter"
                    )
                # An exception may only relax. A successor at or above the
                # rule's own effect means the exemption either changes nothing
                # or tightens on match, and both read as a rule written the
                # wrong way round -- say it directly rather than shipping a
                # policy whose exception block is decorative.
                if (
                    suppressed_effect.restrictiveness
                    >= effect.restrictiveness
                ):
                    errors.append(
                        f"{rule_id}: suppressed_effect {suppressed_effect.value!r} "
                        f"is not less restrictive than effect {effect.value!r}; "
                        f"an exception may only relax"
                    )

        rewrite_template = data.get("rewrite_template")
        redact = bool(data.get("redact", False))
        # A REWRITE reached by demotion needs the same equipment as a REWRITE
        # declared outright -- without a template or redaction it rewrites
        # nothing and the demotion produces a REWRITE verdict whose rewritten
        # content is the original, which is worse than either honest answer.
        rewrites = {effect, suppressed_effect}
        if Decision.REWRITE in rewrites and not (rewrite_template or redact):
            culprit = (
                "REWRITE effect"
                if effect is Decision.REWRITE
                else "suppressed_effect: REWRITE"
            )
            errors.append(
                f"{rule_id}: {culprit} requires 'rewrite_template' and/or "
                f"'redact: true'"
            )
        if (rewrite_template or redact) and Decision.REWRITE not in rewrites:
            errors.append(
                f"{rule_id}: 'rewrite_template'/'redact' only apply to REWRITE, "
                f"as 'effect' or as 'suppressed_effect'"
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
            suppressed_effect=suppressed_effect,
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
    # Onde este objeto foi lido, quando foi lido de um arquivo. `from_dict` --
    # toda fixture de teste, e qualquer política montada em memória -- deixa
    # None, e nesse caso o artefato sai com digest "" e a versão declarada
    # mantida. Ausência de arquivo não é ausência de identidade.
    source_path: Optional[Path] = None

    def config_artifacts(self) -> List["ConfigArtifact"]:
        return [ConfigArtifact(
            role="policy",
            version=self.metadata.get("version"),
            path=str(self.source_path) if self.source_path else None,
        )]

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
        policy = cls.from_dict(data)
        policy.source_path = path
        return policy

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
