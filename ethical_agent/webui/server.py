from __future__ import annotations

from http.server import ThreadingHTTPServer

# Importing these registers their @routing.route(...) handlers as a side
# effect. Explicit, fixed list (not plugin discovery) so it stays grep-able;
# adding the audit screen later means adding one more import line here.
from . import (  # noqa: F401
    handlers_browse,
    handlers_chat,
    handlers_check,
    handlers_choices,
    handlers_demo,
    handlers_eval,
    handlers_history,
)
from .httphandler import make_handler
from .state import ServerState


def make_server(port: int, initial_config: dict) -> ThreadingHTTPServer:
    """Binds to 127.0.0.1 only -- never 0.0.0.0, no flag to change that.
    This server exposes the guardrail pipeline and (indirectly, via what it
    writes) the audit trail; it must not be reachable from the network by
    accident."""
    state = ServerState(initial_config)
    handler_cls = make_handler(state)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    server.daemon_threads = True
    # Exposed for tests that need to reach into ServerState (job registry GC,
    # conversation store) without a second, parallel way to construct it.
    # Not used by any handler -- they all receive `state` as an argument.
    server.state = state
    return server
