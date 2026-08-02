// Top navigation, shared by every screen. Auditoria only exists when the
// server was started with a password for it (`serve --audit-password-file`);
// otherwise the whole screen -- page, endpoints and assets -- 404s, and the
// item renders disabled here to say so rather than linking somewhere that
// isn't there. A disabled item must *look* inert, not just fail to respond
// to a click, so this sets aria-disabled + tabindex="-1" (no keyboard focus
// stop) instead of just omitting href, and app.css keys off
// [aria-disabled="true"] for the cursor/opacity/no-hover treatment.
//
// This is presentation only: hiding the link was never what keeps the trail
// separate (anyone can type the URL). The real barrier is server-side, in
// routing.match() -- see webui/auth.py.

const ITEMS = [
  { path: "/", label: "Conversa" },
  { path: "/check", label: "Avaliar texto" },
  { path: "/demo", label: "Demo" },
  { path: "/eval", label: "Eval" },
  { path: "/audit", label: "Auditoria", realm: "audit", badge: "desativada" },
];

export function renderNav(navEl, activePath, options = {}) {
  const auditEnabled = Boolean(options.auditEnabled);
  navEl.innerHTML = "";
  navEl.setAttribute("role", "navigation");
  const list = document.createElement("ul");
  list.className = "ea-nav__list";

  for (const item of ITEMS) {
    const li = document.createElement("li");
    const isActive = item.path === activePath;
    const enabled = item.realm === "audit" ? auditEnabled : true;

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
      if (item.badge) {
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
