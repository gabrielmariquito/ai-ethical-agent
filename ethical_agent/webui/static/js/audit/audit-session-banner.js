// The permanent "this session is being recorded" strip.
//
// Not dismissible, on purpose. A disclosure that can be closed is a
// disclosure that is read once and then absent for the rest of the session,
// which in an application about transparency is the wrong default. It is a
// strip rather than a modal so it costs attention once and then stays
// legible without blocking the work.
//
// Every claim it makes comes from GET /api/audit/session -- the event list
// is the server's own catalog of what it can write, not a promise this page
// makes about itself.

import { getJSON } from "../api.js";
import { onEventCount, track } from "./audit-telemetry.js";

export function renderSessionBanner(hostEl, session) {
  hostEl.innerHTML = "";

  const strip = document.createElement("section");
  strip.className = "ea-audit-session";
  strip.setAttribute("role", "status");

  const line = document.createElement("p");
  line.className = "ea-audit-session__line";

  const dot = document.createElement("span");
  dot.className = "ea-audit-session__dot";
  dot.setAttribute("aria-hidden", "true");
  line.appendChild(dot);

  const text = document.createElement("span");
  text.textContent = "Esta sessão de auditoria está sendo registrada para a pesquisa";
  line.appendChild(text);

  const counter = document.createElement("strong");
  counter.className = "ea-audit-session__counter";
  counter.textContent = "0 eventos";
  line.appendChild(counter);
  onEventCount((count) => {
    counter.textContent = count === 1 ? "1 evento" : `${count} eventos`;
  });

  const sid = document.createElement("code");
  sid.className = "ea-audit-session__id";
  sid.textContent = `sessão ${String(session.session_id).slice(0, 8)}`;
  sid.title = "Identificador anônimo desta sessão. Não está ligado a você.";
  line.appendChild(sid);

  strip.appendChild(line);

  const details = document.createElement("details");
  details.className = "ea-audit-session__details";
  const summary = document.createElement("summary");
  summary.textContent = "O que exatamente é registrado";
  details.appendChild(summary);

  const files = document.createElement("p");
  files.className = "ea-audit-session__files";
  files.textContent = `Arquivo: ${session.auditor_log_path || "(indisponível)"}. `;
  files.appendChild(
    document.createTextNode(
      `A trilha do agente, que você está lendo, é outro arquivo: ${session.audit_log_path}. ` +
        "Os dois nunca se misturam — o que você faz aqui não entra no registro das decisões do agente."
    )
  );
  details.appendChild(files);

  const noPii = document.createElement("p");
  noPii.textContent =
    "Não são coletados nome, e-mail, endereço de rede nem identificação do navegador. " +
    "O único identificador é o código de sessão acima, gerado no servidor quando você entrou.";
  details.appendChild(noPii);

  const listTitle = document.createElement("p");
  listTitle.className = "ea-audit-label";
  listTitle.textContent = "Tipos de evento que podem ser gravados:";
  details.appendChild(listTitle);

  const list = document.createElement("ul");
  list.className = "ea-audit-session__events";
  for (const item of session.event_types || []) {
    const li = document.createElement("li");
    const code = document.createElement("code");
    code.textContent = item.type;
    li.appendChild(code);
    li.appendChild(document.createTextNode(` — ${item.description}`));
    list.appendChild(li);
  }
  details.appendChild(list);

  if (session.auditor_log_warning) {
    const warn = document.createElement("p");
    warn.className = "ea-audit-scan ea-audit-scan--warn";
    warn.textContent = session.auditor_log_warning;
    details.appendChild(warn);
  }

  const viewBtn = document.createElement("button");
  viewBtn.type = "button";
  viewBtn.className = "ea-audit-session__view";
  viewBtn.textContent = "Ver meus eventos desta sessão";
  const viewOut = document.createElement("div");
  viewOut.className = "ea-audit-session__viewout";
  viewBtn.addEventListener("click", async () => {
    viewBtn.disabled = true;
    try {
      // Reading your own trail is itself recorded -- said here rather than
      // discovered later, because a transparency screen with one quiet
      // exception in it is not one.
      const data = await getJSON("/api/audit/session/events?limit=200");
      viewOut.innerHTML = "";
      const note = document.createElement("p");
      note.className = "ea-audit-hint";
      note.textContent = `${data.count} evento(s). Esta leitura também foi registrada.`;
      viewOut.appendChild(note);
      const pre = document.createElement("pre");
      pre.className = "ea-audit-pre";
      pre.textContent = data.events.map((e) => JSON.stringify(e)).join("\n");
      viewOut.appendChild(pre);
    } catch (err) {
      viewOut.textContent = `Não foi possível ler: ${err.message}`;
    } finally {
      viewBtn.disabled = false;
    }
  });
  details.appendChild(viewBtn);
  details.appendChild(viewOut);

  strip.appendChild(details);

  const trail = document.createElement("p");
  trail.className = "ea-audit-session__trail";
  trail.textContent = `Trilha em leitura: ${session.audit_log_path} (somente leitura)`;
  strip.appendChild(trail);

  hostEl.appendChild(strip);
  return strip;
}

export { track };
