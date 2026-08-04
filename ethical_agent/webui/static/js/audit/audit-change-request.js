// "Isso deveria ser diferente" — registra intenção e não muda nada, e as duas
// coisas que a redação carrega são de validade de pesquisa:
// REGISTRO, "Texto movido do código".

import { postJSON } from "../api.js";
import { track } from "./audit-telemetry.js";

export function createChangeRequestControl(match, recordEventId) {
  const wrap = document.createElement("div");
  wrap.className = "ea-audit-cr";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "ea-audit-cr__open";
  button.textContent = "Isso deveria ser diferente";
  wrap.appendChild(button);

  const form = document.createElement("form");
  form.className = "ea-audit-cr__form";
  form.hidden = true;

  const about = document.createElement("p");
  about.className = "ea-audit-cr__about";
  about.textContent = match.rule_id
    ? `Sobre a norma ${match.rule_id}, neste registro.`
    : "Sobre este registro.";
  form.appendChild(about);

  const warning = document.createElement("p");
  warning.className = "ea-audit-cr__warning";
  warning.textContent =
    "Isto não altera a política. Fica registrado como intenção, ancorado neste " +
    "registro e nesta norma. A edição efetiva das regras chega na próxima etapa — " +
    "até lá, o agente continua decidindo pela política atual.";
  form.appendChild(warning);

  const label = document.createElement("label");
  const noteId = `ea-audit-cr-note-${Math.random().toString(36).slice(2, 8)}`;
  label.setAttribute("for", noteId);
  label.textContent = "Motivo (opcional — pode deixar em branco)";
  form.appendChild(label);

  const note = document.createElement("textarea");
  note.id = noteId;
  note.rows = 3;
  note.placeholder = "Se quiser, diga o que está errado. Não é obrigatório.";
  form.appendChild(note);

  const recorded = document.createElement("p");
  recorded.className = "ea-audit-cr__recorded";
  recorded.textContent = "Esta marcação também fica registrada na sua sessão de auditoria.";
  form.appendChild(recorded);

  const actions = document.createElement("div");
  actions.className = "ea-audit-cr__actions";
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = "Registrar";
  actions.appendChild(submit);
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ea-audit-cr__cancel";
  cancel.textContent = "Cancelar";
  actions.appendChild(cancel);
  form.appendChild(actions);

  const status = document.createElement("p");
  status.className = "ea-audit-cr__status";
  status.setAttribute("role", "status");
  status.hidden = true;
  form.appendChild(status);

  wrap.appendChild(form);

  button.addEventListener("click", () => {
    form.hidden = !form.hidden;
    if (!form.hidden) note.focus();
  });
  cancel.addEventListener("click", () => {
    form.hidden = true;
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    try {
      const result = await postJSON("/api/audit/change-requests", {
        record_event_id: recordEventId,
        rule_id: match.rule_id || null,
        note: note.value,
      });
      track("change_request_submitted", {
        record_event_id: recordEventId,
        rule_id: match.rule_id || null,
        change_request_id: result.change_request_id,
        // The note itself goes to the change-requests file; the session log
        // only learns whether there was one.
        has_note: Boolean(note.value.trim()),
      });
      status.hidden = false;
      status.textContent = result.message;
      status.classList.add("ea-audit-cr__status--ok");
      note.value = "";
    } catch (err) {
      status.hidden = false;
      status.textContent = `Não foi possível registrar: ${err.message}`;
    } finally {
      submit.disabled = false;
    }
  });

  return wrap;
}
