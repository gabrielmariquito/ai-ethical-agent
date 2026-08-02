// The collapsed "Engine settings" panel shared by every screen. Starts
// closed on every page load (never persisted as "open" -- only the field
// values are remembered, and only for the tab's session via sessionStorage,
// never written to a file). Values are seeded from GET /api/choices'
// `defaults` (which mirrors whatever `ethical-agent serve` was started
// with) the first time there's nothing in sessionStorage yet.

import { getJSON } from "./api.js";
import { createFileBrowser } from "./file-browser.js";

const STORAGE_KEY = "ea.config.v1";

const FIELDS = [
  { key: "policy", label: "Policy", type: "text", browse: true },
  { key: "ontology", label: "Ontology", type: "text", browse: true },
  { key: "grounding", label: "Grounding", type: "text", browse: true },
  { key: "norms", label: "Norms", type: "text", browse: true },
  { key: "engine", label: "Engine", type: "select" },
  { key: "audit_log", label: "Audit log", type: "text", browse: true },
  { key: "model", label: "Model", type: "text" },
  { key: "mock", label: "Mock (não chama nenhum modelo)", type: "checkbox" },
];

function loadStoredConfig() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (_err) {
    return null;
  }
}

function saveStoredConfig(config) {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(config));
  } catch (_err) {
    // sessionStorage unavailable (private mode, quota) -- config just won't
    // survive a reload; not fatal, every request still carries it explicitly.
  }
}

export async function initConfigPanel(panelEl, toggleBtn) {
  const choices = await getJSON("/api/choices");
  const stored = loadStoredConfig();
  const config = Object.assign({}, choices.defaults, stored || {});
  const fileBrowser = createFileBrowser();

  panelEl.innerHTML = "";
  panelEl.classList.add("ea-config-panel");
  panelEl.hidden = true;

  const inputs = {};
  for (const field of FIELDS) {
    const row = document.createElement("div");
    row.className = "ea-config-panel__row";
    if (field.type === "checkbox") row.classList.add("ea-config-panel__row--checkbox");

    const fieldId = `ea-config-${field.key}`;
    const label = document.createElement("label");
    label.setAttribute("for", fieldId);
    label.textContent = field.label;
    row.appendChild(label);

    let input;
    if (field.type === "select") {
      input = document.createElement("select");
      for (const opt of choices.engines) {
        const optionEl = document.createElement("option");
        optionEl.value = opt.value;
        optionEl.textContent = opt.label;
        input.appendChild(optionEl);
      }
      input.value = config.engine;
    } else if (field.type === "checkbox") {
      input = document.createElement("input");
      input.type = "checkbox";
      input.checked = Boolean(config[field.key]);
    } else {
      // Plain, explicitly editable text input -- paths can be long, so it
      // also gets a `title` (full value on hover) since even a full-width
      // input can still be narrower than a long Windows path.
      input = document.createElement("input");
      input.type = "text";
      input.value = config[field.key] || "";
      input.title = input.value;
      input.spellcheck = false;
      input.autocomplete = "off";
    }
    input.id = fieldId;
    input.addEventListener("input", () => {
      config[field.key] = field.type === "checkbox" ? input.checked : input.value;
      if (field.type === "text") input.title = input.value;
      saveStoredConfig(config);
    });
    inputs[field.key] = input;

    if (field.type === "text" && field.browse) {
      const inputRow = document.createElement("div");
      inputRow.className = "ea-config-panel__input-row";
      inputRow.appendChild(input);

      const browseBtn = document.createElement("button");
      browseBtn.type = "button";
      browseBtn.className = "ea-config-panel__browse";
      browseBtn.textContent = "Procurar…";
      browseBtn.addEventListener("click", async () => {
        // The browser can't tell us the absolute path of a file picked via
        // <input type="file"> (withheld for privacy) -- the server walks
        // the filesystem instead (handlers_browse.py) and this just shows
        // what it returns.
        const picked = await fileBrowser.open(input.value);
        if (picked) {
          input.value = picked;
          input.title = picked;
          config[field.key] = picked;
          saveStoredConfig(config);
        }
      });
      inputRow.appendChild(browseBtn);
      row.appendChild(inputRow);
    } else {
      row.appendChild(input);
    }
    panelEl.appendChild(row);
  }

  toggleBtn.setAttribute("aria-expanded", "false");
  toggleBtn.addEventListener("click", () => {
    panelEl.hidden = !panelEl.hidden;
    toggleBtn.setAttribute("aria-expanded", String(!panelEl.hidden));
  });

  return {
    getConfig() {
      return Object.assign({}, config);
    },
  };
}
