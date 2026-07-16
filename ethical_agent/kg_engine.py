from __future__ import annotations

from typing import List, Tuple

from .engine import PolicyEngine, RuleBasedEngine
from .ontology import Norm, Ontology
from .types import ActionContext, Decision, RuleMatch, SuppressedMatch, Verdict


class KnowledgeGraphEngine(PolicyEngine):
    name = "knowledge-graph"

    def __init__(self, ontology: Ontology):
        self.ontology = ontology

    def _build_match(self, norm: Norm, evidence: list) -> RuleMatch:
        provocations = []
        for concept_id in norm.when:
            concept = self.ontology.concepts.get(concept_id)
            if concept and concept.provocation:
                provocations.append(f"[{concept_id}] {concept.provocation}")
        rationale = norm.rationale
        user_message = norm.user_message
        if provocations:
            joined = " ".join(provocations)
            rationale = f"{rationale}  |  RelAIEO provocation(s): {joined}".strip()
            if not user_message:
                user_message = f"Reflective audit prompt (RelAIEO): {joined}"
        return RuleMatch(
            rule_id=norm.id,
            principle=norm.principle,
            deontic=norm.deontic,
            severity=norm.severity,
            effect=norm.effect,
            rationale=rationale,
            evidence=evidence,
            hard=False,
            user_message=user_message,
        )

    def evaluate(self, action: ActionContext) -> Verdict:
        activation = self.ontology.activate(action.content)
        fired: List[Tuple[Norm, list]] = []
        suppressed: List[SuppressedMatch] = []

        for norm in self.ontology.norms:
            if not norm.applies_to(action.stage):
                continue
            if not all(concept in activation for concept in norm.when):
                continue
            evidence = [
                item
                for concept in norm.when
                for item in activation[concept][:3]
            ]
            blocking = [c for c in norm.unless if c in activation]
            if blocking:
                suppressed.append(
                    SuppressedMatch(
                        rule_id=norm.id,
                        reason=f"exception concept active: {', '.join(blocking)}",
                        evidence=[
                            item
                            for concept in blocking
                            for item in activation[concept][:3]
                        ],
                    )
                )
                continue
            fired.append((norm, evidence))

        decision = Decision.most_restrictive(norm.effect for norm, _ in fired)
        matches = [
            self._build_match(norm, evidence) for norm, evidence in fired
        ]
        matches.sort(
            key=lambda m: (m.effect.restrictiveness, m.severity.rank), reverse=True
        )

        return Verdict(
            decision=decision,
            stage=action.stage,
            engine=self.name,
            matches=matches,
            suppressed=suppressed,
            reason=RuleBasedEngine._summarise(matches, suppressed),
        )
