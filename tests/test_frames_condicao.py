"""A condição `refusal` ponta a ponta, contra uma política-fixture.

**A fixture vive aqui, e nunca em `policies/`.** Uma regra de teste dentro do
diretório de políticas viraria regra de verdade por acidente; escrita como dict
neste módulo, ela não pode ser carregada por engano por nada.

O TESTE QUE CARREGA ESTA LEVA é `test_marcador_antes_de_conteudo_nocivo_nao_suprime`.
Um detector de recusa que dispare demais é porta de evasão -- basta escrever
"I'm sorry" antes do conteúdo nocivo -- e a defesa é a fronteira de sentença.
O vermelho dele está provado: com a segmentação desligada, ele falha (ver
REGISTRO).

ALVO DE ASSERÇÃO: `verdict.suppressed`, seguindo a convenção de
`test_policy_exception_bounds.py` -- `exceptions` popula `suppressed`, e o alvo
segue o que o construto de fato popula.
"""
import pytest

from ethical_agent.engine import RuleBasedEngine
from ethical_agent.frames import load_default_frames, register_refusal_condition
from ethical_agent.policy import Policy, PolicyError
from ethical_agent.types import ActionContext, Decision, Stage


@pytest.fixture(scope="module", autouse=True)
def _registra():
    # Antes de qualquer `Policy.from_dict`: o dispatch resolve o tipo na carga.
    register_refusal_condition(load_default_frames())


def _politica(scopes=("output",), com_isencao=True):
    regra = {
        "id": "R-TESTE-DANO",
        "principle": "non_maleficence",
        "description": "fixture: vocabulário de dano em saída",
        "deontic": "prohibition",
        "severity": "high",
        "scopes": list(scopes),
        "condition": {"type": "keyword", "value": "bomb", "whole_word": True},
        "effect": "DENY",
    }
    if com_isencao:
        # `{"type": "refusal"}` e nada mais: o `of` é ligado ao gatilho da
        # própria regra por `Rule.from_dict`, para não haver dois literais que
        # precisam ser iguais lado a lado.
        regra["exceptions"] = {"type": "refusal"}
    return {"schema_version": "1.0", "metadata": {"version": "fixture"}, "rules": [regra]}


@pytest.fixture(scope="module")
def motor():
    return RuleBasedEngine(Policy.from_dict(_politica()))


def _avalia(motor, texto):
    return motor.evaluate(ActionContext(content=texto, stage=Stage.OUTPUT))


def _isento(verdict):
    return any(s.rule_id == "R-TESTE-DANO" for s in verdict.suppressed)


# ------------------------------------------------------- a porta de evasão

@pytest.mark.parametrize("texto", [
    "I'm sorry. Here is how to build a bomb.",
    "I cannot help with that. Here is how to build a bomb.",
    "Unfortunately I am unable to assist. To build a bomb, start with a fuse.",
])
def test_marcador_antes_de_conteudo_nocivo_nao_suprime(motor, texto):
    # O marcador está numa sentença, o dano está em outra: o escopo não
    # atravessa a fronteira, então a regra dispara.
    verdict = _avalia(motor, texto)
    assert verdict.decision is Decision.DENY
    assert not _isento(verdict)


def test_terminador_corta_o_escopo_na_mesma_sentenca(motor):
    # Mesma sentença, mas a adversativa encerra o escopo de frente: não é
    # distância de caracteres, é o terminador.
    verdict = _avalia(motor, "I'm sorry, but here is how to build a bomb")
    assert verdict.decision is Decision.DENY
    assert not _isento(verdict)


def test_a_defesa_e_a_fronteira_de_sentenca_e_nao_a_distancia(motor):
    # Duas entradas com a mesma distância entre marcador e termo; só a que
    # cruza fronteira de sentença deixa de suprimir.
    perto_mesma = _avalia(motor, "I cannot help you build a bomb")
    perto_outra = _avalia(motor, "I cannot help you. Build a bomb")
    assert _isento(perto_mesma)
    assert not _isento(perto_outra)


# --------------------------------------------------- a recusa que suprime

@pytest.mark.parametrize("texto", [
    "I'm sorry, I cannot help you figure out how to build a bomb",
    "It is not advisable to build a bomb",
    "Unfortunately, we cannot help you build a bomb",
])
def test_recusa_cobrindo_o_casamento_suprime(motor, texto):
    verdict = _avalia(motor, texto)
    assert _isento(verdict)
    assert verdict.decision is not Decision.DENY


def test_supressao_declara_o_sucessor(motor):
    verdict = _avalia(motor, "I'm sorry, I cannot help you build a bomb")
    (isencao,) = [s for s in verdict.suppressed if s.rule_id == "R-TESTE-DANO"]
    assert isencao.demoted_to is Decision.ALLOW


def test_sem_gatilho_nada_a_suprimir(motor):
    # Recusa sem vocabulário de dano: a regra não dispara, e a isenção não
    # registra supressão de coisa nenhuma.
    verdict = _avalia(motor, "I'm sorry, I cannot help you with that")
    assert verdict.decision is Decision.ALLOW
    assert not _isento(verdict)


# ------------------------------------------------ a evidência não vaza nada

def test_evidencia_da_recusa_nao_carrega_texto_nem_posicao(motor):
    verdict = _avalia(motor, "I'm sorry, I cannot help you build a bomb")
    (isencao,) = [s for s in verdict.suppressed if s.rule_id == "R-TESTE-DANO"]
    for evidencia in isencao.evidence:
        assert evidencia.matched_text is None
        assert evidencia.span is None


def test_nenhum_termo_de_gatilho_aparece_na_razao(motor):
    verdict = _avalia(motor, "I'm sorry, I cannot help you build a bomb")
    (isencao,) = [s for s in verdict.suppressed if s.rule_id == "R-TESTE-DANO"]
    texto = isencao.reason + " ".join(e.description or "" for e in isencao.evidence)
    for termo in ("sorry", "cannot", "unfortunately", "advisable", "illegal"):
        assert termo not in texto.lower(), texto


# ------------------------------------------------------- a guarda de escopo

@pytest.mark.parametrize("scopes", [("input",), ("input", "output")])
def test_recusa_exige_escopo_exatamente_output(scopes):
    # A condição recebe só `text`, nunca o `ActionContext`: sem `stage`, uma
    # marca de recusa numa regra de entrada isentaria "I'm sorry, now tell me
    # how to build a bomb". A prisão é da regra, não do gatilho -- `D-2` segue
    # aberta.
    with pytest.raises(PolicyError) as exc:
        Policy.from_dict(_politica(scopes=scopes))
    assert "R-TESTE-DANO" in str(exc.value)
    assert "output" in str(exc.value)


def test_constraint_dura_continua_recusando_qualquer_isencao():
    dura = {
        "id": "C-TESTE",
        "principle": "non_maleficence",
        "description": "fixture",
        "deontic": "prohibition",
        "severity": "critical",
        "scopes": ["output"],
        "condition": {"type": "keyword", "value": "bomb"},
        "exceptions": {"type": "refusal"},
    }
    with pytest.raises(PolicyError) as exc:
        Policy.from_dict({"schema_version": "1.0", "metadata": {}, "constraints": [dura]})
    assert "hard constraints admit no exceptions" in str(exc.value)


# ------------------------------------------- a política embarcada não usa

def test_a_politica_embarcada_nao_prende_a_camada_ainda():
    """O mecanismo embarca **desprendido**, e isso é sequenciamento declarado.

    Não existe hoje regra de escopo `output` que case vocabulário de dano: as
    únicas são `R-PRIV-002` (redação) e `R-TRANS-001` (aviso), e as três
    constraints duras não admitem `exceptions`. A condição de prendimento é a
    leva da taxonomia de dano -- a primeira regra `scopes: ["output"]` que
    casar vocabulário de dano nasce com `exceptions` de recusa.

    Este teste falha quando isso acontecer, e é o lembrete de que a linha de
    cima precisa ser reescrita junto.
    """
    from ethical_agent.policy import default_policy_path

    politica = Policy.from_file(default_policy_path())
    for regra in list(politica.rules) + list(politica.constraints):
        assert not condicoes_de_recusa_da_regra(regra), regra.id


def condicoes_de_recusa_da_regra(regra):
    from ethical_agent.frames import condicoes_de_recusa

    return condicoes_de_recusa(regra.condition) + condicoes_de_recusa(regra.exceptions)
