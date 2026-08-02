import { getJSON, postJSON, showErrorBanner } from "./api.js";
import { renderNav } from "./nav.js";
import { initConfigPanel } from "./config-panel.js";
import { renderVerdict } from "./verdict-view.js";

// The raw stage values ("input"/"output") stay canonical -- gui_choices.py
// is still the single source of truth for what values exist -- but this
// screen describes them in plain language instead of the bare word, since
// which one applies is exactly what a policy author needs to reason about
// before reading the result.
const STAGE_COPY = {
  input: "Antes de enviar ao modelo (entrada)",
  output: "Depois de gerado pelo modelo (saída)",
};

const els = {
  nav: document.getElementById("ea-nav"),
  configToggle: document.getElementById("ea-config-toggle"),
  configPanel: document.getElementById("ea-config-panel"),
  bannerHost: document.getElementById("ea-banner-host"),
  form: document.getElementById("ea-check-form"),
  textarea: document.getElementById("ea-check-input"),
  stageSelect: document.getElementById("ea-check-stage"),
  submitBtn: document.getElementById("ea-check-submit"),
  result: document.getElementById("ea-check-result"),
};

let configPanel = null;

function clearBanners() {
  els.bannerHost.innerHTML = "";
}

function renderResult(data) {
  els.result.innerHTML = "";

  if (data.audit_notices && data.audit_notices.length > 0) {
    const notices = document.createElement("p");
    notices.className = "ea-tool-notices";
    notices.textContent = data.audit_notices.join(" ");
    els.result.appendChild(notices);
  }

  const summary = document.createElement("p");
  summary.className = "ea-tool-summary";
  summary.textContent = data.intervened
    ? "O guardrail interveio neste texto."
    : "O guardrail não interveio neste texto.";
  els.result.appendChild(summary);

  const verdictEl = document.createElement("div");
  verdictEl.innerHTML = renderVerdict(data.verdict);
  els.result.appendChild(verdictEl);
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = els.textarea.value.trim();
  if (!text) return;
  clearBanners();
  els.submitBtn.disabled = true;
  try {
    const config = configPanel.getConfig();
    const data = await postJSON("/api/check", { text, stage: els.stageSelect.value, config });
    renderResult(data);
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  } finally {
    els.submitBtn.disabled = false;
  }
});

async function init() {
  renderNav(els.nav, "/check");
  try {
    configPanel = await initConfigPanel(els.configPanel, els.configToggle);
    // Re-render now that we know whether the audit screen exists on this
    // server (initConfigPanel already fetched /api/choices).
    renderNav(els.nav, "/check", { auditEnabled: configPanel.auditScreenEnabled });
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
    return;
  }
  try {
    const choices = await getJSON("/api/choices");
    els.stageSelect.innerHTML = "";
    for (const opt of choices.stages) {
      const option = document.createElement("option");
      option.value = opt.value;
      option.textContent = STAGE_COPY[opt.value] || opt.label;
      els.stageSelect.appendChild(option);
    }
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  }
}

init();
