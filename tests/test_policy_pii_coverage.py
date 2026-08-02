"""R-PRIV-002 cobre os formatos de PII que um LLM de fato escreve.

O defeito que motivou a ampliação não era a omissão em si, era a cobertura
PARCIAL. Numa resposta com e-mail e telefone `+55` na mesma frase, o e-mail
saía redigido e o telefone em claro: o leitor vê `[REDACTED]` e conclui que o
texto foi tratado. Meia redação mente mais do que redação nenhuma.

Esta cobertura vive aqui, e não em `eval/dataset*.json`, de propósito: os
datasets são a linha de base congelada dos 2787 casos, e acrescentar casos a
eles muda o instrumento de medida. É decisão própria, não efeito colateral de
uma mudança de regra.

E é por isso que o benchmark não detecta esta mudança: dos 929 casos, 226 são
de estágio `output` (o único em que esta regra pode disparar), 5 contêm PII dos
formatos antigos e **nenhum** contém qualquer formato novo. Zero de 2787 mudam
de decisão -- não porque a mudança seja inócua, mas porque a suíte de casos não
a alcança.
"""

from __future__ import annotations

import pytest

from ethical_agent import ActionContext, Decision, Policy, RuleBasedEngine, Stage
from ethical_agent.policy import default_policy_path


@pytest.fixture(scope="module")
def engine():
    return RuleBasedEngine(Policy.from_file(default_policy_path()))


def _saida(engine, texto: str):
    return engine.evaluate(ActionContext(content=texto, stage=Stage.OUTPUT))


def _redigido(engine, texto: str) -> bool:
    v = _saida(engine, texto)
    return v.decision is Decision.REWRITE and "[REDACTED:R-PRIV-002]" in (v.rewritten_content or "")


# --------------------------------------------------------- o caso do relato


def test_email_e_telefone_na_mesma_frase_somem_os_dois(engine):
    # A reprodução exata do problema. Antes desta mudança, este teste falhava
    # com o telefone intacto ao lado de um [REDACTED] -- que é o que fazia o
    # leitor concluir que o texto tinha sido tratado.
    v = _saida(engine, "contato: john.doe@example.com ou +55 21 99876-5432")
    assert v.decision is Decision.REWRITE
    assert "john.doe@example.com" not in v.rewritten_content
    assert "99876-5432" not in v.rewritten_content
    assert v.rewritten_content.count("[REDACTED:R-PRIV-002]") == 2


# ------------------------------------------------------ os formatos novos


@pytest.mark.parametrize(
    "nome, texto",
    [
        ("+55 com espaços", "ligue para +55 21 99876-5432"),
        ("+55 sem separador", "ligue para +5521998765432"),
        ("+55 com parênteses", "ligue para +55 (21) 99876-5432"),
        ("+55 hífen no meio", "ligue para +55 21 9876-5432"),
        ("móvel com DDD", "ligue para 21 99876-5432"),
        ("fixo com DDD", "ligue para 21 3456-7890"),
        ("CPF rotulado", "o CPF dele e 12345678900"),
        ("CPF com dois-pontos", "CPF: 12345678900"),
        ("cpf minúsculo", "cpf 12345678900"),
    ],
)
def test_formatos_brasileiros_sao_redigidos(engine, nome, texto):
    assert _redigido(engine, texto), nome


# --------------------------------- os formatos antigos continuam cobertos


@pytest.mark.parametrize(
    "nome, texto",
    [
        ("e-mail", "escreva para john.doe@example.com"),
        ("CPF pontuado", "o CPF dele e 123.456.789-00"),
        ("SSN", "SSN 123-45-6789"),
        ("cartão", "Card number: 4111 1111 1111 1111"),
        ("telefone com parênteses", "ligue para (21) 99876-5432"),
        ("RG", "RG 12.345.678-9"),
    ],
)
def test_a_ampliacao_nao_quebrou_o_que_ja_funcionava(engine, nome, texto):
    assert _redigido(engine, texto), nome


# ------------------------------------------- falso positivo: texto benigno


BENIGNOS = [
    "Python 3.12.5 e a versao estavel",
    "release 2024.10.1 publicada",
    "atualize para v1.2.3",
    "o pedido numero 12345678900 foi enviado",
    "R$ 1.234.567,89 de faturamento no trimestre",
    "custou US$ 12,345.67",
    "a data limite e 2026-08-02",
    "vence em 21/08/2026",
    "Springfield, IL 62704-1234",
    "ISBN 978-0-13-235088-4",
    "o servidor responde em 192.168.0.1:8080",
    "timestamp 1723000000000 em milissegundos",
    "veja as paginas 12-34",
    "de 1000 a 2000 unidades",
    "a cidade tem 1.234.567 habitantes",
    "numero de serie SN 12345678901234",
    "erro 404 na porta 8765",
    "a norma ISO 27001-2022 exige",
    "processo 0001234-56.2020.8.26.0100",
]


@pytest.mark.parametrize("texto", BENIGNOS)
def test_texto_benigno_com_numeros_nao_e_redigido(engine, texto):
    # Padrões numéricos largos casam com o que não é PII. Os colisores
    # plausíveis estão todos aqui: pedido de 11 dígitos (que um `\d{11}` solto
    # pegaria), ZIP+4 americano (5 dígitos, hífen, 4 -- vizinho do CEP),
    # timestamp de 13, versões, dinheiro, número de processo.
    v = _saida(engine, texto)
    assert v.decision is Decision.ALLOW, f"{texto!r} -> {v.rewritten_content}"


# ------------------------------- o que fica de fora É escolha, não esquecimento


@pytest.mark.parametrize(
    "nome, texto, razao",
    [
        (
            "CNPJ",
            "a empresa tem CNPJ 12.345.678/0001-95",
            "identifica empresa, não pessoa; é registro público, e redigir "
            "quebraria resposta legítima sobre a empresa",
        ),
        (
            "CEP",
            "o endereco fica no CEP 22290-140",
            "sozinho identifica logradouro, não pessoa; redigir quebraria "
            "resposta de endereço sem proteger ninguém",
        ),
        (
            "CPF sem rótulo",
            "o numero e 12345678900",
            "um `\\d{11}` solto casaria pedido, identificador e timestamp, e a "
            "engine é regex pura, sem como validar o dígito verificador",
        ),
    ],
)
def test_exclusoes_deliberadas_continuam_passando(engine, nome, texto, razao):
    # Estes três NÃO são redigidos, e isso está escrito na `description` da
    # regra. O teste existe para que incluí-los seja um ato deliberado -- quem
    # acrescentar o padrão vai ver este teste ficar vermelho e ler a razão
    # antes de decidir que ela não vale mais.
    v = _saida(engine, texto)
    assert v.decision is Decision.ALLOW, f"{nome} passou a ser redigido; razão da exclusão: {razao}"


# ------------------------------------------------------------ a versão subiu


def test_a_versao_da_politica_acompanhou_a_mudanca_de_cobertura():
    # A trilha grava policy_version. Mudar regra sem mudar versão torna
    # registros antes e depois indistinguíveis para quem auditar.
    policy = Policy.from_file(default_policy_path())
    assert policy.metadata["version"] == "0.3.0"


def test_a_regra_documenta_o_que_deixou_de_fora():
    # A omissão tem de estar escrita onde quem lê a política a encontra.
    policy = Policy.from_file(default_policy_path())
    rule = next(r for r in policy.rules if r.id == "R-PRIV-002")
    description = rule.description.lower()
    for termo in ("cnpj", "cep", "not covered"):
        assert termo in description, termo
