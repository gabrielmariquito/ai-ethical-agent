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
//
// THREE states, not two. Whether the audit screen exists is only known once
// GET /api/choices has answered, and every screen renders the nav before
// that (see chat.js init: once immediately, once again after the fetch).
// This used to coerce the missing value with Boolean(), so the first render
// asserted "desativada" -- a definite claim about the server, made before
// asking it. When something then went wrong before the second render, the
// nav went on stating it indefinitely, and the operator had no way to tell
// "the server says no" apart from "nobody asked yet". Undefined is its own
// state, and it renders without the badge.

const ITEMS = [
  { path: "/", label: "Conversa" },
  { path: "/check", label: "Avaliar texto" },
  { path: "/demo", label: "Demo" },
  { path: "/eval", label: "Eval" },
  { path: "/audit", label: "Auditoria", realm: "audit", badge: "desativada" },
];

export function renderNav(navEl, activePath, options = {}) {
  // Undefined stays undefined; only an actual boolean is a claim.
  const auditEnabled =
    options.auditEnabled === undefined || options.auditEnabled === null
      ? undefined
      : Boolean(options.auditEnabled);
  navEl.innerHTML = "";
  navEl.setAttribute("role", "navigation");
  const list = document.createElement("ul");
  list.className = "ea-nav__list";

  for (const item of ITEMS) {
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
