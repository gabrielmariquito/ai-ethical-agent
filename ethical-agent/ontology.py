from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from .conditions import Condition, ConditionError, register_condition_type
from .types import Decision, Evidence, Severity, Stage

PROPAGATING_PREDICATES = {"is_a", "part_of", "implies"}

_VALID_NORM_EFFECTS = {Decision.DENY, Decision.ESCALATE, Decision.FLAG}
_VALID_DEONTICS = {"prohibition", "obligation"}

MAX_GROUND_EVIDENCE = 10


class OntologyError(ValueError):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("invalid ontology:\n" + "\n".join(f"- {e}" for e in errors))


@dataclass(frozen=True)
class Lexicalization:
    term: str
    regex: bool = False


@dataclass
class Concept:
    id: str
    label: str
    principle: str = ""
    description: str = ""
    provocation: str = ""
    references: list = field(default_factory=list)
    terms: List[Lexicalization] = field(default_factory=list)
    _patterns: list = field(default_factory=list, repr=False)

    def compile(self) -> None:
        self._patterns = []
        for lex in self.terms:
            pattern = lex.term if lex.regex else rf"\b{re.escape(lex.term)}\b"
            try:
                self._patterns.append((lex, re.compile(pattern, re.IGNORECASE)))
            except re.error as exc:
                raise OntologyError(
                    [f"{self.id}: invalid term pattern {lex.term!r}: {exc}"]
                ) from exc

    def ground(self, text: str) -> List[Evidence]:
        evidence: List[Evidence] = []
        for lex, regex in self._patterns:
            for match in regex.finditer(text):
                evidence.append(
                    Evidence(
                        description=f"concept {self.id!r} term {lex.term!r}",
                        matched_text=match.group(0),
                        span=(match.start(), match.end()),
                    )
                )
                if len(evidence) >= MAX_GROUND_EVIDENCE:
                    return evidence
        return evidence


@dataclass(frozen=True)
class Relation:
    subject: str
    predicate: str
    object: str

    @property
    def propagates(self) -> bool:
        return self.predicate in PROPAGATING_PREDICATES


@dataclass
class Norm:
    id: str
    principle: str
    deontic: str
    severity: Severity
    effect: Decision
    scopes: frozenset
    when: List[str]
    unless: List[str] = field(default_factory=list)
    description: str = ""
    rationale: str = ""
    references: list = field(default_factory=list)
    user_message: Optional[str] = None

    def applies_to(self, stage: Stage) -> bool:
        return stage in self.scopes


@dataclass
class Ontology:
    schema_version: str
    metadata: dict
    concepts: Dict[str, Concept]
    relations: List[Relation]
    norms: List[Norm]
    _edges: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "Ontology":
        errors: List[str] = []

        concepts: Dict[str, Concept] = {}
        for raw in data.get("concepts", []):
            concept_id = raw.get("id")
            if not concept_id:
                errors.append("concept without 'id'")
                continue
            if concept_id in concepts:
                errors.append(f"duplicate concept id: {concept_id}")
                continue
            terms = []
            for raw_term in raw.get("terms", []):
                term = raw_term.get("term")
                if not term:
                    errors.append(f"{concept_id}: term without 'term' value")
                    continue
                terms.append(Lexicalization(term=term, regex=bool(raw_term.get("regex", False))))
            concepts[concept_id] = Concept(
                id=concept_id,
                label=raw.get("label", concept_id),
                principle=raw.get("principle", ""),
                description=raw.get("description", ""),
                provocation=raw.get("provocation", ""),
                references=list(raw.get("references", [])),
                terms=terms,
            )

        relations: List[Relation] = []
        for raw in data.get("relations", []):
            subject = raw.get("subject")
            predicate = raw.get("predicate")
            obj = raw.get("object")
            if not (subject and predicate and obj):
                errors.append(f"relation missing fields: {raw!r}")
                continue
            for ref in (subject, obj):
                if ref not in concepts:
                    errors.append(f"relation references unknown concept: {ref!r}")
            relations.append(Relation(subject=subject, predicate=predicate, object=obj))

        norms: List[Norm] = []
        seen_norms = set()
        for raw in data.get("norms", []):
            norm_id = raw.get("id") or "<missing id>"
            if norm_id in seen_norms:
                errors.append(f"duplicate norm id: {norm_id}")
            seen_norms.add(norm_id)

            deontic = raw.get("deontic", "prohibition")
            if deontic not in _VALID_DEONTICS:
                errors.append(f"{norm_id}: invalid deontic {deontic!r}")

            try:
                severity = Severity(raw.get("severity", "medium"))
            except ValueError:
                errors.append(f"{norm_id}: invalid severity {raw.get('severity')!r}")
                severity = Severity.MEDIUM

            try:
                effect = Decision(raw.get("effect", "DENY"))
            except ValueError:
                errors.append(f"{norm_id}: invalid effect {raw.get('effect')!r}")
                effect = Decision.DENY
            if effect not in _VALID_NORM_EFFECTS:
                errors.append(
                    f"{norm_id}: norm effect must be one of "
                    f"{sorted(e.value for e in _VALID_NORM_EFFECTS)}"
                )

            scopes = set()
            for raw_scope in raw.get("scopes", ["input", "output"]):
                try:
                    scopes.add(Stage(raw_scope))
                except ValueError:
                    errors.append(f"{norm_id}: invalid scope {raw_scope!r}")

            when = list(raw.get("when", []))
            if not when:
                errors.append(f"{norm_id}: 'when' requires at least one concept")
            unless = list(raw.get("unless", []))
            for ref in when + unless:
                if ref not in concepts:
                    errors.append(f"{norm_id}: unknown concept {ref!r}")

            norms.append(
                Norm(
                    id=norm_id,
                    principle=raw.get("principle", ""),
                    deontic=deontic,
                    severity=severity,
                    effect=effect,
                    scopes=frozenset(scopes),
                    when=when,
                    unless=unless,
                    description=raw.get("description", ""),
                    rationale=raw.get("rationale", ""),
                    references=list(raw.get("references", [])),
                    user_message=raw.get("user_message"),
                )
            )

        if not concepts:
            errors.append("ontology defines no concepts")

        if errors:
            raise OntologyError(errors)

        for concept in concepts.values():
            concept.compile()

        edges = defaultdict(list)
        for relation in relations:
            if relation.propagates:
                edges[relation.subject].append((relation.predicate, relation.object))

        return cls(
            schema_version=data.get("schema_version", "1.0"),
            metadata=data.get("metadata", {}),
            concepts=concepts,
            relations=relations,
            norms=norms,
            _edges=dict(edges),
        )

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "Ontology":
        path = Path(path)
        with path.open(encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise OntologyError([f"{path}: invalid JSON: {exc}"]) from exc
        return cls.from_dict(data)

    def activate(self, text: str) -> Dict[str, List[Evidence]]:
        activated: Dict[str, List[Evidence]] = {}
        queue = deque()
        for concept in self.concepts.values():
            evidence = concept.ground(text)
            if evidence:
                activated[concept.id] = evidence
                queue.append(concept.id)
        while queue:
            current = queue.popleft()
            for predicate, target in self._edges.get(current, []):
                if target in activated:
                    continue
                base = activated[current][0]
                activated[target] = [
                    Evidence(
                        description=f"{base.description} --{predicate}--> {target}",
                        matched_text=base.matched_text,
                        span=base.span,
                    )
                ]
                queue.append(target)
        return activated


class ConceptCondition(Condition):
    type_name = "concept"

    def __init__(self, ontology: Ontology, concept_id: str, direct_only: bool = False):
        if concept_id not in ontology.concepts:
            raise ConditionError(f"unknown ontology concept {concept_id!r}")
        self.ontology = ontology
        self.concept_id = concept_id
        self.direct_only = direct_only

    def evaluate(self, text: str) -> List[Evidence]:
        if self.direct_only:
            return self.ontology.concepts[self.concept_id].ground(text)
        return self.ontology.activate(text).get(self.concept_id, [])

    def to_dict(self) -> dict:
        return {
            "type": "concept",
            "concept": self.concept_id,
            "direct_only": self.direct_only,
        }


def register_concept_condition(ontology: Ontology) -> None:
    def factory(data: dict) -> ConceptCondition:
        concept_id = data.get("concept")
        if not concept_id:
            raise ConditionError("'concept' condition requires a 'concept' field")
        return ConceptCondition(ontology, concept_id, bool(data.get("direct_only", False)))

    register_condition_type("concept", factory)
