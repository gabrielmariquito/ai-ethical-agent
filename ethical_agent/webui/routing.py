from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Pattern, Tuple

# Populated at import time by each handlers_*.py module's @route(...)
# decorators. server.py imports every handlers_* module explicitly (a fixed,
# grep-able list, not plugin discovery) before constructing the server, so
# this is fully populated before the first request is served.
#
# A route may declare a `realm`: a named group of routes that only exists
# when the server was started with the configuration that realm needs (today
# the only one is "audit", which needs a password -- see auth.py). Routes of
# a disabled realm are skipped by match() *before* path_known is set, so a
# request for one is indistinguishable from a request for a path nobody ever
# registered -- see the comment in match() for why that ordering is the whole
# point rather than a detail.
ROUTES: List["Route"] = []

_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class Route:
    method: str
    pattern: Pattern[str]
    handler: Callable
    realm: Optional[str] = None
    requires_session: bool = False


def _compile_pattern(path: str) -> Pattern[str]:
    def replace(match: "re.Match[str]") -> str:
        return f"(?P<{match.group(1)}>[^/]+)"

    regex_str = _PARAM_RE.sub(replace, path)
    return re.compile(f"^{regex_str}$")


def route(method: str, path: str, realm: Optional[str] = None, requires_session: bool = False):
    """Decorator: @route("GET", "/api/chat/{conversation_id}") registers a
    handler with signature handler(state, params: dict, body: dict).

    `realm` names the configuration gate the route lives behind (see ROUTES'
    comment). `requires_session` asks httphandler to reject the request with
    401 unless the caller presented a valid session for that realm -- the
    check is central, in the dispatcher, so that a handler added later cannot
    forget to perform it.
    """
    pattern = _compile_pattern(path)

    def decorator(handler: Callable) -> Callable:
        ROUTES.append(Route(method.upper(), pattern, handler, realm, requires_session))
        return handler

    return decorator


def match(
    method: str, path: str, realm_enabled: Optional[Callable[[str], bool]] = None
) -> Tuple[Optional["Route"], Optional[dict], bool]:
    """Returns (route, params, path_known). `path_known` is True if some
    route's path pattern matched regardless of method, so callers can tell
    a 404 (no such path) apart from a 405 (right path, wrong method).

    `realm_enabled(realm) -> bool` decides whether a realm's routes exist at
    all right now; None means "every realm is enabled" (used by tests that
    exercise the router directly).

    A route in a disabled realm is skipped *before* path_known is set. That
    ordering is load-bearing, not tidiness: if it were skipped afterwards, a
    POST to a GET-only audit path would answer 405 instead of 404 and thereby
    confirm the endpoint exists to anyone poking at the URL -- which is
    exactly the thing the password is there to prevent. The whole separation
    is only as real as this branch.

    Returns the Route (not the bare handler) so the dispatcher can read
    requires_session from one place instead of every handler re-checking it.
    """
    path_known = False
    for candidate in ROUTES:
        if (
            candidate.realm is not None
            and realm_enabled is not None
            and not realm_enabled(candidate.realm)
        ):
            continue
        m = candidate.pattern.match(path)
        if m is None:
            continue
        path_known = True
        if candidate.method == method.upper():
            return candidate, m.groupdict(), True
    return None, None, path_known
