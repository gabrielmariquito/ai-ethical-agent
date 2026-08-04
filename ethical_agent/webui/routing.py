from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, List, Optional, Pattern, Tuple

# Populado no import pelos decoradores `@route`, e uma rota pode declarar um
# `realm`: grupo nomeado que só existe quando o servidor subiu com a
# configuração daquele realm — versão longa em `997a6fe^`.
ROUTES: List["Route"] = []

_PARAM_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


@dataclass
class Route:
    method: str
    pattern: Pattern[str]
    handler: Callable
    realm: Optional[str] = None
    requires_session: bool = False
    hidden_without_session: bool = False
    """Answer 404 (not 401) to a caller with no session, by being skipped in
    match() before path_known -- the same treatment a disabled realm gets.

    Deliberately NOT the default for requires_session routes. /api/audit/*
    answers 401 because /audit is a login screen: it has to tell "you are not
    signed in" apart from "this does not exist", or it cannot decide whether
    to show the form. Check/Demo/Eval have no login shell of their own, so
    nothing needs that distinction and there is no reason to confirm the
    endpoint to someone who cannot use it. The criterion is "a route with no
    front door of its own does not announce itself", which is what makes this
    one rule rather than two."""


def _compile_pattern(path: str) -> Pattern[str]:
    def replace(match: "re.Match[str]") -> str:
        return f"(?P<{match.group(1)}>[^/]+)"

    regex_str = _PARAM_RE.sub(replace, path)
    return re.compile(f"^{regex_str}$")


def route(
    method: str,
    path: str,
    realm: Optional[str] = None,
    requires_session: bool = False,
    hidden_without_session: bool = False,
):
    """Decorador que registra um handler; `realm` nomeia o portão de
    configuração e `requires_session` faz o dispatcher recusar centralmente,
    para que um handler novo não possa esquecer de conferir: versão longa em `997a6fe^`.
    """
    pattern = _compile_pattern(path)

    def decorator(handler: Callable) -> Callable:
        ROUTES.append(
            Route(
                method.upper(),
                pattern,
                handler,
                realm,
                requires_session,
                hidden_without_session,
            )
        )
        return handler

    return decorator


def match(
    method: str,
    path: str,
    realm_enabled: Optional[Callable[[str], bool]] = None,
    has_session: Optional[Callable[[], bool]] = None,
) -> Tuple[Optional["Route"], Optional[dict], bool]:
    """Devolve (rota, params, path_known), com `path_known` distinguindo 404 de
    405; `realm_enabled` e `has_session` são injetados para que o roteador
    seja testável direto: versão longa em `997a6fe^`.
    """
    path_known = False
    for candidate in ROUTES:
        if (
            candidate.realm is not None
            and realm_enabled is not None
            and not realm_enabled(candidate.realm)
        ):
            continue
        if (
            candidate.hidden_without_session
            and has_session is not None
            and not has_session()
        ):
            continue
        m = candidate.pattern.match(path)
        if m is None:
            continue
        path_known = True
        if candidate.method == method.upper():
            return candidate, m.groupdict(), True
    return None, None, path_known
