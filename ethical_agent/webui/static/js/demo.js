import { postJSON, showErrorBanner } from "./api.js";
import { renderNav } from "./nav.js";
import { initConfigPanel } from "./config-panel.js";
import { renderIntervention, interventionKind } from "./intervention-view.js";

const els = {
  nav: document.getElementById("ea-nav"),
  configToggle: document.getElementById("ea-config-toggle"),
  configPanel: document.getElementById("ea-config-panel"),
  bannerHost: document.getElementById("ea-banner-host"),
  runBtn: document.getElementById("ea-demo-run"),
  result: document.getElementById("ea-demo-result"),
};

let configPanel = null;

function clearBanners() {
  els.bannerHost.innerHTML = "";
}

function buildCaseEl(caseData) {
  const el = document.createElement("div");
  el.className = "ea-demo-case";

  const prompt = document.createElement("p");
  prompt.className = "ea-demo-case__prompt";
  prompt.textContent = caseData.text;
  el.appendChild(prompt);

  const message = document.createElement("p");
  message.className = "ea-demo-case__message";
  message.textContent = caseData.message;
  el.appendChild(message);

  const kind = interventionKind(caseData);
  if (kind !== "none") {
    el.appendChild(renderIntervention(caseData));
  }

  return el;
}

function renderResult(data) {
  els.result.innerHTML = "";

  if (data.audit_notices && data.audit_notices.length > 0) {
    const notices = document.createElement("p");
    notices.className = "ea-tool-notices";
    notices.textContent = data.audit_notices.join(" ");
    els.result.appendChild(notices);
  }

  const list = document.createElement("div");
  list.className = "ea-demo-list";
  for (const caseData of data.cases) {
    list.appendChild(buildCaseEl(caseData));
  }
  els.result.appendChild(list);

  const note = document.createElement("p");
  note.className = "ea-demo-note";
  note.textContent = data.note;
  els.result.appendChild(note);
}

els.runBtn.addEventListener("click", async () => {
  clearBanners();
  els.runBtn.disabled = true;
  try {
    const config = configPanel.getConfig();
    const data = await postJSON("/api/demo", { config });
    renderResult(data);
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  } finally {
    els.runBtn.disabled = false;
  }
});

async function init() {
  renderNav(els.nav, "/demo");
  try {
    configPanel = await initConfigPanel(els.configPanel, els.configToggle);
    // Re-render now that we know whether the audit screen exists on this
    // server (initConfigPanel already fetched /api/choices).
    renderNav(els.nav, "/demo", { auditEnabled: configPanel.auditScreenEnabled });
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  }
}

init();
