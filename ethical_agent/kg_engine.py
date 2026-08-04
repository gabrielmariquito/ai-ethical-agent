from __future__ import annotations

from typing import List, Tuple

from .engine import PolicyEngine, RuleBasedEngine
from .ontology import Norm, Ontology
from .provenance import ConfigArtifact
from .types import (
    ActionContext,
    Decision,
    Evidence,
    RuleMatch,
    SuppressedMatch,
    Verdict,
)


class KnowledgeGraphEngine(PolicyEngine):
    name = "knowledge-graph"

    def __init__(self, ontology: Ontology, frames=None):
        self.ontology = ontology
        # Espelha `RuleBasedEngine(policy, frames=None)`. Uma norma que declara
        # `unless_frame` sem que o motor tenha frames carregados não suprime --
        # ausência de detector não pode virar isenção silenciosa.
        self.frames = frames

    def config_artifacts(self) -> List[ConfigArtifact]:
        return self.ontology.config_artifacts()

    def describe_config(self) -> dict:
        declarado = {
            "ontology_schema_version": self.ontology.schema_version,
            "ontology_grounding_version": self.ontology.metadata.get(
                "grounding_version", "unknown"
            ),
            "ontology_norms_version": self.ontology.metadata.get(
                "norms_version", "unknown"
            ),
        }
        # Chaves próprias, e não reuso das de cima: a taxonomia de dano é outra
        # fonte, com outro ciclo de vida e outra autoria. Reusar faria a segunda
        # carga sobrescrever a primeira e o registro alegar a camada errada.
        for chave in ("harm_grounding_version", "harm_norms_version"):
            if chave in self.ontology.metadata:
                declarado[chave] = self.ontology.metadata[chave]
        return declarado

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

    def _sob_guarda_de_frame(self, norm: Norm, texto: str, activation: dict) -> bool:
        """Todo casamento dos conceitos de `when` cai dentro de um escopo do frame.

        Contenção por span, e é a semântica em vigor desde a camada de frames --
        não cobertura total do texto (medida inerte, 2 de 10) nem "algum escopo
        marcado" (medida como porta de evasão, 10 de 10). `activate()` já devolve
        `Evidence` com span; até aqui a informação era descartada.
        """
        if norm.unless_frame is None or self.frames is None:
            return False
        spans = [
            item.span
            for concept in norm.when
            for item in activation.get(concept, [])
        ]
        return self.frames.sob_recusa(texto, spans)

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
            if self._sob_guarda_de_frame(norm, action.content, activation):
                suppressed.append(
                    SuppressedMatch(
                        rule_id=norm.id,
                        reason=f"frame guard {norm.unless_frame!r}: every match lies inside it",
                        evidence=[Evidence(description=f"frame guard {norm.unless_frame!r}")],
                        demoted_to=Decision.ALLOW,
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
