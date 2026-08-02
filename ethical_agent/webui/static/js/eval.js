import { getJSON, postJSON, showErrorBanner } from "./api.js";
import { renderNav } from "./nav.js";
import { initConfigPanel } from "./config-panel.js";
import { createFileBrowser } from "./file-browser.js";

const els = {
  nav: document.getElementById("ea-nav"),
  configToggle: document.getElementById("ea-config-toggle"),
  configPanel: document.getElementById("ea-config-panel"),
  bannerHost: document.getElementById("ea-banner-host"),
  form: document.getElementById("ea-eval-form"),
  dataset: document.getElementById("ea-eval-dataset"),
  browseBtn: document.getElementById("ea-eval-browse"),
  submitBtn: document.getElementById("ea-eval-submit"),
  result: document.getElementById("ea-eval-result"),
};

let configPanel = null;
const fileBrowser = createFileBrowser();

function clearBanners() {
  els.bannerHost.innerHTML = "";
}

function renderResult(data) {
  els.result.innerHTML = "";

  const summary = document.createElement("p");
  summary.className = "ea-tool-summary";
  const mismatchCount = (data.mismatches || []).length;
  summary.textContent = `${data.total_cases} casos · ${mismatchCount} divergência${mismatchCount === 1 ? "" : "s"} da decisão esperada`;
  els.result.appendChild(summary);

  const report = document.createElement("pre");
  report.className = "ea-eval-report";
  report.textContent = data.report_text;
  els.result.appendChild(report);
}

els.browseBtn.addEventListener("click", async () => {
  const picked = await fileBrowser.open(els.dataset.value);
  if (picked) {
    els.dataset.value = picked;
    els.dataset.title = picked;
  }
});

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearBanners();
  els.submitBtn.disabled = true;
  els.submitBtn.textContent = "Rodando…";
  try {
    const config = configPanel.getConfig();
    const data = await postJSON("/api/eval", { dataset: els.dataset.value, config });
    renderResult(data);
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  } finally {
    els.submitBtn.disabled = false;
    els.submitBtn.textContent = "Rodar eval";
  }
});

async function init() {
  renderNav(els.nav, "/eval");
  try {
    configPanel = await initConfigPanel(els.configPanel, els.configToggle);
    // Re-render now that we know whether the audit screen exists on this
    // server (initConfigPanel already fetched /api/choices).
    renderNav(els.nav, "/eval", { auditEnabled: configPanel.auditScreenEnabled });
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
    return;
  }
  try {
    const choices = await getJSON("/api/choices");
    els.dataset.value = choices.dataset_default;
    els.dataset.title = choices.dataset_default;
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  }
}

init();
