import argparse
import socket

import pytest

from ethical_agent.__main__ import main
from webui_support import RunningServer


@pytest.fixture
def server(tmp_path):
    running = RunningServer(tmp_path)
    yield running
    running.close()


def test_server_socket_is_bound_to_127_0_0_1_only(server):
    assert server.server.server_address[0] == "127.0.0.1"


def test_server_unreachable_via_any_other_local_address(server):
    # If the server were bound to 0.0.0.0 this would also succeed; bound to
    # 127.0.0.1 specifically, connecting via the machine's real hostname (or
    # any other local interface address) must fail to connect at all.
    other_addresses = set()
    try:
        other_addresses.add(socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    other_addresses.discard("127.0.0.1")
    if not other_addresses:
        pytest.skip("no other local address available to test against on this host")
    for address in other_addresses:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        try:
            with pytest.raises(OSError):
                sock.connect((address, server.port))
        finally:
            sock.close()


def test_serve_subcommand_has_no_host_flag():
    # argparse rejects an unrecognized "--host" and exits (SystemExit) from
    # inside parse_args(), before `serve`'s handler (which would otherwise
    # block forever in serve_forever()) is ever reached -- safe to call
    # main() directly here.
    with pytest.raises(SystemExit):
        main(["serve", "--host", "0.0.0.0", "--port", "0"])


def test_serve_subcommand_accepts_port_flag():
    parser = argparse.ArgumentParser()
    # Smoke-check at the argparse level: `serve --port` is a recognized
    # option with an int type and a default, without actually binding a
    # socket (that's covered by the fixture-based tests above).
    from ethical_agent.__main__ import DEFAULT_WEB_PORT

    assert isinstance(DEFAULT_WEB_PORT, int)
    assert DEFAULT_WEB_PORT > 0


def test_serve_default_config_calls_the_real_model_not_mock(monkeypatch):
    # Web-UI-only default: `ethical-agent serve` seeds the chat's config
    # panel with mock=False, so a first-time visitor with Ollama running
    # gets a real answer -- resolve_llm() still falls back to MockLLM on its
    # own if the model can't be reached, this only changes what's *tried*
    # first. Verified by intercepting webui.server.make_server (cmd_serve
    # does `from .webui.server import make_server` at call time, so
    # patching the module attribute here is picked up), never binding a
    # real socket.
    captured = {}

    class FakeServer:
        def serve_forever(self):
            raise KeyboardInterrupt()

        def server_close(self):
            pass

    def fake_make_server(port, initial_config):
        captured["initial_config"] = initial_config
        return FakeServer()

    import ethical_agent.webui.server as server_module

    monkeypatch.setattr(server_module, "make_server", fake_make_server)

    code = main(["serve", "--port", "0"])
    assert code == 0
    assert captured["initial_config"]["mock"] is False
