// Sequência da conversa: uma decisão isolada raramente é julgável, então
// registros do mesmo `conversation_id` são legíveis em ordem.

import { getJSON } from "../api.js";
import { gravityLabel } from "./audit-layers.js";
import { track } from "./audit-telemetry.js";

export function createConversationStrip(conversationId, currentEventId, onOpenRecord) {
  const section = document.createElement("section");
  section.className = "ea-audit-conversation";

  const title = document.createElement("h4");
  title.textContent = "Esta decisão dentro da conversa";
  section.appendChild(title);

  const status = document.createElement("p");
  status.className = "ea-audit-hint";
  status.textContent = "Carregando os outros turnos…";
  section.appendChild(status);

  getJSON(`/api/audit/conversations/${encodeURIComponent(conversationId)}`)
    .then((data) => {
      status.remove();
      const position = data.turns.findIndex((t) => t.event_id === currentEventId);

      const where = document.createElement("p");
      where.className = "ea-audit-conversation__where";
      where.textContent =
        position >= 0
          ? `Você está no turno ${position + 1} de ${data.turns.length}.`
          : `Esta conversa tem ${data.turns.length} turno(s).`;
      section.appendChild(where);

      if (!data.complete) {
        const partial = document.createElement("p");
        partial.className = "ea-audit-scan ea-audit-scan--warn";
        partial.textContent =
          "Não cheguei ao primeiro turno desta conversa dentro do limite de varredura: a sequência abaixo pode estar incompleta.";
        section.appendChild(partial);
      }
      if (data.turn_index_duplicates && data.turn_index_duplicates.length > 0) {
        const dup = document.createElement("p");
        dup.className = "ea-audit-scan ea-audit-scan--warn";
        dup.textContent = `A trilha tem mais de um registro para o(s) turno(s) ${data.turn_index_duplicates.join(", ")}; a ordem abaixo pode não ser a real.`;
        section.appendChild(dup);
      }

      const list = document.createElement("ol");
      list.className = "ea-audit-conversation__turns";
      for (const turn of data.turns) {
        const li = document.createElement("li");
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = `ea-audit-turn ea-audit-turn--${turn.gravity}`;
        if (turn.event_id === currentEventId) {
          btn.classList.add("ea-audit-turn--current");
          btn.setAttribute("aria-current", "true");
        }

        const head = document.createElement("span");
        head.className = "ea-audit-turn__head";
        head.textContent = `Turno ${turn.turn_index ?? "?"}`;
        if (turn.gravity !== "none") {
          const badge = document.createElement("span");
          badge.className = `ea-audit-badge ea-audit-badge--${turn.gravity}`;
          badge.textContent = gravityLabel(turn.gravity);
          head.appendChild(badge);
        }
        btn.appendChild(head);

        const preview = document.createElement("span");
        preview.className = "ea-audit-turn__preview";
        preview.textContent = turn.preview || "(sem texto de entrada)";
        btn.appendChild(preview);

        btn.addEventListener("click", () => {
          if (turn.event_id === currentEventId) return;
          track("conversation_turn_focused", {
            conversation_id: conversationId,
            record_event_id: turn.event_id,
            turn_index: turn.turn_index,
          });
          onOpenRecord(turn, "conversation");
        });
        li.appendChild(btn);
        list.appendChild(li);
      }
      section.appendChild(list);

      track("conversation_opened", {
        conversation_id: conversationId,
        turn_count: data.turns.length,
        from_record_event_id: currentEventId,
        complete: data.complete,
      });
    })
    .catch((err) => {
      status.textContent = `Não foi possível carregar a conversa: ${err.message}`;
    });

  return section;
}
