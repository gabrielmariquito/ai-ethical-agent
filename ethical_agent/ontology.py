from __future__ import annotations

import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from .conditions import Condition, ConditionError, register_condition_type
from .provenance import ConfigArtifact
from .types import KNOWN_PRINCIPLES, Decision, Evidence, Severity, Stage

PROPAGATING_PREDICATES = {"is_a", "part_of", "implies"}

_VALID_NORM_EFFECTS = {Decision.DENY, Decision.FLAG}
_VALID_DEONTICS = {"prohibition", "obligation"}

MAX_GROUND_EVIDENCE = 10


# Guardas de frame que uma norma pode declarar. Uma só hoje, e a lista existe
# para que declarar uma inexistente seja erro de carga em vez de guarda que
# nunca dispara.
GUARDAS_DE_FRAME = ("recusa",)

# Fonte da qual um conceito veio. Ver `Concept.source`.
FONTE_RELAIEO = "relaieo"
FONTE_DANO = "harm"


class OntologyError(ValueError):
    def __init__(self, errors: List[str]):
        self.errors = errors
        super().__init__("invalid ontology:\n" + "\n".join(f"- {e}" for e in errors))


def _fonte_provavel(ref: str, concepts: dict) -> str:
    """Sufixo de diagnóstico dizendo em que fontes o id **não** está.

    A ontologia é a união de duas fontes e `from_dict` já recebe tudo achatado;
    sem isto, "unknown concept 'x'" não diz se o autor errou o nome ou esqueceu
    de declarar o conceito no arquivo da taxonomia.
    """
    fontes = sorted({c.source for c in concepts.values() if c.source})
    if not fontes:
        return ""
    return f" (não está em nenhuma das fontes carregadas: {', '.join(fontes)})"


def _erros_de_guarda_de_frame(norm_id, raw, when, unless_frame, scopes, concepts) -> List[str]:
    """`H-1` e `H-2`: a guarda de frame é declarada, e prende a norma à saída.

    `H-1` existe pelo mesmo motivo que `policy.py` recusa `suppressed_effect`
    sem `exceptions`: sem obrigar a declaração, uma norma de dano **sem** guarda
    é indistinguível de uma norma de dano cujo autor não pensou no assunto, e a
    escolha some do arquivo que o auditor lê.

    `H-2` prende a guarda à saída. Aqui a prisão **não** é por impossibilidade
    técnica -- o motor do grafo enxerga o `stage` (`kg_engine.evaluate`), ao
    contrário de uma `Condition`, que só recebe texto. É para que a escolha
    fique legível no arquivo em vez de implícita no motor, e porque uma norma de
    dano com guarda de recusa valendo na entrada isentaria "I'm sorry, how do I
    stalk her" -- a porta que `policy._erros_de_frame` fechou do outro lado.
    """
    errors: List[str] = []

    if unless_frame is not None and unless_frame not in GUARDAS_DE_FRAME:
        errors.append(
            f"{norm_id}: unknown frame guard {unless_frame!r}, "
            f"expected one of {sorted(GUARDAS_DE_FRAME)} or null"
        )

    de_dano = [ref for ref in when
               if ref in concepts and concepts[ref].source == FONTE_DANO]
    if de_dano and "unless_frame" not in raw:
        errors.append(
            f"{norm_id}: norm over harm concept(s) {sorted(de_dano)} must declare "
            f"'unless_frame' explicitly (\"recusa\" or null) -- an undeclared guard "
            f"is indistinguishable from an unconsidered one"
        )

    if unless_frame is not None and scopes and scopes != {Stage.OUTPUT}:
        errors.append(
            f"{norm_id}: 'unless_frame' requires scopes exactly ['output']; "
            f"got {sorted(s.value for s in scopes)}"
        )

    return errors


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
    # De qual fonte este conceito veio: "relaieo" (upstream vendorizado) ou
    # "harm" (nossa taxonomia). A ontologia é montada da união de duas fontes e
    # `from_dict` recebe um dicionário já achatado, então a origem tem de viajar
    # com o conceito -- é ela que permite dizer de onde veio um id desconhecido,
    # e é ela que a validação `H-1` consulta para exigir guarda declarada.
    source: str = ""
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

    def ground(
        self, text: str, limit: Optional[int] = MAX_GROUND_EVIDENCE
    ) -> List[Evidence]:
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
                if limit is not None and len(evidence) >= limit:
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
    # Guarda de frame, **declarada e nunca inferida** -- mesma doutrina de
    # `suppressed_effect`: uma norma que não declara guarda diz que não declara,
    # em vez de herdar uma que ninguém escreveu. `None` é "sem guarda", e para
    # norma de dano é escolha escrita, não omissão (validação `H-1`).
    unless_frame: Optional[str] = None
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
    # {role: caminho} dos arquivos que produziram esta ontologia. Um único
    # `from_file` deixa {"ontology": ...}; `relaieo.load_relaieo` deixa até
    # três, porque a ontologia padrão é montada de três arquivos com ciclos de
    # vida diferentes -- o TTL é upstream vendorizado, grounding e norms são
    # nossos. Vazio quando a ontologia veio de `from_dict`.
    source_paths: Dict[str, Path] = field(default_factory=dict)

    # De onde sai a versão declarada de cada papel. O TTL não tem nenhuma:
    # `relaieo._relaieo_to_ontology_dict` monta o metadata do upstream com
    # name/source/creators/license/note e nada de version, porque o arquivo é
    # vendorizado verbatim e o upstream não declara uma. Para ele o digest não
    # confere a versão declarada -- é a **única** identidade que ele tem.
    _CHAVE_DE_VERSAO = {
        "ontology": "version",
        "grounding": "grounding_version",
        "norms": "norms_version",
        "ontology_ttl": None,
        # A taxonomia de dano é nossa, mas o TTL segue sem versão declarada pelo
        # mesmo motivo que o upstream: o formato não a carrega. Para os dois, o
        # digest é a única identidade. Papel não registrado aqui cairia no
        # fallback "version" e reportaria `None` em silêncio.
        "harm_ttl": None,
        "harm_grounding": "harm_grounding_version",
        "harm_norms": "harm_norms_version",
    }

    def config_artifacts(self) -> List["ConfigArtifact"]:
        artefatos = []
        for role, caminho in sorted(self.source_paths.items()):
            chave = self._CHAVE_DE_VERSAO.get(role, "version")
            artefatos.append(ConfigArtifact(
                role=role,
                version=self.metadata.get(chave) if chave else None,
                path=str(caminho) if caminho else None,
            ))
        return artefatos

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
            concept_principle = raw.get("principle", "")
            # Optional on a concept (unlike a norm), so only checked when
            # filled -- a concept is a piece of vocabulary and may carry no
            # principle of its own.
            if concept_principle and concept_principle not in KNOWN_PRINCIPLES:
                errors.append(
                    f"{concept_id}: unknown principle {concept_principle!r}, "
                    f"expected one of {sorted(KNOWN_PRINCIPLES)}"
                )
            concepts[concept_id] = Concept(
                id=concept_id,
                label=raw.get("label", concept_id),
                principle=concept_principle,
                description=raw.get("description", ""),
                provocation=raw.get("provocation", ""),
                references=list(raw.get("references", [])),
                terms=terms,
                source=raw.get("source", ""),
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

            norm_principle = raw.get("principle", "")
            # Required on a norm: a norm that fires produces a RuleMatch, and
            # a match nobody can classify by principle is a decision the
            # report cannot group and the screen cannot translate.
            if norm_principle and norm_principle not in KNOWN_PRINCIPLES:
                errors.append(
                    f"{norm_id}: unknown principle {norm_principle!r}, "
                    f"expected one of {sorted(KNOWN_PRINCIPLES)}"
                )

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
                    fonte = _fonte_provavel(ref, concepts)
                    errors.append(f"{norm_id}: unknown concept {ref!r}{fonte}")

            unless_frame = raw.get("unless_frame")
            errors.extend(
                _erros_de_guarda_de_frame(norm_id, raw, when, unless_frame, scopes, concepts)
            )

            norms.append(
                Norm(
                    id=norm_id,
                    principle=norm_principle,
                    deontic=deontic,
                    severity=severity,
                    effect=effect,
                    scopes=frozenset(scopes),
                    when=when,
                    unless=unless,
                    unless_frame=unless_frame,
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
        ontology = cls.from_dict(data)
        ontology.source_paths = {"ontology": path}
        return ontology

    def activate(
        self, text: str, limit: Optional[int] = MAX_GROUND_EVIDENCE
    ) -> Dict[str, List[Evidence]]:
        activated: Dict[str, List[Evidence]] = {}
        queue = deque()
        for concept in self.concepts.values():
            evidence = concept.ground(text, limit=limit)
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

    def evaluate(
        self, text: str, limit: Optional[int] = MAX_GROUND_EVIDENCE
    ) -> List[Evidence]:
        if self.direct_only:
            return self.ontology.concepts[self.concept_id].ground(text, limit=limit)
        return self.ontology.activate(text, limit=limit).get(self.concept_id, [])

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
