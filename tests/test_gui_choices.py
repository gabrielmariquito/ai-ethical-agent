import pytest

from ethical_agent.gui_choices import (
    ENGINE_LABELS,
    STAGE_LABELS,
    engine_value,
    stage_value,
)
from ethical_agent.types import Stage


@pytest.mark.parametrize(
    "label, expected",
    [("Rule", "rule"), ("KG", "kg"), ("Hybrid", "hybrid")],
)
def test_engine_value_maps_display_label_to_canonical_value(label, expected):
    assert engine_value(label) == expected


@pytest.mark.parametrize(
    "label, expected",
    [("Input", Stage.INPUT.value), ("Output", Stage.OUTPUT.value)],
)
def test_stage_value_maps_display_label_to_stage_enum_value(label, expected):
    value = stage_value(label)
    assert value == expected
    assert Stage(value) is (Stage.INPUT if label == "Input" else Stage.OUTPUT)


def test_engine_value_covers_every_declared_label():
    for label in ENGINE_LABELS:
        assert engine_value(label)


def test_stage_value_covers_every_declared_label():
    for label in STAGE_LABELS:
        assert stage_value(label)


def test_engine_value_rejects_unknown_label():
    with pytest.raises(ValueError):
        engine_value("rule")  # canonical value, not the display label


def test_stage_value_rejects_unknown_label():
    with pytest.raises(ValueError):
        stage_value("input")  # canonical value, not the display label


# ------------------------------------- o vocabulário que a tela de Eval usa


def test_engine_values_e_a_lista_canonica_na_ordem_dos_rotulos():
    """`__main__.py` troca o literal `choices=["rule","kg","hybrid"]` por
    `list(engine_values())` afirmando "mesmos valores, mesma ordem". Esta linha
    transforma a afirmação em verificação — e é a única coisa que impede um
    reordenar de `ENGINE_LABELS` de mudar o default do `--engine` em silêncio.
    """
    from ethical_agent.gui_choices import engine_values

    assert list(engine_values()) == ["rule", "kg", "hybrid"]


def test_a_opcao_de_comparar_nao_entra_no_mapa_de_motores():
    """`comparar` é modo da tela, não motor. Se entrasse em `_ENGINE_VALUES`,
    `engine_value` deixaria de ser mapa puro e o painel compartilhado passaria a
    oferecer uma opção que a conversa não sabe construir.
    """
    from ethical_agent.gui_choices import ENGINE_COMPARE_VALUE, engine_values

    assert ENGINE_COMPARE_VALUE not in engine_values()
    with pytest.raises(ValueError):
        engine_value("Comparar as três")


@pytest.mark.parametrize(
    "label, expected",
    [
        ("Inteiro", "full"),
        ("Tune (ajuste)", "tune"),
        ("Holdout (publicável)", "holdout"),
        ("Tune e holdout, separados", "ambas"),
    ],
)
def test_metade_value_maps_display_label_to_canonical_value(label, expected):
    from ethical_agent.gui_choices import metade_value

    assert metade_value(label) == expected


def test_os_valores_de_metade_sao_a_receita_mais_ambas():
    """A correspondência é fixada por teste e não por acoplamento: `gui_choices`
    é módulo de rótulos e não pode importar `evaluate`, que arrastaria a cadeia
    inteira de motor/política para dentro dele. O teste importa os dois.
    """
    from ethical_agent.evaluate import METADES
    from ethical_agent.gui_choices import METADE_AMBAS, _METADE_VALUES

    assert set(_METADE_VALUES.values()) == set(METADES) | {METADE_AMBAS}
