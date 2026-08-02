// Left-hand conversation list. Sourced entirely from GET /api/chat/history
// (which reads logs/audit.jsonl -- see archive.py); this module holds no
// state of its own beyond "what's currently selected" for highlighting.
// The endpoint already caps the list and scans the trail backward, so this
// module doesn't need to worry about a large audit.jsonl either.

import { getJSON } from "./api.js";

const ACTIVE_CLASS = "ea-sidebar__item--active";

function formatTimestamp(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  const time = date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  const day = date.toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
  return `${day} ${time}`;
}

export function initSidebar(listEl, { onSelect, getAuditLogPath }) {
  let activeId = null;
  let lastConversations = [];
  let lastTruncated = false;

  function render() {
    listEl.innerHTML = "";
    if (lastConversations.length === 0) {
      const empty = document.createElement("p");
      empty.className = "ea-sidebar__empty";
      empty.textContent = "Nenhuma conversa anterior.";
      listEl.appendChild(empty);
      return;
    }
    for (const conv of lastConversations) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "ea-sidebar__item";
      if (conv.conversation_id === activeId) item.classList.add(ACTIVE_CLASS);

      const preview = document.createElement("span");
      preview.className = "ea-sidebar__preview";
      preview.textContent = conv.preview || "(sem prévia)";

      const meta = document.createElement("span");
      meta.className = "ea-sidebar__meta";
      const n = conv.turn_count;
      const when = formatTimestamp(conv.updated_at);
      meta.textContent = `${n} turno${n === 1 ? "" : "s"}${when ? ` · ${when}` : ""}`;

      item.appendChild(preview);
      item.appendChild(meta);
      item.addEventListener("click", () => onSelect(conv.conversation_id));
      listEl.appendChild(item);
    }
    if (lastTruncated) {
      const note = document.createElement("p");
      note.className = "ea-sidebar__empty";
      note.textContent = "Mostrando as mais recentes.";
      listEl.appendChild(note);
    }
  }

  return {
    async refresh() {
      try {
        const auditLog = getAuditLogPath();
        const data = await getJSON(`/api/chat/history?audit_log=${encodeURIComponent(auditLog)}`);
        lastConversations = data.conversations;
        lastTruncated = Boolean(data.truncated);
        render();
      } catch (_err) {
        // Sidebar failing to load isn't fatal to the chat itself -- leave
        // whatever was last rendered (possibly empty) rather than blocking.
      }
    },
    setActive(conversationId) {
      activeId = conversationId;
      render();
    },
  };
}
