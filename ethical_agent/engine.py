from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Sequence, Tuple

from .policy import Policy, Rule
from .provenance import ConfigArtifact
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

    def describe_config(self) -> dict:
        """Identifica a(s) versão(ões) de configuração por trás dos vereditos,
        para carimbar registros de auditoria — reporta versão **declarada**,
        e o que foi de fato carregado está em `config_artifacts`: versão longa em `997a6fe^`.
        """
        return {}

    def config_artifacts(self) -> List[ConfigArtifact]:
        """Os arquivos de configuração por trás dos vereditos, **planos** mesmo
        no `CompositeEngine`, porque a configuração que governa uma decisão é
        uma coisa só: versão longa em `997a6fe^`.
        """
        return []


class RuleBasedEngine(PolicyEngine):
    name = "rule-based"

    def __init__(self, policy: Policy, frames=None):
        self.policy = policy
        # A camada de frames é do motor, não da política: ela é lida e declarada
        # mesmo quando nenhuma regra a usa, para que o artefato embarcado fique
        # registrado no `config_id` e o diff da leva da taxonomia seja só sobre
        # a norma. Mesma lógica do `ontology_ttl`, cuja maioria das classes não
        # tem norma e que ainda assim é declarado.
        self.frames = frames

    def describe_config(self) -> dict:
        declarado = {
            "policy_schema_version": self.policy.schema_version,
            "policy_version": self.policy.metadata.get("version", "unknown"),
        }
        if self.frames is not None:
            declarado["frames_refusal_version"] = self.frames.metadata.get(
                "version", "unknown"
            )
        return declarado

    def config_artifacts(self) -> List[ConfigArtifact]:
        artefatos = self.policy.config_artifacts()
        if self.frames is not None:
            artefatos = artefatos + self.frames.config_artifacts()
        return artefatos

    def evaluate(self, action: ActionContext) -> Verdict:
        # `fired` carries the *effective* effect alongside the rule, not just
        # the rule. A demoted rule differs from an undemoted one in exactly one
        # respect -- which effect it casts -- so carrying that effect here lets
        # most_restrictive, the match list and the rewrite pass treat it like
        # any other fired rule instead of growing a branch apiece.
        fired: List[Tuple[Rule, Decision, List[Evidence]]] = []
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
                    successor = rule.suppressed_effect or Decision.ALLOW
                    suppressed.append(
                        SuppressedMatch(
                            rule_id=rule.id,
                            reason=f"exception matched: {reasons}",
                            evidence=exception_evidence,
                            demoted_to=successor,
                        )
                    )
                    if successor is Decision.ALLOW:
                        continue
                    # A evidência do gatilho, não a da exceção: é o gatilho que justifica o
                    # efeito que sobreviver — versão longa em `997a6fe^`.
                    fired.append((rule, successor, evidence))
                    continue
            fired.append((rule, rule.effect, evidence))

        decision = Decision.most_restrictive(effect for _, effect, _ in fired)
        matches = [
            RuleMatch(
                rule_id=rule.id,
                principle=rule.principle,
                deontic=rule.deontic,
                severity=rule.severity,
                effect=effect,
                rationale=rule.rationale,
                evidence=(
                    [e.without_matched_text() for e in evidence]
                    if rule.redact
                    else evidence
                ),
                hard=rule.hard,
                user_message=rule.user_message,
                redacted=rule.redact,
                demoted_from=rule.effect if effect is not rule.effect else None,
            )
            for rule, effect, evidence in fired
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
            # Say what each one was demoted *to*. "R-SEC-002 suppressed" left
            # the reader unable to tell a released request from a downgraded
            # one, and that ambiguity was the whole finding.
            ids = ", ".join(
                f"{s.rule_id} -> {s.demoted_to.value}" for s in suppressed
            )
            parts.append(f"{len(suppressed)} rule(s) suppressed by exception ({ids})")
        return "; ".join(parts)

    @staticmethod
    def _apply_rewrites(
        content: str, fired: Sequence[Tuple[Rule, Decision, List[Evidence]]]
    ) -> str:
        # Filtered on the effective effect, so a rule demoted into REWRITE
        # rewrites on the same terms as one that declared REWRITE outright.
        rewrite_rules = [
            (rule, evidence)
            for rule, effect, evidence in fired
            if effect is Decision.REWRITE
        ]

        result = content
        # start, end, rule_id, severity_rank
        redactions: List[Tuple[int, int, str, int]] = []
        for rule, evidence in rewrite_rules:
            if not rule.redact:
                continue
            # A redação tem de ser completa mesmo além do teto de evidências, então esta
            # varredura é sem limite — versão longa em `997a6fe^`.
            full_evidence = rule.condition.evaluate(content, limit=None)
            for item in full_evidence:
                if item.span is not None:
                    redactions.append(
                        (item.span[0], item.span[1], rule.id, rule.severity.rank)
                    )

        if redactions:
            # Funde spans sobrepostos em intervalos unificados antes de substituir, senão
            # conteúdo é descartado — versão longa em `997a6fe^`.
            redactions.sort(key=lambda r: (r[0], r[1]))
            merged: List[List] = []  # [start, end, [(severity_rank, rule_id), ...]]
            for start, end, rule_id, sev in redactions:
                if merged and start < merged[-1][1]:
                    merged[-1][1] = max(merged[-1][1], end)
                    merged[-1][2].append((sev, rule_id))
                else:
                    merged.append([start, end, [(sev, rule_id)]])
            # Uma passada só da esquerda para a direita sobre o `content` intacto, em
            # vez de refatiar por redação, que seria O(matches × tamanho).
            pieces = []
            cursor = 0
            for start, end, contributors in merged:
                pieces.append(content[cursor:start])
                tag_rule_id = max(contributors)[1]
                pieces.append(f"[REDACTED:{tag_rule_id}]")
                cursor = end
            pieces.append(content[cursor:])
            result = "".join(pieces)

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

    def describe_config(self) -> dict:
        return {engine.name: engine.describe_config() for engine in self.engines}

    def config_artifacts(self) -> List[ConfigArtifact]:
        """Concatenated, not nested. Deduplication is by (role, path) in
        provenance.build_configuration, so two engines sharing one policy file
        contribute one artifact, not two identical ones."""
        return [a for engine in self.engines for a in engine.config_artifacts()]

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
                        system_error=True,
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
            system_error=any(v.system_error for v in verdicts),
        )
