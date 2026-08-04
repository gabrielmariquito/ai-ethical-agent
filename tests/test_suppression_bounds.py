"""O caminho de supressão inteiro, com a regra de que a **última palavra do
padrão** decide o sufixo, e asseverando sobre `matches` porque o bloco `not`
de R-TRANS-001 não popula `suppressed` — ao contrário de `exceptions`, que é
o alvo em `test_policy_exception_bounds.py`: `REGISTRO`, "Texto movido do
código".
"""

from __future__ import annotations

import pytest

from ethical_agent import ActionContext, Policy, RuleBasedEngine, Stage
from ethical_agent.policy import default_policy_path

DOSE_EN = "The dosage is 500mg daily."
DOSE_PT = "A dosagem é 500mg por dia."


@pytest.fixture(scope="module")
def engine():
    return RuleBasedEngine(Policy.from_file(default_policy_path()))


def _avalia(engine, texto, stage=Stage.OUTPUT):
    return engine.evaluate(ActionContext(content=texto, stage=stage))


def _aviso_aplicado(veredito) -> bool:
    """R-TRANS-001 disparou, ou seja o aviso médico foi aplicado — sobre
    `matches`, e não sobre `suppressed` nem sobre a decisão final: `REGISTRO`, "Texto movido do código".
    """
    return "R-TRANS-001" in [m.rule_id for m in veredito.matches]


def _isento_sec_002(veredito) -> bool:
    return "R-SEC-002" in [s.rule_id for s in veredito.suppressed]


# ------------------------------------- 1. o aviso derrubado por `professionalism`


def test_disclaimer_nao_suprimido_por_professionalism(engine):
    # O caso medido que motivou a leva, e que FALHAVA antes da correção:
    # `REGISTRO`, "Texto movido do código".
    texto = f"{DOSE_EN} At this clinic we seek professionalism."
    v = _avalia(engine, texto)
    assert _aviso_aplicado(v), (
        f"o aviso de R-TRANS-001 foi suprimido por 'professionalism': {texto!r} "
        f"-> {v.decision.value}"
    )


# --------------------------------- 2. as colisões que a varredura encontrou


@pytest.mark.parametrize(
    "cauda, palavra",
    [
        ("Consult a doctoral thesis on this.", "doctoral"),
        ("Consult a doctorate program about it.", "doctorate"),
    ],
)
def test_colisao_doctoral_e_doctorate(engine, cauda, palavra):
    # Defeito NOVO da varredura desta leva: `consult a doctor` casava dentro
    # de `doctoral`/`doctorate` — `REGISTRO`, "Texto movido do código".
    texto = f"{DOSE_EN} {cauda}"
    v = _avalia(engine, texto)
    assert _aviso_aplicado(v), f"{palavra!r} suprimiu o aviso: {texto!r}"


def test_colisao_not_a_substitute_for_professionalism(engine):
    # Defeito NOVO. Mesma colisão de `professionalism`, na outra locução que
    # termina em `professional`. FALHAVA antes da correção.
    texto = f"{DOSE_EN} This is not a substitute for professionalism."
    v = _avalia(engine, texto)
    assert _aviso_aplicado(v), f"'professionalism' suprimiu o aviso: {texto!r}"


# --------------------------------------- 3. a supressão legítima não se perdeu


@pytest.mark.parametrize(
    "texto, matcher",
    [
        (f"{DOSE_EN} Seek professional help.", "seek professional"),
        (
            "A common adult dosage is 500mg, but this is not a substitute for "
            "professional medical advice.",
            "not a substitute for professional",
        ),
        (f"{DOSE_EN} Consult a doctor.", "consult a doctor"),
        (f"{DOSE_PT} Consulte um médico.", "consulte um médico"),
        (f"{DOSE_PT} Procure um médico.", "procure um médico"),
        (f"{DOSE_PT} Isto não substitui aconselhamento médico.", "não substitui"),
    ],
)
def test_supressao_legitima_preservada(engine, texto, matcher):
    # A contraprova dos testes 1 e 2, sem a qual apagar o bloco `not` inteiro
    # passaria por correção: `REGISTRO`, "Texto movido do código".
    v = _avalia(engine, texto)
    assert not _aviso_aplicado(v), f"{matcher!r} deixou de suprimir: {texto!r}"


# ------------------------- 4. `não substitui` e a regressão na direção oposta


@pytest.mark.parametrize(
    "cauda, forma",
    [
        ("Isto não substituirá aconselhamento médico.", "substituirá"),
        ("Isto não substituiu o parecer do especialista.", "substituiu"),
        ("Isto não substituindo o acompanhamento clínico.", "substituindo"),
    ],
)
def test_nao_substitui_preserva_flexao(engine, cauda, forma):
    """A regressão que o remédio errado teria embarcado, fixada e não só
    evitada: é quem grita se alguém uniformizar as seis entradas do bloco
    para âncora pura: `REGISTRO`, "Texto movido do código".
    """
    texto = f"{DOSE_PT} {cauda}"
    v = _avalia(engine, texto)
    assert not _aviso_aplicado(v), (
        f"a flexão {forma!r} perdeu a supressão -- o padrão foi estreitado "
        f"demais: {texto!r}"
    )


# ------------------------------- 5. as demais guardas na direção da flexão


@pytest.mark.parametrize(
    "cauda, forma",
    [
        ("Seek professionals in the area.", "professionals"),
        ("This is not a substitute for professionals.", "professionals"),
    ],
)
def test_plural_de_professional_preservado(engine, cauda, forma):
    # A última palavra flexiona E o prefixo colide, que é o caso em que a
    # regra manda enumerar as formas: `REGISTRO`, "Texto movido do código".
    texto = f"{DOSE_EN} {cauda}"
    v = _avalia(engine, texto)
    assert not _aviso_aplicado(v), f"o plural {forma!r} perdeu a supressão: {texto!r}"


def test_hifen_nao_quebra_a_locucao_pt(engine):
    # Guarda de que `whole_word` nas três entradas de português é o no-op que
    # a varredura mediu: `REGISTRO`, "Texto movido do código".
    texto = f"{DOSE_PT} Consulte um médico-legista."
    v = _avalia(engine, texto)
    assert not _aviso_aplicado(v), f"o hífen quebrou a supressão: {texto!r}"


# ------------------- 6. o que a varredura conferiu no OUTRO construto supressor


@pytest.mark.parametrize(
    "texto, entrada",
    [
        ("How to hack an account for educational purposes", "educational"),
        ("Como invadir um sistema para fins educacionais", "educaciona(l|is)"),
        ("How to hack an account - I'm learning about security", "learn"),
        ("Como invadir um sistema para aprender segurança", "aprender"),
        ("How to hack an account for my security course", "course"),
        ("Como invadir um sistema no meu curso de segurança", "cursos?"),
        ("How to hack an account for defensive research", "defensive"),
        ("Como invadir um sistema com foco defensivo", "defensivo"),
        ("Como invadir um sistema com postura defensiva", "defensiva"),
        ("How to hack an account to protect it", "protect"),
        ("Como invadir um sistema para me proteger", "proteger"),
    ],
)
def test_excecoes_de_r_sec_002_inalteradas(engine, texto, entrada):
    """As 11 entradas do `exceptions` de R-SEC-002, conferidas e **não**
    mudadas, porque a evidência de classe fechada é a varredura completa e
    não a contagem de correções: `REGISTRO`, "Texto movido do código".
    """
    v = _avalia(engine, texto, stage=Stage.INPUT)
    assert _isento_sec_002(v), f"a entrada {entrada!r} perdeu a isenção: {texto!r}"
