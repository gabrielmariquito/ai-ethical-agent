"""Toda regra que isenta diz o que assume o lugar dela. Verificado, não confiado.

`suppressed_effect` nasce opcional, e opcional com default `None` reproduz
exatamente o comportamento que a leva do motor veio consertar: exceção casa,
regra sai, nada sucede. Isso é deliberado -- um default que rebaixasse daria a
todo bloco `exceptions` um sucessor que o autor nunca escreveu, que é o defeito
com roupa nova. O preço de manter o default inócuo é que o schema, sozinho,
volta a permitir a supressão sem sucessor na próxima regra que alguém escrever.

Este arquivo é o que cobra o preço. É a mesma disciplina de `4812a7e`
(KNOWN_PRINCIPLES passa a ser verificado, não apenas declarado) e de
`test_principles_are_checked.py`: a política deste repositório não pode ficar em
silêncio sobre o sucessor, mesmo que o carregador aceite silêncio de políticas
de terceiros.

**Por que teste e não erro de carga.** `Rule.from_dict` recusar `exceptions` sem
`suppressed_effect` quebraria toda política externa escrita antes deste campo
existir -- e o campo nasce nesta leva, então *toda* política externa é anterior
a ele. O erro de carga puniria quem não teve como saber. O teste cobra de quem
tem: este repositório.
"""
from __future__ import annotations

import pytest

from ethical_agent import Decision, Policy, PolicyError
from ethical_agent.policy import default_policy_path


@pytest.fixture(scope="module")
def policy():
    return Policy.from_file(default_policy_path())


def test_toda_regra_com_excecoes_declara_o_sucessor(policy):
    """O silêncio sobre o sucessor é uma decisão, e tem de estar escrita."""
    # Constraints entram junto: hoje o carregador já recusa `exceptions` num
    # hard constraint, mas essa recusa mora noutro `if` e varrer os dois aqui
    # custa nada e não depende dela continuar existindo.
    mudas = [
        r.id
        for r in [*policy.constraints, *policy.rules]
        if r.exceptions is not None and r.suppressed_effect is None
    ]
    assert not mudas, "\n".join(
        f"{rule_id} tem `exceptions` sem `suppressed_effect` declarado. "
        f"Supressão sem sucessor foi o defeito medido na Leva 2: 54 de 66 "
        f"células da grade de R-SEC-002 caíam para ALLOW com `matches` vazio, "
        f"e o único vestígio era uma linha em `suppressed` que não dizia se "
        f"algo tinha assumido. Declare o efeito que assume o lugar da regra "
        f"isenta -- ou `\"ALLOW\"`, se esta isenção libera o pedido de "
        f"propósito. `\"ALLOW\"` é resposta legítima; o que não é resposta é "
        f"não dizer."
        for rule_id in mudas
    )


def test_r_sec_002_rebaixa_para_rewrite(policy):
    """A decisão B2, fixada onde ela mora.

    Não é redundante com o teste acima: aquele cobra que *haja* sucessor, este
    cobra *qual*. Trocar REWRITE por FLAG aqui passaria pelo primeiro sem um
    ruído, e teria mudado o alcance da isenção sem nada acender.
    """
    regra = next(r for r in policy.rules if r.id == "R-SEC-002")
    assert regra.effect is Decision.DENY
    assert regra.suppressed_effect is Decision.REWRITE
    # Escrito para roubo de credencial, não emprestado de R-SEC-001 -- e com
    # `{content}`, senão o REWRITE substitui a pergunta inteira pelo template.
    assert regra.rewrite_template and "{content}" in regra.rewrite_template
    assert "credential" in regra.rewrite_template.lower()


@pytest.mark.parametrize(
    "mutacao, trecho",
    [
        pytest.param(
            {"suppressed_effect": "REWRITE", "exceptions": None},
            "without 'exceptions'",
            id="sucessor-sem-excecao",
        ),
        pytest.param(
            {"suppressed_effect": "DENY"},
            "not less restrictive",
            id="sucessor-nao-afrouxa",
        ),
        pytest.param(
            {"suppressed_effect": "GRITAR"},
            "invalid suppressed_effect",
            id="valor-invalido",
        ),
        pytest.param(
            {"suppressed_effect": "REWRITE", "rewrite_template": None},
            "requires 'rewrite_template'",
            id="rewrite-sem-template",
        ),
    ],
)
def test_o_schema_recusa_sucessores_incoerentes(mutacao, trecho):
    base = {
        "id": "R-TESTE",
        "principle": "security",
        "deontic": "prohibition",
        "severity": "high",
        "scopes": ["input"],
        "effect": "DENY",
        "condition": {"type": "keyword", "value": "gatilho"},
        "exceptions": {"type": "keyword", "value": "isento"},
        "suppressed_effect": "REWRITE",
        "rewrite_template": "reformulado: {content}",
    }
    dados = {**base, **mutacao}
    dados = {k: v for k, v in dados.items() if v is not None}

    from ethical_agent.policy import Rule

    with pytest.raises(PolicyError) as exc:
        Rule.from_dict(dados)
    assert trecho in str(exc.value), str(exc.value)


def test_rewrite_template_e_aceito_quando_so_o_sucessor_reescreve():
    """`effect: DENY` + `suppressed_effect: REWRITE` carrega template.

    Antes desta leva `rewrite_template` só era aceito em regra cujo `effect`
    fosse REWRITE, e essa recusa tornava B2 inexprimível: R-SEC-002 nega, e só
    a versão rebaixada dela reescreve.
    """
    from ethical_agent.policy import Rule

    regra = Rule.from_dict(
        {
            "id": "R-TESTE",
            "principle": "security",
            "deontic": "prohibition",
            "severity": "high",
            "scopes": ["input"],
            "effect": "DENY",
            "condition": {"type": "keyword", "value": "gatilho"},
            "exceptions": {"type": "keyword", "value": "isento"},
            "suppressed_effect": "REWRITE",
            "rewrite_template": "reformulado: {content}",
        }
    )
    assert regra.effect is Decision.DENY
    assert regra.suppressed_effect is Decision.REWRITE
    assert regra.rewrite_template == "reformulado: {content}"


def test_allow_e_declaravel_como_sucessor_mas_nao_como_efeito():
    """A assimetria é o ponto, não um descuido.

    ALLOW como `effect` seria uma regra que decide não decidir -- a ausência de
    regra já significa isso. ALLOW como `suppressed_effect` é a única forma de
    escrever "esta isenção libera de propósito", que era o comportamento tácito
    de todo bloco `exceptions` até esta leva.
    """
    from ethical_agent.policy import Rule

    base = {
        "id": "R-TESTE",
        "principle": "security",
        "deontic": "prohibition",
        "severity": "high",
        "scopes": ["input"],
        "condition": {"type": "keyword", "value": "gatilho"},
        "exceptions": {"type": "keyword", "value": "isento"},
    }

    regra = Rule.from_dict({**base, "effect": "DENY", "suppressed_effect": "ALLOW"})
    assert regra.suppressed_effect is Decision.ALLOW

    with pytest.raises(PolicyError) as exc:
        Rule.from_dict({**base, "effect": "ALLOW"})
    assert "effect must be one of" in str(exc.value)
