"""Separação de acesso da tela de auditoria, exigida como **estrutural** e não
visual: sem senha configurada a superfície tem de ser indistinguível de um
caminho nunca registrado, em todo método: versão longa em `997a6fe^`.
"""
from __future__ import annotations

import json

import pytest

from ethical_agent import senha_auditoria
from ethical_agent.webui.auth import (
    AuditPasswordError,
    dotenv_password_present,
    load_audit_password,
)
from webui_support import RunningServer

PASSWORD = "senha-de-teste"

# Every audit path, so a route added later without a realm= marker shows up
# here as a failure rather than as a quiet hole.
AUDIT_API_PATHS = [
    "/api/audit/login",
    "/api/audit/logout",
    "/api/audit/session",
    "/api/audit/session/events",
    "/api/audit/records",
    "/api/audit/records/some-event-id",
    "/api/audit/conversations/some-conversation",
    "/api/audit/telemetry",
    "/api/audit/change-requests",
]


@pytest.fixture
def chat_server(tmp_path):
    """No password -> the audit screen does not exist."""
    running = RunningServer(tmp_path)
    yield running
    running.close()


@pytest.fixture
def audit_server(tmp_path):
    running = RunningServer(tmp_path, audit_password=PASSWORD)
    yield running
    running.close()


def test_audit_api_requires_password_when_configured(audit_server):
    # Without a session, no audit data is reachable at all.
    status, body, _ = audit_server.get("/api/audit/records")
    assert status == 401, body
    assert body["error"] == "unauthorized"

    # A wrong password neither logs in nor loosens anything.
    status, body, _ = audit_server.login_as_auditor("nao-e-a-senha")
    assert status == 401, body
    assert body["error"] == "invalid_password"
    status, _, _ = audit_server.get("/api/audit/records")
    assert status == 401

    status, body, _ = audit_server.login_as_auditor(PASSWORD)
    assert status == 200, body
    status, body, _ = audit_server.get("/api/audit/records")
    assert status == 200, body
    assert "records" in body


def test_audit_endpoints_do_not_exist_in_chat_mode(chat_server):
    # Os 404 de referência: um de rota de API inexistente e um de arquivo
    # estático ausente — corpo distintivo já anunciaria que a coisa existe.
    _, api_404, _ = chat_server.request("GET", "/api/does-not-exist")
    _, static_404, _ = chat_server.request("GET", "/static/js/nope.js")

    for path in AUDIT_API_PATHS + ["/audit"]:
        for method in ("GET", "POST"):
            status, raw, _ = chat_server.request(
                method, path, {} if method == "POST" else None
            )
            assert status == 404, (method, path, raw)
            expected = json.dumps(
                {"error": "not_found", "message": f"no route for {method} {path}"},
                ensure_ascii=False,
            ).encode("utf-8")
            assert raw == expected, (method, path, raw)
    assert api_404.startswith(b'{"error": "not_found"')

    # The screen's own assets are gated too. Serving them would leave the
    # whole audit frontend readable in chat mode; that they live under one
    # static/js/audit/ prefix is what makes the gate a single check.
    for path in (
        "/static/js/audit/audit-app.js",
        "/static/js/audit/audit-layers.js",
        "/static/css/audit.css",
    ):
        status, raw, _ = chat_server.request("GET", path)
        assert status == 404, path
        assert raw == static_404, path


def test_audit_wrong_method_is_404_not_405_in_chat_mode(chat_server):
    # A regressão que isto guarda: `_dispatch` marca `path_known` por qualquer
    # padrão que case, ignorando o método, então o portão tem de acontecer
    # dentro de `routing.match()`: versão longa em `997a6fe^`.
    status, body, _ = chat_server.post("/api/audit/records", {})
    assert status == 404, body
    assert body["error"] == "not_found"

    # Sanity: a genuinely known path still 405s, so the test above is not
    # passing because 405 stopped happening everywhere.
    status, body, _ = chat_server.get("/api/chat/new")
    assert status == 405, body


def test_audit_page_serves_login_shell_but_no_records_without_session(audit_server):
    # The one deliberate exception to "the screen does not exist": with a
    # password configured, /audit serves the login form, which holds no
    # records. Everything behind it still 401s.
    status, raw, headers = audit_server.request("GET", "/audit")
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert b"ea-audit-login" in raw
    for path in ("/api/audit/records", "/api/audit/session"):
        status, _, _ = audit_server.get(path)
        assert status == 401, path


def test_login_cookie_is_httponly_samesite_and_has_no_secure_flag(audit_server):
    status, _, headers = audit_server.login_as_auditor(PASSWORD)
    assert status == 200
    cookie = headers["Set-Cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    # No Secure attribute, deliberately: this server is plain HTTP on
    # 127.0.0.1 and a Secure cookie would never be sent back, breaking the
    # screen entirely. Asserted so nobody "hardens" it into non-function.
    assert "Secure" not in cookie


def test_session_token_never_appears_in_any_log_file(audit_server, tmp_path):
    status, body, headers = audit_server.login_as_auditor(PASSWORD)
    assert status == 200
    token = headers["Set-Cookie"].split("=", 1)[1].split(";", 1)[0]
    assert token

    audit_server.post(
        "/api/audit/telemetry",
        {"events": [{"seq": 1, "type": "session_started", "payload": {}}]},
    )
    audit_server.post(
        "/api/audit/change-requests", {"record_event_id": "abc", "rule_id": "R-1"}
    )

    # The session_id identifies the session in the file; the token
    # authenticates. Writing the latter would put a live credential in an
    # artifact meant to be read and shared.
    for path in (
        audit_server.auditor_session_log,
        audit_server.change_requests_log,
        audit_server.audit_log_path,
    ):
        try:
            with open(path, encoding="utf-8") as handle:
                assert token not in handle.read(), path
        except FileNotFoundError:
            pass
    assert body["session_id"] != token


def test_lockout_after_five_failures_returns_429_with_retry_after(audit_server):
    for _ in range(4):
        status, _, _ = audit_server.login_as_auditor("errada")
        assert status == 401
    status, body, _ = audit_server.login_as_auditor("errada")
    assert status == 429, body
    assert body["error"] == "too_many_attempts"
    # Even the correct password is refused while locked out -- otherwise the
    # lockout would only slow down someone who never guesses right.
    status, body, _ = audit_server.login_as_auditor(PASSWORD)
    assert status == 429, body


def test_session_invalid_after_server_restart(tmp_path):
    first = RunningServer(tmp_path, audit_password=PASSWORD)
    try:
        status, _, _ = first.login_as_auditor(PASSWORD)
        assert status == 200
        cookies = dict(first.cookies)
        status, _, _ = first.get("/api/audit/records")
        assert status == 200
    finally:
        first.close()

    second = RunningServer(tmp_path, audit_password=PASSWORD)
    try:
        # Sessions live in process memory only, so a restart invalidates
        # them. Documented behaviour: persisting a session token to disk
        # would mean writing a credential next to the trail it unlocks.
        second.cookies = cookies
        status, body, _ = second.get("/api/audit/records")
        assert status == 401, body
    finally:
        second.close()


def test_reserved_underscore_params_cannot_be_forged(audit_server):
    # Handlers read params["_session_id"], which the dispatcher injects. Any
    # client-supplied param starting with "_" is stripped first, so the query
    # string cannot manufacture an identity.
    status, body, _ = audit_server.get("/api/audit/records?_session_id=forjado")
    assert status == 401, body

    status, _, _ = audit_server.login_as_auditor(PASSWORD)
    assert status == 200
    status, body, _ = audit_server.get("/api/audit/session?_session_id=forjado")
    assert status == 200
    assert body["session_id"] != "forjado"


def test_choices_endpoint_never_exposes_the_password(audit_server):
    # handlers_choices.py serves dict(initial_config) verbatim, unauthenticated.
    # The password is kept in AuditAuth precisely so it cannot ride along;
    # this asserts the whole payload, not just the keys we expect.
    status, raw, _ = audit_server.request("GET", "/api/choices")
    assert status == 200
    assert PASSWORD.encode("utf-8") not in raw
    body = json.loads(raw)
    assert body["audit_screen_enabled"] is True
    assert not any("password" in key.lower() for key in body["defaults"])


def test_choices_reports_audit_disabled_in_chat_mode(chat_server):
    status, body, _ = chat_server.get("/api/choices")
    assert status == 200
    assert body["audit_screen_enabled"] is False


def test_non_ascii_password_round_trips(tmp_path):
    # hmac.compare_digest raises TypeError on non-ASCII str, so both sides
    # are hashed to bytes first. A pt-BR password with an accent is entirely
    # likely, and this is the trap that would only surface in the field.
    password = "sênha-com-acento-çãó"
    server = RunningServer(tmp_path, audit_password=password)
    try:
        status, body, _ = server.login_as_auditor(password)
        assert status == 200, body
        status, _, _ = server.get("/api/audit/records")
        assert status == 200
    finally:
        server.close()


# As três fontes de senha e sua ordem; todos passam `root=tmp_path` explícito
# porque o default é a raiz real do repositório: versão longa em `997a6fe^`.


def _dotenv(root, value):
    """Uma máquina **anterior** à leva do hash: senha em claro no `.env`.

    Depois da primeira `load_audit_password`, esta máquina não existe mais --
    a senha vira hash e a linha some. É por isso que quase todo teste abaixo
    que usa este helper está, na verdade, exercitando a migração.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".env").write_text(
        f"OLLAMA_MODEL=llama3.2:3b\nETHICAL_AGENT_AUDIT_PASSWORD={value}\n",
        encoding="utf-8",
    )
    return root


def _hasheada(root, value):
    """Uma máquina já migrada: só o registro `senha/v1`, nenhum `.env`."""
    root.mkdir(parents=True, exist_ok=True)
    senha_auditoria.gravar(root, senha_auditoria.registrar_senha(value))
    return root


def _confere(credencial, senha):
    """A credencial verifica aquela senha -- e, sendo hash, não *é* a senha."""
    assert credencial is not None
    assert credencial != senha
    return senha_auditoria.verificar(credencial, senha)


FONTE = f"{senha_auditoria.NOME_ARQUIVO} ({senha_auditoria.RECEITA_SENHA})"


def test_password_file_takes_precedence_over_env_var(tmp_path):
    path = tmp_path / "senha.txt"
    path.write_text("do-arquivo\n", encoding="utf-8")
    password, source, _ = load_audit_password(
        str(path), {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=tmp_path
    )
    assert password == "do-arquivo"
    assert str(path) in source
    # ...and the value itself never appears in the description, which is the
    # only part of this that gets printed.
    assert "do-arquivo" not in source


def test_the_env_var_is_not_a_password_source_any_more(tmp_path):
    # A variável não perde: ela não é lida, então deixá-la setada tem de ser
    # recusado e não ignorado: versão longa em `997a6fe^`.
    with pytest.raises(AuditPasswordError) as excinfo:
        load_audit_password(
            None, {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=tmp_path
        )

    message = str(excinfo.value)
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" in message
    assert "apague a variável" in message.lower()
    assert "do-ambiente" not in message


def test_o_registro_hasheado_e_a_fonte_quando_nao_ha_flag_nem_variavel(tmp_path):
    # O caminho do instalador: senha definida no wizard e `serve` sem flag.
    credencial, source, _ = load_audit_password(None, {}, root=_hasheada(tmp_path, "a-senha"))
    assert _confere(credencial, "a-senha")
    assert source == FONTE
    assert "a-senha" not in source


def test_a_migracao_transforma_o_dotenv_em_hash_e_apaga_a_linha(tmp_path):
    # Teste 5 do plano. A máquina de ontem sobe hoje, e a senha em claro deixa
    # de existir em arquivo nenhum.
    root = _dotenv(tmp_path, "senha-de-teste-9c2f")

    credencial, source, avisos = load_audit_password(None, {}, root=root)

    assert _confere(credencial, "senha-de-teste-9c2f")
    assert source == FONTE
    # A senha em claro sumiu do `.env`...
    dotenv = (root / ".env").read_text(encoding="utf-8")
    assert "senha-de-teste-9c2f" not in dotenv
    assert "ETHICAL_AGENT_AUDIT_PASSWORD" not in dotenv
    # ...e o resto do `.env` sobreviveu: a migração tira uma linha, não o arquivo.
    assert "OLLAMA_MODEL=llama3.2:3b" in dotenv
    # ...e nem no arquivo novo ela aparece.
    registro = senha_auditoria.caminho_do_registro(root).read_text(encoding="utf-8")
    assert "senha-de-teste-9c2f" not in registro
    assert registro.startswith(senha_auditoria.RECEITA_SENHA)
    # E foi dita em voz alta: migração silenciosa que apaga linha de arquivo de
    # configuração é o que assusta quando descoberto depois.
    assert any("migrada para hash" in a for a in avisos)
    assert any(senha_auditoria.NOME_ARQUIVO in a for a in avisos)
    assert not any("senha-de-teste-9c2f" in a for a in avisos)


def test_a_migracao_e_idempotente_e_nao_sobrescreve_hash_em_vigor(tmp_path):
    root = _hasheada(tmp_path, "a-que-vale")
    # Um `.env` reeditado à mão depois da migração não pode ganhar do hash.
    (root / ".env").write_text(
        "ETHICAL_AGENT_AUDIT_PASSWORD=a-que-nao-vale\n", encoding="utf-8"
    )

    credencial, _, avisos = load_audit_password(None, {}, root=root)

    assert _confere(credencial, "a-que-vale")
    assert senha_auditoria.verificar(credencial, "a-que-nao-vale") is False
    assert avisos == []


def test_a_migracao_roda_antes_da_checagem_de_conflito(tmp_path):
    # Teste 7 do plano, e a interação que quebraria calado: a leva anterior fez
    # o `serve` recusar quando uma variável remanescente discorda da senha em
    # vigor. Numa máquina não migrada, o registro ainda não existe -- se a
    # checagem rodasse primeiro, ela chamaria a variável de órfã e recusaria a
    # subir uma máquina que estava perfeitamente configurada.
    credencial, source, _ = load_audit_password(
        None,
        {"ETHICAL_AGENT_AUDIT_PASSWORD": "senha-de-teste-9c2f"},
        root=_dotenv(tmp_path, "senha-de-teste-9c2f"),
    )

    assert _confere(credencial, "senha-de-teste-9c2f")
    assert source == FONTE


def test_uma_variavel_remanescente_que_discorda_do_hash_e_recusada(tmp_path):
    root = _hasheada(tmp_path, "a-que-vale")
    with pytest.raises(AuditPasswordError) as excinfo:
        load_audit_password(None, {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=root)

    message = str(excinfo.value)
    assert "$ETHICAL_AGENT_AUDIT_PASSWORD" in message
    assert str(senha_auditoria.caminho_do_registro(root).resolve()) in message
    assert "--audit-password-file" in message
    # Pode dizer que divergem. Não pode dizer como, nem citar nenhuma das duas.
    assert "do-ambiente" not in message
    assert "a-que-vale" not in message


def test_uma_variavel_remanescente_que_verifica_contra_o_hash_e_silenciosa(tmp_path):
    # Nada é ambíguo, logo não há o que recusar. E note o que mudou: a decisão
    # sai de `verificar`, não de `==` entre duas strings -- é o que fecha `D-10`,
    # porque não há mais dois analisadores que precisem concordar.
    credencial, source, _ = load_audit_password(
        None,
        {"ETHICAL_AGENT_AUDIT_PASSWORD": "a-mesma"},
        root=_hasheada(tmp_path, "a-mesma"),
    )
    assert _confere(credencial, "a-mesma")
    assert source == FONTE


def test_password_file_silences_the_tripwire(tmp_path):
    # The regression test for where the check sits: inside
    # load_audit_password, *after* the --audit-password-file branch has
    # already returned. The flag states which password to use, so a leftover
    # variable cannot make the invocation ambiguous. (cmd_serve still names
    # it in the banner -- silencing the refusal is not saying nothing.)
    path = tmp_path / "senha.txt"
    path.write_text("do-arquivo\n", encoding="utf-8")
    root = _dotenv(tmp_path, "do-dotenv")
    password, source, _ = load_audit_password(
        str(path), {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=root
    )
    assert password == "do-arquivo"
    assert "do-arquivo" not in source
    assert "do-dotenv" not in source
    assert "do-ambiente" not in source
    # E a flag não é desculpa para deixar senha em claro no disco: a migração
    # roda antes dela e não muda quem vence esta invocação.
    assert "do-dotenv" not in (root / ".env").read_text(encoding="utf-8")
    assert senha_auditoria.verificar(senha_auditoria.ler(root), "do-dotenv")


def test_a_variable_with_a_dotenv_that_has_no_password_is_refused(tmp_path):
    # The .env exists and is read -- it just does not carry this key. Nothing
    # would be in effect, so the variable's owner would lose the screen in
    # silence. This is the case that used to work, and it is the one the
    # README's one-liner produced.
    (tmp_path / ".env").write_text("OLLAMA_MODEL=llama3.2:3b\n", encoding="utf-8")
    with pytest.raises(AuditPasswordError) as excinfo:
        load_audit_password(
            None, {"ETHICAL_AGENT_AUDIT_PASSWORD": "do-ambiente"}, root=tmp_path
        )
    assert "wizard_gui.py" in str(excinfo.value), "tem de dizer onde a senha passa a morar"


def test_a_blank_env_var_is_not_a_leftover_at_all(tmp_path):
    # An exported-but-empty variable is how a shell profile leaves the name
    # defined without meaning anything by it. Refusing over that would be
    # refusing over nothing.
    credencial, source, _ = load_audit_password(
        None, {"ETHICAL_AGENT_AUDIT_PASSWORD": "   "}, root=_hasheada(tmp_path, "a-senha")
    )
    assert _confere(credencial, "a-senha")
    assert source == FONTE

    # ...and with nothing configured anywhere, a blank variable is still just
    # a disabled audit screen, not an error.
    credencial, source, _ = load_audit_password(
        None, {"ETHICAL_AGENT_AUDIT_PASSWORD": ""}, root=tmp_path / "vazio"
    )
    assert credencial is None
    assert source is None


def test_the_resolver_never_reads_the_real_environment_when_env_is_passed(monkeypatch, tmp_path):
    # The property every other test in this file leans on: `env` is honoured
    # exactly, so a developer's own exported password cannot reach in. It
    # matters more now that a stray variable raises instead of being ranked.
    monkeypatch.setenv("ETHICAL_AGENT_AUDIT_PASSWORD", "veneno-do-ambiente-real")
    credencial, source, _ = load_audit_password(None, {}, root=_hasheada(tmp_path, "a-senha"))
    assert _confere(credencial, "a-senha")
    assert source == FONTE


def test_dotenv_password_present_reports_the_loser_without_the_value(tmp_path):
    # What the startup banner uses to say "there is also one configured, and it
    # is not the one in effect" -- a boolean, never the value.
    assert dotenv_password_present(root=_hasheada(tmp_path, "a-senha")) is True
    assert dotenv_password_present(root=tmp_path / "vazio") is False


def test_empty_key_in_dotenv_is_not_configured_rather_than_an_error(tmp_path):
    # The opposite of an empty --audit-password-file below: nobody points at
    # .env on purpose, so a blank line there is silence, not a broken request.
    (tmp_path / ".env").write_text(
        "OLLAMA_MODEL=llama3.2:3b\nETHICAL_AGENT_AUDIT_PASSWORD=\n", encoding="utf-8"
    )
    password, source, _ = load_audit_password(None, {}, root=tmp_path)
    assert password is None
    assert source is None


def test_a_migracao_preserva_espacos_e_cerquilha_da_senha_do_dotenv(tmp_path):
    # O analisador feito à mão é autoritativo para esta chave, e leva o resto da
    # linha inteiro: um `#` é parte da senha, não comentário. Espaço nas pontas
    # some, porque a escrita também fazia strip.
    #
    # Depois da leva do hash isto só governa **a migração** -- é a última vez
    # que este analisador toca uma senha. É também onde mora o resíduo de
    # `D-10`: se alguém tiver editado o `.env` à mão com ASPAS, elas viajam para
    # dentro do hash, e o conserto é rodar o instalador de novo. Não é mais
    # recusa espúria; é uma senha migrada errada, que aparece no primeiro login.
    (tmp_path / ".env").write_text(
        "ETHICAL_AGENT_AUDIT_PASSWORD=  senha com espaços #1  \n", encoding="utf-8"
    )

    credencial, source, _ = load_audit_password(None, {}, root=tmp_path)

    assert _confere(credencial, "senha com espaços #1")
    assert source == FONTE


def test_no_password_source_means_the_screen_is_disabled(tmp_path):
    password, source, warnings = load_audit_password(None, {}, root=tmp_path)
    assert password is None
    assert source is None
    assert warnings == []


def test_empty_password_file_is_a_startup_error(tmp_path):
    path = tmp_path / "vazio.txt"
    path.write_text("   \n", encoding="utf-8")
    # Failing loudly beats silently starting a server whose audit screen
    # quietly does not exist -- the operator explicitly asked for it.
    with pytest.raises(AuditPasswordError):
        load_audit_password(str(path), {}, root=tmp_path)
