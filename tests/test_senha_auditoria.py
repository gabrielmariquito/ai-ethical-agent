import hashlib
import re
from pathlib import Path

import pytest

from ethical_agent import senha_auditoria as sa

SOURCE = (
    Path(__file__).resolve().parent.parent / "ethical_agent" / "senha_auditoria.py"
).read_text(encoding="utf-8")

SENHA = "senha-de-teste-9c2f"


# -- o que o arquivo guarda ---------------------------------------------------


def test_o_arquivo_guarda_hash_e_sal_e_nunca_a_senha_em_claro(tmp_path):
    # A afirmação inteira desta leva num teste só: quem lê o disco não lê a
    # senha. Asseverado sobre o conteúdo do arquivo, não sobre o registro em
    # memória, porque é o arquivo que sobrevive a um backup ou a um screenshot.
    sa.gravar(tmp_path, sa.registrar_senha(SENHA))
    conteudo = sa.caminho_do_registro(tmp_path).read_text(encoding="utf-8")

    assert SENHA not in conteudo
    # E nem em pedaços: um sal ou um hash que por acaso contivesse a senha
    # seria a mesma falha com outra roupa.
    assert SENHA.encode("utf-8").hex() not in conteudo
    registro = sa.ler(tmp_path)
    assert len(registro.sal) == sa.HASH_SAL_BYTES
    assert len(registro.hash) == sa.HASH_DKLEN


def test_a_receita_e_os_parametros_ficam_dentro_do_registro(tmp_path):
    # Endurecer `n` um dia tem de ser detectável, não silencioso: quem lê o
    # arquivo vê com que custo aquele hash foi feito, sem precisar do código
    # da versão que o escreveu.
    sa.gravar(tmp_path, sa.registrar_senha(SENHA))
    conteudo = sa.caminho_do_registro(tmp_path).read_text(encoding="utf-8")

    assert sa.RECEITA_SENHA in conteudo
    assert f"n={sa.HASH_SCRYPT_N}" in conteudo
    assert f"r={sa.HASH_SCRYPT_R}" in conteudo
    assert f"p={sa.HASH_SCRYPT_P}" in conteudo


def test_os_parametros_sao_constantes_nomeadas_e_nao_literais_soltos():
    # A disciplina de `RECEITA_DIVISAO`/`CONFIG_ID_RECIPE`: a receita escrita
    # por extenso, e o custo em constante com nome, para que a mudança seja uma
    # linha e apareça no diff.
    assert 'RECEITA_SENHA = "senha/v1"' in SOURCE
    for nome in ("HASH_SCRYPT_N", "HASH_SCRYPT_R", "HASH_SCRYPT_P"):
        assert re.search(rf"^{nome} = ", SOURCE, re.MULTILINE), nome
    # Quem *escreve* um registro novo usa as constantes, nunca um número solto.
    # A derivação em si recebe n/r/p por parâmetro de propósito -- `verificar`
    # tem de usar os do registro lido, não os de hoje, senão endurecer a
    # constante invalidaria todo arquivo já gravado.
    corpo = SOURCE[SOURCE.index("def registrar_senha(") :]
    corpo = corpo[: corpo.index("\ndef ")]
    for nome in ("HASH_SCRYPT_N", "HASH_SCRYPT_R", "HASH_SCRYPT_P", "HASH_SAL_BYTES"):
        assert nome in corpo, nome
    assert not re.search(r"\b(16384|2\s*\*\*\s*14)\b", corpo)


# -- autenticação -------------------------------------------------------------


def test_senha_correta_autentica_e_senha_errada_nao(tmp_path):
    sa.gravar(tmp_path, sa.registrar_senha(SENHA))
    registro = sa.ler(tmp_path)

    assert sa.verificar(registro, SENHA) is True
    assert sa.verificar(registro, "auditoria2027") is False
    assert sa.verificar(registro, "") is False
    assert sa.verificar(registro, SENHA + " ") is False


def test_senha_com_acento_faz_round_trip(tmp_path):
    # `hmac.compare_digest` levanta TypeError em str não-ASCII, e uma senha
    # pt-BR com acento é inteiramente provável -- os dois lados são bytes.
    acentuada = "não-é-segurança"
    sa.gravar(tmp_path, sa.registrar_senha(acentuada))
    registro = sa.ler(tmp_path)

    assert sa.verificar(registro, acentuada) is True
    assert sa.verificar(registro, "nao-e-seguranca") is False


def test_a_comparacao_usa_compare_digest_e_nao_igualdade():
    # `==` sobre digest vaza informação por tempo de resposta. Asseverado sobre
    # o fonte porque o comportamento certo e o errado são indistinguíveis por
    # valor de retorno -- só o mecanismo distingue.
    corpo = SOURCE[SOURCE.index("def verificar(") :]
    corpo = corpo[: corpo.index("\ndef ")] if "\ndef " in corpo else corpo

    assert "hmac.compare_digest" in corpo
    assert not re.search(r"==\s*registro\.hash|registro\.hash\s*==", corpo)


def test_sal_diferente_por_senha(tmp_path):
    # Duas senhas iguais geram hashes diferentes: sem isso, dois arquivos com o
    # mesmo hash denunciam que as duas máquinas usam a mesma senha, e uma
    # tabela pré-computada serve as duas.
    a = sa.registrar_senha(SENHA)
    b = sa.registrar_senha(SENHA)

    assert a.sal != b.sal
    assert a.hash != b.hash
    # E as duas continuam verificando a mesma senha.
    assert sa.verificar(a, SENHA) and sa.verificar(b, SENHA)


# -- o formato `senha/v1` -----------------------------------------------------


def test_round_trip_da_receita(tmp_path):
    registro = sa.registrar_senha(SENHA)
    assert sa.analisar(sa.formatar(registro)) == registro


def test_o_formato_tem_quatro_campos_na_ordem_declarada(tmp_path):
    campos = sa.formatar(sa.registrar_senha(SENHA)).split("$")

    assert len(campos) == 4
    assert campos[0] == "senha/v1"
    assert campos[1] == f"n={sa.HASH_SCRYPT_N},r={sa.HASH_SCRYPT_R},p={sa.HASH_SCRYPT_P}"
    assert re.fullmatch(r"[0-9a-f]+", campos[2])
    assert re.fullmatch(r"[0-9a-f]+", campos[3])


def test_o_separador_e_seguro_porque_hex_nao_contem_cifrao():
    # Afirmado, não deixado como coincidência: se um dia o sal virar base64 --
    # que TEM `+`, `/` e `=` -- este teste é o que acusa antes de o parser
    # começar a cortar campo no lugar errado.
    for _ in range(32):
        registro = sa.registrar_senha("x")
        assert "$" not in registro.sal.hex()
        assert "$" not in registro.hash.hex()
    assert "$" not in f"n={sa.HASH_SCRYPT_N},r={sa.HASH_SCRYPT_R},p={sa.HASH_SCRYPT_P}"


@pytest.mark.parametrize(
    "linha",
    [
        "",
        "senha/v1",
        "senha/v1$n=16384,r=8,p=1$abc",
        "senha/v1$n=16384,r=8,p=1$abc$def$extra",
        "senha/v2$n=16384,r=8,p=1$ab$cd",
        "senha/v1$n=16384,r=8$ab$cd",
        "senha/v1$r=8,n=16384,p=1$ab$cd",
        "senha/v1$n=dezesseis,r=8,p=1$ab$cd",
        "senha/v1$n=16384,r=8,p=1$zz$cd",
        "senha-de-teste-9c2f",
    ],
)
def test_linha_malformada_e_recusa_clara_e_nao_erro_cru(linha):
    # Recusa nomeada, para que um arquivo corrompido produza uma mensagem e não
    # um ValueError de dentro de `bytes.fromhex`.
    with pytest.raises(sa.SenhaInvalida):
        sa.analisar(linha)


def test_arquivo_ausente_e_none_e_arquivo_corrompido_e_recusa(tmp_path):
    # Ausente não é erro: é "não configurada", o mesmo critério que o `.env`
    # sempre teve. Corrompido é erro, porque alguém quis configurar.
    assert sa.ler(tmp_path) is None

    sa.caminho_do_registro(tmp_path).write_text("lixo\n", encoding="utf-8")
    with pytest.raises(sa.SenhaInvalida):
        sa.ler(tmp_path)


def test_a_gravacao_e_atomica_e_nao_deixa_temporario_para_tras(tmp_path):
    sa.gravar(tmp_path, sa.registrar_senha(SENHA))
    sa.gravar(tmp_path, sa.registrar_senha("outra"))

    restantes = sorted(p.name for p in tmp_path.iterdir())
    assert restantes == [sa.NOME_ARQUIVO]
    assert sa.verificar(sa.ler(tmp_path), "outra")


def test_o_hash_e_reproduzivel_a_partir_do_sal_e_dos_parametros_do_arquivo(tmp_path):
    # O que a verificação faz, feito à mão: quem tem o arquivo consegue
    # recomputar sem o código deste módulo. É o que torna a receita auditável.
    sa.gravar(tmp_path, sa.registrar_senha(SENHA))
    registro = sa.ler(tmp_path)

    esperado = hashlib.scrypt(
        SENHA.encode("utf-8"),
        salt=registro.sal,
        n=registro.n,
        r=registro.r,
        p=registro.p,
        dklen=len(registro.hash),
    )
    assert esperado == registro.hash


def test_o_fonte_nao_cita_nenhuma_senha_de_verdade():
    # Achado durante esta própria leva, por varredura da árvore: o docstring
    # deste módulo explicava por que `scrypt` e não `sha256` citando **a senha
    # real desta máquina**, por extenso. Um exemplo concreto num comentário é a
    # senha em texto plano dentro do repositório -- exatamente o que a leva
    # acabara de tirar do `.env`, reintroduzido pela porta dos fundos.
    #
    # A regra que sobra: o fonte argumenta sobre a *forma* de uma senha fraca,
    # nunca sobre uma senha que alguém use.
    #
    # E a asserção é por **padrão**, não por lista: uma lista de senhas
    # proibidas seria este mesmo teste cometendo o defeito que ele vigia -- as
    # senhas reais estariam aqui, em texto plano, no repositório.
    suspeitas = re.findall(r"``([a-z][a-z-]{4,}\d{2,4})``", SOURCE)
    assert not suspeitas, (
        f"o fonte cita {suspeitas!r} como exemplo concreto de senha; "
        "descreva a forma (curta, minúsculas, ano no fim) em vez de citar uma"
    )


def test_o_modulo_so_depende_da_biblioteca_padrao():
    # O wizard roda no Python do sistema, antes do pip install, e só importa o
    # que um checkout nu oferece -- a mesma restrição que faz
    # `AUDIT_PASSWORD_ENV_VAR` vir de `ollama_install`.
    importados = re.findall(r"^(?:from|import)\s+([\w.]+)", SOURCE, re.MULTILINE)
    permitidos = {"hashlib", "hmac", "os", "secrets", "dataclasses", "pathlib", "typing"}
    assert {m.split(".")[0] for m in importados} <= permitidos
