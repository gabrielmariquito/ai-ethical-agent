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

// TWO kinds of gated item, and they are not treated alike.
//
// Auditoria is gated on *configuration*: it exists whenever the server was
// started with a password. When it is not, the item renders disabled with a
// badge, because the operator needs to learn the area exists and how to turn
// it on -- see the three-state note above.
//
// Avaliar texto / Demo / Eval are gated on *session*: they are the
// evaluator's instruments, and the employee running the chat is not their
// audience. These render absent, never disabled-with-a-badge. An area that
// does not exist for you is not announced to you; and four inert items would
// be four announcements of areas the reader cannot open. Auditoria is the one
// door, and one door is enough to find the rest behind it.
//
// Absence here is presentation, exactly as the note above says. The barrier
// is server-side: routing.match() skips these routes without a session,
// before path_known, so they 404 rather than 401 (see routing.Route).
const ITEMS = [
  { path: "/", label: "Conversa" },
  { path: "/check", label: "Avaliar texto", realm: "audit", needsSession: true },
  { path: "/demo", label: "Demo", realm: "audit", needsSession: true },
  { path: "/eval", label: "Eval", realm: "audit", needsSession: true },
  { path: "/audit", label: "Auditoria", realm: "audit", badge: "desativada" },
];

// Whether the caller holds an audit session. GET /api/audit/session already
// answers exactly the three states -- 404 without a password, 401 without a
// session, 200 with one -- so no new endpoint and no second permission axis.
// Only asked when the realm is on, to avoid a 401 in the log on every page
// load of a server that has no audit screen at all.
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
