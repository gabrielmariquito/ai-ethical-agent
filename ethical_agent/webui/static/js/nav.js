// Navegação de topo: Auditoria só existe quando o servidor subiu com senha,
// e o item renderiza desabilitado para dizê-lo — são TRÊS estados, não dois,
// porque "ninguém perguntou ainda" não é "o servidor disse não":
// versão longa em `997a6fe^`.

// DOIS tipos de item barrado, tratados diferente: Auditoria é barrada por
// *configuração* e renderiza desabilitada com distintivo; as ferramentas são
// barradas por *sessão* e renderizam ausentes —
// versão longa em `997a6fe^`.
const ITEMS = [
  { path: "/", label: "Conversa" },
  { path: "/check", label: "Avaliar texto", realm: "audit", needsSession: true },
  { path: "/demo", label: "Demo", realm: "audit", needsSession: true },
  { path: "/eval", label: "Eval", realm: "audit", needsSession: true },
  { path: "/audit", label: "Auditoria", realm: "audit", badge: "desativada" },
];

// Se quem chama tem sessão de auditoria: `GET /api/audit/session` já responde
// exatamente os três estados, então não há endpoint novo nem segundo eixo de
// permissão — versão longa em `997a6fe^`.
export async function probeSessionActive(auditEnabled) {
  if (!auditEnabled) return false;
  try {
    const response = await fetch("/api/audit/session", { method: "GET" });
    return response.ok;
  } catch (_networkErr) {
    return undefined; // nobody answered; not a claim either way
  }
}

export function renderNav(navEl, activePath, options = {}) {
  // Undefined stays undefined; only an actual boolean is a claim.
  const auditEnabled =
    options.auditEnabled === undefined || options.auditEnabled === null
      ? undefined
      : Boolean(options.auditEnabled);
  const sessionActive =
    options.sessionActive === undefined || options.sessionActive === null
      ? undefined
      : Boolean(options.sessionActive);
  navEl.innerHTML = "";
  navEl.setAttribute("role", "navigation");
  const list = document.createElement("ul");
  list.className = "ea-nav__list";

  for (const item of ITEMS) {
    // Session-gated items are absent unless the session is a definite yes.
    // Undefined -- nobody has asked yet -- renders nothing, same as false:
    // showing them and then removing them would be worse than arriving late.
    if (item.needsSession && !(auditEnabled && sessionActive === true)) {
      continue;
    }
    const li = document.createElement("li");
    const isActive = item.path === activePath;
    const enabled = item.realm === "audit" ? auditEnabled : true;
    // The badge is the *claim*, so it is the part that waits for an answer.
    // Unknown looks inert exactly like disabled -- clicking through to a
    // 404 would be worse -- it just does not say why.
    const known = enabled !== undefined;

    if (enabled) {
      const a = document.createElement("a");
      a.href = item.path;
      a.textContent = item.label;
      if (isActive) {
        a.classList.add("ea-nav__link--active");
        a.setAttribute("aria-current", "page");
      }
      li.appendChild(a);
    } else {
      const span = document.createElement("span");
      span.className = "ea-nav__link ea-nav__link--disabled";
      span.setAttribute("aria-disabled", "true");
      span.setAttribute("tabindex", "-1");
      span.textContent = item.label;
      if (item.badge && known) {
        const badge = document.createElement("small");
        badge.className = "ea-nav__badge";
        badge.textContent = item.badge;
        span.appendChild(badge);
      }
      li.appendChild(span);
    }
    list.appendChild(li);
  }
  navEl.appendChild(list);
}
