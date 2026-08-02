// Top navigation, shared by every screen. Auditoria is the next screen
// (comes in a later change); it renders here already, disabled, so the nav
// structure doesn't have to be invented later -- a disabled item must
// *look* inert, not just fail to respond to a click, so this sets
// aria-disabled + tabindex="-1" (no keyboard focus stop) instead of just
// omitting href, and app.css keys off [aria-disabled="true"] for the
// cursor/opacity/no-hover treatment.

const ITEMS = [
  { path: "/", label: "Conversa", enabled: true },
  { path: "/check", label: "Avaliar texto", enabled: true },
  { path: "/demo", label: "Demo", enabled: true },
  { path: "/eval", label: "Eval", enabled: true },
  { path: "/audit", label: "Auditoria", enabled: false, badge: "em breve" },
];

export function renderNav(navEl, activePath) {
  navEl.innerHTML = "";
  navEl.setAttribute("role", "navigation");
  const list = document.createElement("ul");
  list.className = "ea-nav__list";

  for (const item of ITEMS) {
    const li = document.createElement("li");
    const isActive = item.path === activePath;

    if (item.enabled) {
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
