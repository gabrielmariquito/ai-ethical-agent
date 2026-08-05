import socket

import pytest

from webui_support import RunningServer


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path)
    yield running
    running.close()


def test_unknown_path_is_404(server):
    status, body, _ = server.get("/api/does-not-exist")
    assert status == 404
    assert body["error"] == "not_found"


def test_a_refused_post_reads_the_body_it_is_refusing(server):
    """Recusar uma rota não dispensa o servidor de consumir o corpo enviado.

    O que acontecia sem isto: o corpo do POST recusado ficava parado no buffer
    de recepção do socket, e fechar um socket nessa situação manda RST em vez
    de FIN -- no Windows, medido. O RST descarta a resposta que o servidor já
    havia escrito, e o cliente levanta ConnectionAbortedError (WinError 10053)
    sem nunca ver o 404. Medido em 6 falhas por 3000 POSTs, ~0,2%: pouco por
    requisição, o bastante para uma falha intermitente por suíte, e era a
    instabilidade de `test_webui_tools_gate.py`.

    Este teste NÃO reproduz aquela corrida -- corrida não é asserção. Ele
    testa o mesmo defeito pelo lado determinístico: duas requisições na MESMA
    conexão. Com o corpo da primeira sem ser lido, os bytes dele sobram no
    fluxo e viram a linha de requisição da segunda, que sai 400 em vez de 404.
    """
    corpo = b'{"campo": "valor"}'

    def pedido(fechar: bool) -> bytes:
        return (
            b"POST /api/nao-existe HTTP/1.1\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Content-Type: application/json; charset=utf-8\r\n"
            b"Content-Length: " + str(len(corpo)).encode() + b"\r\n"
            + (b"Connection: close\r\n" if fechar else b"")
            + b"\r\n" + corpo
        )

    recebido = b""
    with socket.create_connection(("127.0.0.1", server.port), timeout=5) as sock:
        # A primeira SEM `Connection: close`: é o keep-alive que faz a sobra
        # dela encostar na segunda, e é isso que o teste precisa exercer.
        sock.sendall(pedido(fechar=False))
        # A segunda COM, para o servidor fechar sozinho depois de responder.
        # Sem isso, ele fica bloqueado esperando uma terceira requisição, o
        # fim do `with` fecha o socket debaixo dele, e a suíte imprime um
        # traceback de ConnectionAbortedError que não é defeito de ninguém.
        sock.sendall(pedido(fechar=True))
        while recebido.count(b"HTTP/1.1 ") < 2:
            try:
                pedaco = sock.recv(4096)
            except socket.timeout:  # pragma: no cover -- só se o defeito voltar
                break
            if not pedaco:
                break
            recebido += pedaco

    assert recebido.count(b"HTTP/1.1 404") == 2, recebido
    # Explícito, porque é ESTE o código que o defeito produzia na segunda.
    assert b"HTTP/1.1 400" not in recebido, recebido


def test_known_path_wrong_method_is_405(server):
    # /api/chat/new only accepts POST.
    status, body, _ = server.get("/api/chat/new")
    assert status == 405
    assert body["error"] == "method_not_allowed"


def test_chat_action_paths_do_not_collide_with_conversation_lookup(server):
    # Guarda de regressão: o curinga de segmento único fica sob
    # `/api/chat/conversations/` justamente para nunca ser confundido com os
    # literais irmãos: versão longa em `997a6fe^`.
    for path in ("/api/chat/new", "/api/chat/message"):
        status, body, _ = server.get(path)
        assert status == 405, f"{path} unexpectedly matched a different route: {body}"


def test_index_page_served_at_root(server):
    status, raw, headers = server.request("GET", "/")
    assert status == 200
    assert b"<title>" in raw
    assert headers["Content-Type"].startswith("text/html")


def test_static_js_served_with_correct_content_type(server):
    status, raw, headers = server.request("GET", "/static/js/chat.js")
    assert status == 200
    assert headers["Content-Type"].startswith("text/javascript")
    assert b"conversation_id" in raw


def test_static_path_traversal_is_blocked(server):
    status, body, _ = server.get("/static/../../pyproject.toml")
    assert status == 404


def test_unknown_static_file_is_404(server):
    status, body, _ = server.get("/static/js/does-not-exist.js")
    assert status == 404


def test_check_demo_eval_pages_do_not_exist_without_a_password(server):
    # This server was started without one, so the evaluator's tools are not
    # merely refused -- they are not there. The full barrier (both unsigned
    # states, wrong method, assets) lives in test_webui_tools_gate.py; this
    # is the routing-level statement that they left PAGES.
    for path in ("/check", "/demo", "/eval"):
        status, _, _ = server.request("GET", path)
        assert status == 404, path


def test_the_chat_page_is_still_served_to_everyone(server):
    status, raw, headers = server.request("GET", "/")
    assert status == 200
    assert b"<title>" in raw
    assert headers["Content-Type"].startswith("text/html")


def test_audit_paths_do_not_collide_with_each_other(tmp_path):
    # Same hazard `handlers_chat` documents: the router matches in
    # registration order, with no literal-over-wildcard precedence:
    # versão longa em `997a6fe^`.
    running = RunningServer(tmp_path, audit_password="senha-de-teste")
    try:
        status, _, _ = running.login_as_auditor("senha-de-teste")
        assert status == 200

        # GET-only paths must 405 on POST, i.e. still resolve to themselves
        # rather than being captured by a wildcard sibling.
        for path in ("/api/audit/records", "/api/audit/session"):
            status, body, _ = running.post(path, {})
            assert status == 405, (path, body)

        # POST-only paths must 405 on GET for the same reason.
        for path in ("/api/audit/login", "/api/audit/logout", "/api/audit/telemetry"):
            status, body, _ = running.get(path)
            assert status == 405, (path, body)

        # session/events is a real route, not "events" read as a parameter.
        status, body, _ = running.get("/api/audit/session/events")
        assert status == 200, body
        assert "events" in body
    finally:
        running.close()
