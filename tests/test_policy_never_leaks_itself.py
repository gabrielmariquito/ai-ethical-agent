"""A política não aparece nos lugares que descrevem a política, e eram duas
portas: a `description` de um bloco `not`, que despejava a lista inteira das
expressões que impedem a regra de disparar, e a mensagem de erro, que
imprimia o conteúdo da política na tela do funcionário: `REGISTRO`, "Texto movido do código".
"""

from __future__ import annotations

import json

import pytest

from ethical_agent import ActionContext, Policy, RuleBasedEngine, Stage, build_check_audit_record
from ethical_agent.conditions import ConditionError, condition_from_dict
from webui_support import RunningServer

# Uma regra com cláusula de ausência, igual em forma à R-TRANS-001 da política
# real: dispara quando um termo aparece SEM a expressão de isenção.
SEGREDO = "frase-que-desliga-a-regra"
POLICY_WITH_NOT = {
    "schema_version": "1.0",
    "metadata": {"version": "test"},
    "rules": [
        {
            "id": "R-NOT",
            "principle": "transparency",
            "deontic": "obligation",
            "severity": "low",
            "effect": "FLAG",
            "scopes": ["input"],
            "rationale": "exige uma isenção",
            "condition": {
                "type": "all",
                "conditions": [
                    {"type": "keyword", "value": "gatilho"},
                    {
                        "type": "not",
                        "condition": {
                            "type": "any",
                            "conditions": [
                                {"type": "keyword", "value": SEGREDO},
                                {"type": "keyword", "value": "outra-saida"},
                            ],
                        },
                    },
                ],
            },
        }
    ],
}


@pytest.fixture
def verdict():
    engine = RuleBasedEngine(Policy.from_dict(POLICY_WITH_NOT))
    return engine, engine.evaluate(ActionContext(content="tem gatilho aqui", stage=Stage.INPUT))


def test_the_rule_still_fires(verdict):
    # Sem isto, os testes abaixo passam por não haver evidência nenhuma.
    # NotCondition tem de continuar devolvendo evidência não-vazia, senão
    # AllCondition curto-circuita e a regra deixa de disparar.
    _, v = verdict
    assert [m.rule_id for m in v.matches] == ["R-NOT"]
    assert any("absence of" in e.description for m in v.matches for e in m.evidence)


def test_the_evidence_names_the_shape_not_the_contents(verdict):
    _, v = verdict
    descriptions = [e.description for m in v.matches for e in m.evidence]
    absence = [d for d in descriptions if d.startswith("absence of")]
    assert absence == ["absence of any of 2 conditions"], absence


@pytest.mark.parametrize(
    "surface",
    ["audit_record", "explain", "to_dict"],
)
def test_the_condition_does_not_reach_the_trail_the_cli_or_the_api(verdict, surface):
    engine, v = verdict
    if surface == "audit_record":
        text = json.dumps(
            build_check_audit_record(engine, v, Stage.INPUT, "tem gatilho aqui"),
            ensure_ascii=False,
        )
    elif surface == "explain":
        text = v.explain()
    else:
        text = json.dumps(v.to_dict(), ensure_ascii=False)

    assert SEGREDO not in text, f"{surface} carrega a expressão que desliga a regra"
    # A forma serializada da condição, que era o defeito original: um dict
    # Python impresso dentro da description. Estas chaves só aparecem se
    # alguém voltar a usar to_dict() ali.
    for marca in ("'conditions'", "'whole_word'", "'type':"):
        assert marca not in text, f"{surface}: {marca} indica condição serializada"


# ------------------------------------------- a mensagem de erro não se publica


BROKEN_POLICIES = {
    "condicao nao e objeto": [SEGREDO, "outra-saida"],
    "regex invalida": {"type": "regex", "pattern": f"(?P<{SEGREDO}"},
    "flag desconhecida": {"type": "regex", "pattern": SEGREDO, "flags": "z"},
}


@pytest.mark.parametrize("nome", sorted(BROKEN_POLICIES))
def test_a_malformed_condition_does_not_print_itself(nome):
    with pytest.raises(ConditionError) as excinfo:
        condition_from_dict(BROKEN_POLICIES[nome])
    assert SEGREDO not in str(excinfo.value), f"{nome}: a mensagem despeja o conteúdo"


def test_the_chat_error_does_not_carry_the_policy(tmp_path):
    # O caminho de maior exposição, ponta a ponta: o painel de configuração
    # deixa apontar `policy`, e o erro do job vai para a tela do funcionário.
    broken = tmp_path / "quebrada.json"
    broken.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "metadata": {"version": "x"},
                "rules": [
                    {
                        "id": "R-BAD",
                        "principle": "security",
                        "deontic": "prohibition",
                        "severity": "low",
                        "effect": "FLAG",
                        "scopes": ["input"],
                        "rationale": "r",
                        "condition": {"type": "regex", "pattern": f"(?P<{SEGREDO}"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    server = RunningServer(tmp_path, engine="rule")
    try:
        _, body, _ = server.post("/api/chat/new", {})
        _, job_body, _ = server.post(
            "/api/chat/message",
            {
                "conversation_id": body["conversation_id"],
                "text": "oi",
                "config": {"policy": str(broken)},
            },
        )
        job = server.wait_for_job(job_body["job_id"])
        assert job["phase"] == "error", job
        message = json.dumps(job["error"], ensure_ascii=False)
        assert "R-BAD" in message, "o erro tem de dizer QUAL regra, senão não é diagnóstico"
        assert SEGREDO not in message, "o erro do chat carrega o conteúdo da política"
    finally:
        server.close()
