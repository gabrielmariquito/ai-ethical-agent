from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .ontology import Ontology, OntologyError

RELAIEO_NS = "http://www.ontology.audit4sg.org/RelAIEO#"
DC_DESCRIPTION = "http://purl.org/dc/elements/1.1/description"

_STRUCTURAL = set(";,.()[]")


def _tokenize(text: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in " \t\r\n":
            i += 1
            continue
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "@":
            while i < n and text[i] != ".":
                i += 1
            i += 1
            continue
        if ch in _STRUCTURAL:
            tokens.append(("punc", ch))
            i += 1
            continue
        if ch == "<":
            j = text.find(">", i + 1)
            if j == -1:
                raise OntologyError(["unterminated IRI in turtle source"])
            tokens.append(("iri", text[i + 1 : j]))
            i = j + 1
            continue
        if ch == '"':
            if text.startswith('"""', i):
                j = i + 3
                buf = []
                while j < n:
                    c = text[j]
                    if c == "\\" and j + 1 < n:
                        buf.append(text[j : j + 2])
                        j += 2
                        continue
                    if c == '"' and text.startswith('"""', j):
                        break
                    buf.append(c)
                    j += 1
                if j >= n:
                    raise OntologyError(["unterminated triple-quoted string"])
                tokens.append(("str", _unescape("".join(buf))))
                i = j + 3
            else:
                j = i + 1
                buf = []
                while j < n:
                    c = text[j]
                    if c == "\\" and j + 1 < n:
                        buf.append(text[j : j + 2])
                        j += 2
                        continue
                    if c == '"':
                        break
                    buf.append(c)
                    j += 1
                tokens.append(("str", _unescape("".join(buf))))
                i = j + 1
            while i < n and text[i] in "@^":
                if text[i] == "@":
                    i += 1
                    while i < n and (text[i].isalnum() or text[i] == "-"):
                        i += 1
                else:
                    i += 2
                    if i <= n and text[i - 1 : i + 1] == "<<":
                        pass
                    while i < n and text[i] not in " \t\r\n;,.":
                        i += 1
            continue
        j = i
        while j < n and text[j] not in " \t\r\n" and text[j] not in _STRUCTURAL and text[j] != "<" and text[j] != '"':
            j += 1
        tokens.append(("name", text[i:j]))
        i = j
    return tokens


def _unescape(value: str) -> str:
    return (
        value.replace("\\\"", '"')
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace("\\\\", "\\")
    )


def _statements(tokens: List[Tuple[str, str]]):
    statement: List[Tuple[str, str]] = []
    for kind, value in tokens:
        if kind == "punc" and value == ".":
            if statement:
                yield statement
                statement = []
            continue
        statement.append((kind, value))
    if statement:
        yield statement


def _local(kind: str, value: str) -> Optional[str]:
    if kind == "name":
        if value.startswith(":"):
            return value[1:]
        return None
    if kind == "iri":
        if value.startswith(RELAIEO_NS):
            return value[len(RELAIEO_NS) :]
        return None
    return None


def _parse_predicate_objects(statement: List[Tuple[str, str]]):
    subject = statement[0]
    groups: List[Tuple[Tuple[str, str], List[Tuple[str, str]]]] = []
    i = 1
    predicate: Optional[Tuple[str, str]] = None
    objects: List[Tuple[str, str]] = []
    depth = 0
    while i < len(statement):
        kind, value = statement[i]
        if kind == "punc" and value in "([":
            depth += 1
            i += 1
            continue
        if kind == "punc" and value in ")]":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth > 0:
            i += 1
            continue
        if kind == "punc" and value == ";":
            if predicate is not None:
                groups.append((predicate, objects))
            predicate, objects = None, []
            i += 1
            continue
        if kind == "punc" and value == ",":
            i += 1
            continue
        if predicate is None:
            predicate = (kind, value)
        else:
            objects.append((kind, value))
        i += 1
    if predicate is not None:
        groups.append((predicate, objects))
    return subject, groups


_PRINCIPLE_BY_CONCEPT = {
    "bias": "fairness",
    "inequality": "fairness",
    "exclusionary_norm": "fairness",
    "non_discrimination": "fairness",
    "surveillance": "privacy",
    "threat_to_privacy": "privacy",
    "respects_privacy": "privacy",
    "hate_speech": "non_maleficence",
    "defamation": "non_maleficence",
    "information_disorder": "non_maleficence",
    "censorship": "non_maleficence",
    "weakening_of_democracy": "non_maleficence",
    "deskilling": "autonomy",
    "environmental_impact": "non_maleficence",
    "fairness": "fairness",
    "justice": "fairness",
    "equity": "fairness",
    "transparency_and_trust": "transparency",
    "explainability": "transparency",
    "responsibility": "accountability",
    "ethic_washing": "transparency",
    "ethic_shopping": "transparency",
    "ethic_dumping": "accountability",
}


def _prettify(local: str) -> str:
    return local.replace("_", " ")


def parse_relaieo(ttl_text: str) -> dict:
    tokens = _tokenize(ttl_text)
    subjects: Dict[str, dict] = {}
    for statement in _statements(tokens):
        if not statement:
            continue
        subj_kind, subj_value = statement[0]
        if subj_kind == "punc":
            continue
        subj_local = _local(subj_kind, subj_value)
        if subj_local is None:
            continue
        subject, groups = _parse_predicate_objects(statement)
        record = subjects.setdefault(
            subj_local,
            {"types": set(), "subClassOf": [], "domain": [], "range": [],
             "comment": [], "provocation": [], "references": [], "label": []},
        )
        for (pk, pv), objects in groups:
            pred = pv
            if pk == "name" and pv == "a":
                pred = "rdf:type"
            for ok, ov in objects:
                if pred == "rdf:type":
                    if ok == "name":
                        record["types"].add(ov)
                elif pred == "rdfs:subClassOf":
                    local = _local(ok, ov)
                    if local:
                        record["subClassOf"].append(local)
                elif pred == "rdfs:domain":
                    local = _local(ok, ov)
                    if local:
                        record["domain"].append(local)
                elif pred == "rdfs:range":
                    local = _local(ok, ov)
                    if local:
                        record["range"].append(local)
                elif pred in ("rdfs:comment", DC_DESCRIPTION):
                    if ok == "str":
                        record["comment"].append(ov)
                elif pred == "rdfs:provocation":
                    if ok == "str":
                        record["provocation"].append(ov)
                elif pred == "rdfs:references":
                    if ok == "str":
                        record["references"].append(ov)
                elif pred == "rdfs:label":
                    if ok == "str":
                        record["label"].append(ov)
    return subjects


def _relaieo_to_ontology_dict(subjects: dict) -> dict:
    concepts = []
    relations = []
    for local, record in subjects.items():
        if "owl:Class" in record["types"]:
            concepts.append(
                {
                    "id": local,
                    "label": record["label"][0] if record["label"] else _prettify(local),
                    "principle": _PRINCIPLE_BY_CONCEPT.get(local, ""),
                    "description": " ".join(record["comment"]).strip(),
                    "provocation": " ".join(record["provocation"]).strip(),
                    "references": list(record["references"]),
                    "terms": [],
                }
            )
            for parent in record["subClassOf"]:
                relations.append(
                    {"subject": local, "predicate": "is_a", "object": parent}
                )
    class_ids = {c["id"] for c in concepts}
    for local, record in subjects.items():
        if "owl:ObjectProperty" not in record["types"]:
            continue
        for dom in record["domain"]:
            for rng in record["range"]:
                if dom in class_ids and rng in class_ids:
                    relations.append(
                        {"subject": dom, "predicate": local, "object": rng}
                    )
    return {
        "schema_version": "1.0",
        "metadata": {
            "name": "Relational AI Ethics Ontology (RelAIEO)",
            "source": "https://ontology.audit4sg.org/",
            "creators": ["Cheshta Arora", "Debarun Sarkar"],
            "license": "GNU General Public License v3",
            "note": "Upstream ontology loaded verbatim from relaieo.ttl; concepts carry rdfs:comment (description), rdfs:provocation and rdfs:references.",
        },
        "concepts": concepts,
        "relations": relations,
        "norms": [],
    }


def _apply_grounding(data: dict, grounding: dict) -> None:
    errors: List[str] = []
    by_id = {c["id"]: c for c in data["concepts"]}
    for concept_id, terms in grounding.items():
        concept = by_id.get(concept_id)
        if concept is None:
            errors.append(f"grounding references unknown RelAIEO concept: {concept_id!r}")
            continue
        for term in terms:
            if isinstance(term, str):
                concept["terms"].append({"term": term})
            elif isinstance(term, dict) and term.get("term"):
                concept["terms"].append(
                    {"term": term["term"], "regex": bool(term.get("regex", False))}
                )
            else:
                errors.append(f"{concept_id}: invalid grounding term {term!r}")
    if errors:
        raise OntologyError(errors)


def load_relaieo(
    ttl_path: Union[str, Path],
    grounding_path: Optional[Union[str, Path]] = None,
    norms_path: Optional[Union[str, Path]] = None,
) -> Ontology:
    ttl_path = Path(ttl_path)
    subjects = parse_relaieo(ttl_path.read_text(encoding="utf-8"))
    data = _relaieo_to_ontology_dict(subjects)

    if grounding_path is not None:
        with Path(grounding_path).open(encoding="utf-8") as handle:
            grounding_doc = json.load(handle)
        _apply_grounding(data, grounding_doc.get("grounding", grounding_doc))

    if norms_path is not None:
        with Path(norms_path).open(encoding="utf-8") as handle:
            norms_doc = json.load(handle)
        data["norms"] = norms_doc.get("norms", norms_doc)

    return Ontology.from_dict(data)


def default_relaieo_ttl() -> Path:
    return Path(__file__).resolve().parents[1] / "ontologies" / "relaieo.ttl"


def default_grounding_path() -> Path:
    return Path(__file__).resolve().parents[1] / "ontologies" / "relaieo_grounding.json"


def default_norms_path() -> Path:
    return Path(__file__).resolve().parents[1] / "ontologies" / "relaieo_norms.json"


def load_default_ontology() -> Ontology:
    return load_relaieo(
        default_relaieo_ttl(), default_grounding_path(), default_norms_path()
    )
