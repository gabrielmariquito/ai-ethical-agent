from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Pattern, Tuple

# Populated at import time by each handlers_*.py module's @route(...)
# decorators. server.py imports every handlers_* module explicitly (a fixed,
# grep-able list, not plugin discovery) before constructing the server, so
# this is fully populated before the first request is served. Adding the
# audit screen later is one new handlers_audit.py + one import line here --
# the router itself does not change.
ROUTES: List["Route"] = []

_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class Route:
    method: str
    pattern: Pattern[str]
    handler: Callable


def _compile_pattern(path: str) -> Pattern[str]:
    def replace(match: "re.Match[str]") -> str:
        return f"(?P<{match.group(1)}>[^/]+)"

    regex_str = _PARAM_RE.sub(replace, path)
    return re.compile(f"^{regex_str}$")


def route(method: str, path: str):
    """Decorator: @route("GET", "/api/chat/{conversation_id}") registers a
    handler with signature handler(state, params: dict, body: dict)."""
    pattern = _compile_pattern(path)

    def decorator(handler: Callable) -> Callable:
        ROUTES.append(Route(method.upper(), pattern, handler))
        return handler

    return decorator


def match(method: str, path: str) -> Tuple[Optional[Callable], Optional[dict], bool]:
    """Returns (handler, params, path_known). `path_known` is True if some
    route's path pattern matched regardless of method, so callers can tell
    a 404 (no such path) apart from a 405 (right path, wrong method)."""
    path_known = False
    for candidate in ROUTES:
        m = candidate.pattern.match(path)
        if m is None:
            continue
        path_known = True
        if candidate.method == method.upper():
            return candidate.handler, m.groupdict(), True
    return None, None, path_known
