"""`KNOWN_PRINCIPLES` é verificado e não apenas declarado, e a fronteira que
estes testes escrevem é que o campo `principle` dos datasets é **outro**
vocabulário com o mesmo nome — validá-los seria erro de categoria: `REGISTRO`, "Texto movido do código".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ethical_agent.ontology import Ontology, OntologyError
from ethical_agent.policy import Policy, PolicyError, default_policy_path
from ethical_agent.types import KNOWN_PRINCIPLES

REPO = Path(__file__).resolve().parent.parent


def _rule(principle: str) -> dict:
    return {
        "id": "R-X",
        "principle": principle,
        "deontic": "prohibition",
        "severity": "low",
        "effect": "FLAG",
        "scopes": ["input"],
        "rationale": "r",
        "condition": {"type": "keyword", "value": "x"},
    }


def _policy(principle: str) -> dict:
    return {"schema_version": "1.0", "metadata": {"version": "t"}, "rules": [_rule(principle)]}


# ------------------------------------------------------------------ política


def test_a_misspelt_principle_is_rejected():
    # O caso concreto: um acento a menos e um "c" no lugar do "ç".
    with pytest.raises(PolicyError) as excinfo:
        Policy.from_dict(_policy("beneficencia"))
    message = str(excinfo.value)
    assert "R-X" in message, "o erro tem de dizer QUAL regra"
    assert "beneficencia" in message, "e qual foi o valor recusado"


def test_the_reserved_principle_loads_without_complaint():
    # beneficence está na lista e não é usado por nenhuma regra hoje. Isso é
    # reserva deliberada, não sobra: encolher o vocabulário por falta de uso
    # atual seria decisão de política, não de dívida técnica.
    assert "beneficence" in KNOWN_PRINCIPLES
    policy = Policy.from_dict(_policy("beneficence"))
    assert policy.rules[0].principle == "beneficence"


@pytest.mark.parametrize("principle", sorted(KNOWN_PRINCIPLES))
def test_every_principle_in_the_vocabulary_is_accepted(principle):
    Policy.from_dict(_policy(principle))


def test_an_empty_principle_still_reports_the_older_error():
    # A validação nova não engole a antiga: faltar é diferente de ser
    # desconhecido, e as duas mensagens dizem coisas diferentes.
    with pytest.raises(PolicyError) as excinfo:
        Policy.from_dict(_policy(""))
    assert "missing 'principle'" in str(excinfo.value)


# ----------------------------------------------------------------- ontologia


def test_a_norm_with_an_unknown_principle_is_rejected():
    raw = {
        "schema_version": "1.0",
        "concepts": [{"id": "c1", "terms": [{"term": "x"}]}],
        "norms": [
            {
                "id": "N-X",
                "principle": "nao_existe",
                "deontic": "prohibition",
                "severity": "low",
                "effect": "DENY",
                "when": ["c1"],
            }
        ],
    }
    with pytest.raises(OntologyError) as excinfo:
        Ontology.from_dict(raw)
    assert "N-X" in str(excinfo.value)
    assert "nao_existe" in str(excinfo.value)


def test_a_concept_may_carry_no_principle_at_all():
    # Opcional no conceito, ao contrário da norma: um conceito é vocabulário
    # e pode não ter princípio próprio. A validação só vale quando preenchido.
    raw = {
        "schema_version": "1.0",
        "concepts": [{"id": "c1", "terms": [{"term": "x"}]}],
        "norms": [],
    }
    ontology = Ontology.from_dict(raw)
    assert ontology.concepts["c1"].principle == ""


# ------------------------------------------- o que já existe continua válido


def test_the_shipped_policy_and_ontology_still_load():
    # Se a validação rejeitasse algo do próprio projeto, seria mudança de
    # comportamento e não conserto.
    Policy.from_file(default_policy_path())


# ------------------------------------- a fronteira com o vocabulário do eval


@pytest.mark.parametrize("dataset", sorted((REPO / "eval").glob("dataset*.json")))
def test_datasets_are_not_validated_against_the_principle_vocabulary(dataset):
    # "benign" é o valor mais comum nos datasets e NÃO está em
    # `KNOWN_PRINCIPLES`, de propósito: ali quer dizer "nenhum princípio se
    # aplica": `REGISTRO`, "Texto movido do código".
    cases = json.loads(dataset.read_text(encoding="utf-8"))["cases"]
    used = {c.get("principle") for c in cases if c.get("principle")}
    assert used - KNOWN_PRINCIPLES, (
        f"{dataset.name} passou a usar só princípios do vocabulário -- se isso for "
        "intencional, a fronteira que este teste descreve mudou e vale reler o comentário "
        "em types.py"
    )
    assert "benign" in used
