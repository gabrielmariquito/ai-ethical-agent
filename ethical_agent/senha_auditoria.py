"""A senha da tela de auditoria guardada como hash, e não em claro.

O que isto protege: **leitura**. Quem lê o disco -- um backup, um screenshot,
um `cat` no arquivo errado -- não lê a senha. Guarda-se sal e hash; no login,
faz-se o hash do que foi digitado e comparam-se os dois.

O que isto **não** protege: **substituição**. Quem tem acesso à máquina troca
este arquivo por um de senha conhecida e entra. A senha continua sendo
separação de papéis -- quem conversa com o agente e quem audita as decisões --,
agora separação de papéis *ilegível*, que não é o mesmo que segura. Prometer
mais que isso seria o defeito que este projeto recusa; o `AUDIT_GUIDE`, Passo 8,
diz o alcance com estas palavras.

Só biblioteca padrão, e é requisito, não coincidência: o instalador roda no
Python do *sistema*, antes do `pip install`, e só pode importar o que um
checkout nu oferece -- a mesma restrição que faz `AUDIT_PASSWORD_ENV_VAR` vir de
`ollama_install`.


A receita `senha/v1`, escrita por extenso
-----------------------------------------

Uma linha, quatro campos, separador `$`, nesta ordem::

    senha/v1$n=16384,r=8,p=1$<sal-hex>$<hash-hex>

1. **receita** -- o literal ``senha/v1``. Recusa-se qualquer outro: um arquivo
   de receita desconhecida não é lido "na melhor das hipóteses", é recusado.
2. **parâmetros** -- ``n=<int>,r=<int>,p=<int>``, nesta ordem, sem espaço. Ficam
   *dentro* do registro, e não só no código, para que o custo com que aquele
   hash foi feito seja legível sem a versão do programa que o escreveu -- e para
   que endurecê-los um dia seja detectável em vez de silencioso.
3. **sal** -- ``HASH_SAL_BYTES`` bytes de `secrets.token_bytes`, em hex
   minúsculo. O sal **não é segredo**: existe para que duas máquinas com a mesma
   senha não tenham o mesmo hash, e para que uma tabela pré-computada não sirva
   as duas.
4. **hash** -- ``HASH_DKLEN`` bytes de `hashlib.scrypt`, em hex minúsculo.

**A senha em claro nunca entra no arquivo.**

O separador é seguro porque **hex não contém `$`**: os campos 3 e 4 usam o
alfabeto ``[0-9a-f]`` e o campo 2 usa ``[nrp0-9=,]``. Isto é afirmado, e não
deixado como coincidência, porque é o canto que morde depois -- base64, que
seria a escolha óbvia se alguém quisesse encurtar a linha, tem `+`, `/` e `=`, e
o dia em que o sal mudar de alfabeto o parser começa a cortar campo no lugar
errado sem nada acusar. `test_o_separador_e_seguro_porque_hex_nao_contem_cifrao`
é o que acusa antes.

Por que `scrypt` e não `sha256` cru: nada obriga a senha da auditoria a ser
forte, e uma senha curta, em minúsculas, com um ano no fim — que é o que as
pessoas escolhem quando o campo diz "senha da tela de auditoria" — cai em
segundos num ataque de dicionário sobre um hash rápido. `scrypt` é lento e
custoso de memória de propósito.

(Este arquivo não cita nenhuma senha real, e não é escrúpulo à toa: um exemplo
concreto no docstring seria a senha em texto plano dentro do repositório, que é
exatamente o que esta leva tirou do `.env`. A varredura que confere isso é
`test_o_fonte_nao_cita_nenhuma_senha_de_verdade`.)

Por que ``n = 2**14``: medido nesta máquina em **197 ms e 16 MiB** por
tentativa, e é o maior `n` que funciona com o ``maxmem`` padrão da stdlib --
``2**15`` levanta ``ValueError: memory limit exceeded`` sem um ``maxmem=``
explícito. Somado ao bloqueio que `webui/auth.py` já faz (cinco falhas em cinco
minutos, 60 s de espera), ataque online está morto; contra dicionário offline, o
que se compra é 197 ms por palpite. Endurecer é trocar uma constante, e a
receita gravada no arquivo torna a troca visível.
"""
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# A receita escrita por extenso, na disciplina de `RECEITA_DIVISAO`
# (`evaluate.py`) e `CONFIG_ID_RECIPE` (`provenance.py`): receita implícita no
# código é o que transforma um número numa afirmação que ninguém recomputa.
RECEITA_SENHA = "senha/v1"

# O custo, em constantes com nome. Trocar `n` é uma linha, aparece no diff, e
# muda o campo 2 de todo registro novo -- que é como a mudança fica detectável.
HASH_SCRYPT_N = 2**14
HASH_SCRYPT_R = 8
HASH_SCRYPT_P = 1
HASH_SAL_BYTES = 16
HASH_DKLEN = 32

NOME_ARQUIVO = ".audit-password"

_SEPARADOR = "$"
_HEX = "0123456789abcdef"


class SenhaInvalida(Exception):
    """Registro que existe e não é legível.

    Ausente é `None` -- "não configurada", o mesmo critério que o `.env` sempre
    teve. Isto aqui é o outro caso: alguém quis configurar e o que está no disco
    não serve. Falhar alto bate deixar `bytes.fromhex` levantar `ValueError` de
    dentro do parser, que não diz a ninguém qual arquivo está corrompido.
    """


@dataclass(frozen=True)
class RegistroSenha:
    """O que fica no disco. Note o que **não** está aqui: a senha."""

    receita: str
    n: int
    r: int
    p: int
    sal: bytes
    hash: bytes


def caminho_do_registro(root: Path) -> Path:
    return Path(root) / NOME_ARQUIVO


def _derivar(senha: str, sal: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(
        senha.encode("utf-8"), salt=sal, n=n, r=r, p=p, dklen=dklen
    )


def registrar_senha(senha: str) -> RegistroSenha:
    """Sal novo a cada chamada, e é o ponto: duas senhas iguais têm de dar
    hashes diferentes, senão dois arquivos idênticos denunciam que as duas
    máquinas usam a mesma senha.
    """
    sal = secrets.token_bytes(HASH_SAL_BYTES)
    return RegistroSenha(
        receita=RECEITA_SENHA,
        n=HASH_SCRYPT_N,
        r=HASH_SCRYPT_R,
        p=HASH_SCRYPT_P,
        sal=sal,
        hash=_derivar(senha, sal, HASH_SCRYPT_N, HASH_SCRYPT_R, HASH_SCRYPT_P, HASH_DKLEN),
    )


def verificar(registro: RegistroSenha, candidata: str) -> bool:
    """Recomputa com o sal e os parâmetros **do próprio registro**, não com as
    constantes deste módulo: um arquivo escrito sob `n` antigo tem de continuar
    verificando depois de a constante ser endurecida.

    `hmac.compare_digest` e nunca `==`. Os dois lados são bytes de propósito --
    `compare_digest` levanta `TypeError` em `str` não-ASCII, e uma senha pt-BR
    com acento é inteiramente provável.
    """
    if registro is None:
        return False
    calculado = _derivar(
        candidata or "", registro.sal, registro.n, registro.r, registro.p, len(registro.hash)
    )
    return hmac.compare_digest(calculado, registro.hash)


def formatar(registro: RegistroSenha) -> str:
    return _SEPARADOR.join(
        (
            registro.receita,
            f"n={registro.n},r={registro.r},p={registro.p}",
            registro.sal.hex(),
            registro.hash.hex(),
        )
    )


def _hex_para_bytes(campo: str, nome: str) -> bytes:
    # `bytes.fromhex` aceita espaços e maiúsculas; aqui o alfabeto é fechado,
    # porque é dele que sai a garantia de que `$` não aparece num campo.
    if not campo or any(c not in _HEX for c in campo) or len(campo) % 2:
        raise SenhaInvalida(
            f"campo {nome} não é hex minúsculo de comprimento par: {campo!r}"
        )
    return bytes.fromhex(campo)


def analisar(linha: str) -> RegistroSenha:
    """Recusa por linha malformada, receita desconhecida ou parâmetro fora de
    forma -- sempre `SenhaInvalida`, nunca um erro cru de dentro do parser.
    """
    campos = (linha or "").strip().split(_SEPARADOR)
    if len(campos) != 4:
        raise SenhaInvalida(
            f"esperados 4 campos separados por {_SEPARADOR!r}, vieram {len(campos)}"
        )

    receita, parametros, sal_hex, hash_hex = campos
    if receita != RECEITA_SENHA:
        raise SenhaInvalida(
            f"receita {receita!r}; este programa lê {RECEITA_SENHA!r}. "
            "Registros de receitas diferentes não são intercambiáveis."
        )

    partes = parametros.split(",")
    if len(partes) != 3:
        raise SenhaInvalida(f"parâmetros {parametros!r}: esperados n, r e p")
    valores = {}
    for parte, esperado in zip(partes, ("n", "r", "p")):
        chave, _, valor = parte.partition("=")
        # A ordem é parte do formato: aceitar `r=8,n=16384` seria um segundo
        # formato que ninguém declarou e que o teste de round-trip não cobre.
        if chave != esperado or not valor.isdigit() or int(valor) <= 0:
            raise SenhaInvalida(
                f"parâmetro {parte!r}: esperado {esperado}=<inteiro positivo>"
            )
        valores[esperado] = int(valor)

    return RegistroSenha(
        receita=receita,
        n=valores["n"],
        r=valores["r"],
        p=valores["p"],
        sal=_hex_para_bytes(sal_hex, "sal"),
        hash=_hex_para_bytes(hash_hex, "hash"),
    )


def gravar(root: Path, registro: RegistroSenha) -> Path:
    """Escrita atômica: temporário no mesmo diretório e `os.replace`, para que
    um crash no meio não deixe meio registro no lugar do inteiro -- meio
    registro é uma tela de auditoria que não abre mais para ninguém.
    """
    destino = caminho_do_registro(root)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + f".tmp-{os.getpid()}")
    try:
        temporario.write_text(formatar(registro) + "\n", encoding="utf-8")
        os.replace(temporario, destino)
    finally:
        if temporario.exists():
            temporario.unlink()
    return destino


def ler(root: Path) -> Optional[RegistroSenha]:
    """`None` quando não há arquivo -- ausente é "não configurada", não erro.
    `SenhaInvalida` quando há e não serve.
    """
    caminho = caminho_do_registro(root)
    if not caminho.exists():
        return None
    try:
        bruto = caminho.read_text(encoding="utf-8")
    except OSError as exc:
        raise SenhaInvalida(
            f"não foi possível ler {caminho}: {exc.__class__.__name__}: {exc}"
        ) from exc
    return analisar(bruto)
