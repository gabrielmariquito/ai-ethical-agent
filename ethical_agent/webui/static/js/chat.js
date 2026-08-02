import { getJSON, postJSON, showErrorBanner, ApiError } from "./api.js";
import { renderMarkdown, escapeHtml } from "./markdown.js";
import { probeSessionActive, renderNav } from "./nav.js";
import { initConfigPanel } from "./config-panel.js";
import { initSidebar } from "./sidebar.js";
import { interventionKind, renderIntervention } from "./intervention-view.js";

const CONV_KEY = "ea.chat.conversation_id";
const TURNS_KEY = "ea.chat.turns";
const POLL_INTERVAL_MS = 300;

const PHASE_LABELS = {
  generating: "Gerando resposta…",
  verifying: "Verificando resposta…",
};

const els = {
  nav: document.getElementById("ea-nav"),
  configToggle: document.getElementById("ea-config-toggle"),
  configPanel: document.getElementById("ea-config-panel"),
  statusBar: document.getElementById("ea-statusbar"),
  transcript: document.getElementById("ea-transcript"),
  bannerHost: document.getElementById("ea-banner-host"),
  form: document.getElementById("ea-composer-form"),
  textarea: document.getElementById("ea-composer-input"),
  sendBtn: document.getElementById("ea-send-btn"),
  newConvBtn: document.getElementById("ea-new-conversation"),
  historyList: document.getElementById("ea-history-list"),
};

let conversationId = null;
let turns = []; // mirrored, display-only -- the server holds the real history
let configPanel = null;
let sidebar = null;
// Non-null while looking at a past conversation reconstructed from
// logs/audit.jsonl (see archive.py) instead of the live one -- the composer
// is disabled the whole time this is set, because a read-only turn was
// never fed back into agent.process() and never will be (see ARCHITECTURE
// notes in archive.py for why: no second copy of _build_messages's
// retention rules, and no ambiguity about what the model "remembers").
let viewingArchivedId = null;

// -------------------------------------------------------------- persistence

function loadMirroredTurns() {
  try {
    const raw = sessionStorage.getItem(TURNS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (_err) {
    return [];
  }
}

function saveMirror() {
  try {
    sessionStorage.setItem(CONV_KEY, conversationId || "");
    sessionStorage.setItem(TURNS_KEY, JSON.stringify(turns));
  } catch (_err) {
    // sessionStorage unavailable -- the mirror just won't survive a reload.
  }
}

function clearMirror() {
  try {
    sessionStorage.removeItem(CONV_KEY);
    sessionStorage.removeItem(TURNS_KEY);
  } catch (_err) {
    /* ignore */
  }
}

// ------------------------------------------------------------------ banners

function clearBanners() {
  els.bannerHost.innerHTML = "";
}

function showInfoBanner(message) {
  const banner = document.createElement("div");
  banner.className = "ea-info-banner";
  banner.setAttribute("role", "status");
  const text = document.createElement("span");
  text.textContent = message;
  banner.appendChild(text);
  const close = document.createElement("button");
  close.type = "button";
  close.className = "ea-error-banner__close";
  close.setAttribute("aria-label", "Fechar aviso");
  close.textContent = "×";
  close.addEventListener("click", () => banner.remove());
  banner.appendChild(close);
  els.bannerHost.prepend(banner);
}

// --------------------------------------------------------------- composer

function setComposerEnabled(enabled) {
  els.textarea.disabled = !enabled;
  els.sendBtn.disabled = !enabled;
}

// ------------------------------------------------------------ bootstrapping

async function openArchivedConversation(id, { banner } = {}) {
  const config = configPanel.getConfig();
  const data = await getJSON(
    `/api/chat/history/${id}?audit_log=${encodeURIComponent(config.audit_log)}`
  );
  viewingArchivedId = id;
  turns = data.turns.map((t) => Object.assign({}, t));
  clearBanners();
  showInfoBanner(
    banner ||
      "Esta conversa é somente leitura, reconstruída da trilha de auditoria: o modelo não tem esse contexto em memória."
  );
  setComposerEnabled(false);
  sidebar.setActive(id);
  renderTranscript();
}

async function bootstrapConversation() {
  const storedId = sessionStorage.getItem(CONV_KEY);
  const storedTurns = loadMirroredTurns();

  if (storedId) {
    let status = null;
    try {
      status = await getJSON(`/api/chat/conversations/${storedId}`);
    } catch (_err) {
      status = null;
    }
    if (status && status.exists && status.turn_count === storedTurns.length) {
      conversationId = storedId;
      turns = storedTurns;
      sidebar.setActive(conversationId);
      renderTranscript();
      return;
    }
    // The live conversation is gone (server restarted) or diverged from
    // what's mirrored -- the mirror is never partially trusted (see the
    // plan's "Reconciliação após F5"). If the trail still has it, offer it
    // read-only instead of losing it outright; otherwise just start fresh.
    clearMirror();
    try {
      await openArchivedConversation(storedId, {
        banner:
          "O servidor foi reiniciado: esta conversa está sendo mostrada em modo somente leitura, reconstruída da trilha de auditoria.",
      });
      return;
    } catch (_err) {
      showErrorBanner(els.bannerHost, {
        message: "A conversa anterior não pôde ser recuperada; iniciando uma nova conversa.",
      });
    }
  }

  await startNewConversation();
}

async function startNewConversation() {
  try {
    const created = await postJSON("/api/chat/new");
    conversationId = created.conversation_id;
    turns = [];
    viewingArchivedId = null;
    saveMirror();
    clearBanners();
    setComposerEnabled(true);
    setStatus(statusFromConfig());
    sidebar.setActive(conversationId);
    renderTranscript();
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  }
}

// ------------------------------------------------------------------ status

function setStatus(text) {
  els.statusBar.textContent = text;
}

function statusFromConfig() {
  const config = configPanel.getConfig();
  const mockNote = config.mock ? " (mock)" : "";
  return `Engine configurado: ${config.engine} · modelo: ${config.model}${mockNote}`;
}

function updateStatusFromLastTurn() {
  const last = turns[turns.length - 1];
  if (!last) return;
  const engineName = (last.input_verdict && last.input_verdict.engine) || "?";
  setStatus(`Engine: ${engineName} · ${last.llm_provenance_text || ""}`);
}

// -------------------------------------------------------------- transcript

function renderEmptyState() {
  els.transcript.innerHTML = `
    <div class="ea-empty-state">
      <h1>Ethical Agent</h1>
      <p>Converse com um agente de linguagem protegido por um guardrail ético
      neurossimbólico. Toda entrada e toda saída gerada passam pelo guardrail
      antes de chegar até você.</p>
      <p><strong>Toda decisão é registrada em <code>logs/audit.jsonl</code>,
      por design.</strong></p>
    </div>`;
}

function renderTranscript() {
  els.transcript.innerHTML = "";
  if (turns.length === 0) {
    renderEmptyState();
    return;
  }
  for (const turn of turns) {
    els.transcript.appendChild(buildUserTurnEl(turn.user_text));
    els.transcript.appendChild(buildAssistantTurnEl(turn));
  }
  updateStatusFromLastTurn();
  scrollToBottom();
}

function scrollToBottom() {
  els.transcript.scrollTop = els.transcript.scrollHeight;
}

function renderCopyButton(turn) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "ea-copy-btn";
  btn.textContent = "Copiar registro";
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(turn, null, 2));
      btn.textContent = "Copiado!";
    } catch (_err) {
      btn.textContent = "Não foi possível copiar";
    }
    setTimeout(() => {
      btn.textContent = "Copiar registro";
    }, 1500);
  });
  return btn;
}

function buildUserTurnEl(text) {
  const el = document.createElement("div");
  el.className = "ea-turn ea-turn--user";
  const bubble = document.createElement("div");
  bubble.className = "ea-bubble";
  bubble.textContent = text;
  el.appendChild(bubble);
  return el;
}

function renderMockFallbackNotice(turn) {
  const provenance = turn.llm_provenance || {};
  const reason = provenance.fallback_reason || "motivo não informado";
  const el = document.createElement("div");
  el.className = "ea-fallback-notice";
  el.setAttribute("role", "status");
  el.innerHTML = `
    <p><strong>O modelo não pôde ser contatado.</strong> A resposta abaixo é simulada, não veio de um modelo real.</p>
    <p class="ea-fallback-notice__reason">Motivo: ${escapeHtml(reason)}</p>
    <p>Para usar um modelo de verdade: inicie o Ollama (<code>ollama serve</code>) e confirme que o
    modelo configurado já foi baixado (<code>ollama pull &lt;modelo&gt;</code>). Se preferir continuar
    em modo simulado de propósito, marque a caixa <strong>Mock</strong> em Configuração.</p>`;
  return el;
}

function buildAssistantTurnEl(turn) {
  const kind = interventionKind(turn);
  const el = document.createElement("div");
  el.className = "ea-turn ea-turn--assistant";

  // Surfaced as a visible notice in the transcript, not just the status
  // bar: with Mock unchecked by default, this fallback is the first thing
  // someone without Ollama running will hit, and a status-bar-only mention
  // is too easy to miss to explain why the reply is a canned string.
  // Doesn't apply to blocked_input -- the model was never called there, so
  // "couldn't be reached" would describe something that was never tried.
  const showFallbackNotice =
    kind !== "blocked_input" && turn.llm_provenance && turn.llm_provenance.kind === "mock_fallback";
  if (showFallbackNotice) {
    el.appendChild(renderMockFallbackNotice(turn));
  }

  if (kind === "blocked_input") {
    // The model was never called: no assistant bubble, the intervention
    // block stands in its place.
    el.appendChild(renderIntervention(turn));
  } else {
    const bubble = document.createElement("div");
    bubble.className = "ea-bubble";
    bubble.innerHTML = renderMarkdown(turn.message || "");
    el.appendChild(bubble);
    if (kind !== "none") {
      el.appendChild(renderIntervention(turn));
    }
  }

  const actions = document.createElement("div");
  actions.className = "ea-turn__actions";
  actions.appendChild(renderCopyButton(turn));
  el.appendChild(actions);
  return el;
}

function renderProgress(phase) {
  const el = document.createElement("div");
  el.className = "ea-progress";
  const label = PHASE_LABELS[phase] || PHASE_LABELS.generating;
  el.innerHTML = `<span class="ea-progress__dot"></span><span>${escapeHtml(label)}</span>`;
  return el;
}

// -------------------------------------------------------------- sending

async function sendMessage(text) {
  if (viewingArchivedId !== null) return; // composer should already be disabled; defensive only

  els.textarea.disabled = true;
  els.sendBtn.disabled = true;

  if (turns.length === 0) els.transcript.innerHTML = "";
  const userTurnEl = buildUserTurnEl(text);
  els.transcript.appendChild(userTurnEl);
  let progressEl = renderProgress("generating");
  els.transcript.appendChild(progressEl);
  scrollToBottom();

  try {
    const config = configPanel.getConfig();
    const { job_id: jobId } = await postJSON("/api/chat/message", {
      conversation_id: conversationId,
      text,
      config,
    });

    let job;
    for (;;) {
      job = await getJSON(`/api/chat/jobs/${jobId}`);
      if (job.phase === "done" || job.phase === "error") break;
      const fresh = renderProgress(job.phase);
      progressEl.replaceWith(fresh);
      progressEl = fresh;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
    progressEl.remove();

    if (job.phase === "error") {
      userTurnEl.remove();
      showErrorBanner(els.bannerHost, {
        message: `Não foi possível processar a mensagem (${job.error.error}): ${job.error.message}`,
      });
      return;
    }

    const turnRecord = Object.assign({ user_text: text }, job.result);
    turns.push(turnRecord);
    saveMirror();
    els.transcript.appendChild(buildAssistantTurnEl(turnRecord));
    updateStatusFromLastTurn();
    scrollToBottom();
    sidebar.refresh(); // this turn just landed in the audit trail
  } catch (err) {
    progressEl.remove();
    userTurnEl.remove();
    showErrorBanner(els.bannerHost, err instanceof ApiError ? err : { message: String(err) });
  } finally {
    if (viewingArchivedId === null) {
      els.textarea.disabled = false;
      els.sendBtn.disabled = false;
      els.textarea.focus();
    }
  }
}

// --------------------------------------------------------------- composer

function autoGrow() {
  els.textarea.style.height = "auto";
  els.textarea.style.height = `${els.textarea.scrollHeight}px`;
}

els.textarea.addEventListener("input", autoGrow);

els.textarea.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    els.form.requestSubmit();
  }
});

els.form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (viewingArchivedId !== null) return;
  const text = els.textarea.value.trim();
  if (!text) return;
  els.textarea.value = "";
  autoGrow();
  sendMessage(text);
});

els.newConvBtn.addEventListener("click", startNewConversation);

// ------------------------------------------------------------------- init

async function init() {
  renderNav(els.nav, "/");
  setComposerEnabled(false);
  try {
    configPanel = await initConfigPanel(els.configPanel, els.configToggle);
    // Re-render now that we know whether the audit screen exists on this
    // server (initConfigPanel already fetched /api/choices) and whether this
    // browser holds an audit session. The employee's chat has neither, and
    // renders one item; the evaluator's has both, and renders all five.
    const sessionActive = await probeSessionActive(configPanel.auditScreenEnabled);
    renderNav(els.nav, "/", {
      auditEnabled: configPanel.auditScreenEnabled,
      sessionActive,
    });
    setStatus(statusFromConfig());
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
    return;
  }

  sidebar = initSidebar(els.historyList, {
    onSelect: (id) => {
      if (id === conversationId && viewingArchivedId === null) return; // already viewing it, live
      openArchivedConversation(id).catch((err) => showErrorBanner(els.bannerHost, err));
    },
    getAuditLogPath: () => configPanel.getConfig().audit_log,
  });
  sidebar.refresh();

  try {
    await bootstrapConversation();
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  }
  if (viewingArchivedId === null) setComposerEnabled(true);
  els.textarea.focus();
}

init();
