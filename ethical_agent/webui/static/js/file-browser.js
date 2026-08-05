// A minimal modal directory browser for the config panel's "Procurar..."
// buttons. Needed because a plain <input type="file"> never exposes the
// absolute path of a chosen file (browsers withhold it for privacy) -- the
// server has to be the one walking the filesystem (see handlers_browse.py
// for the access restriction), this just renders what it returns.

import { getJSON } from "./api.js";

function dirnameOf(p) {
  const idx = Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\"));
  return idx >= 0 ? p.slice(0, idx) : "";
}

function joinPath(dir, name) {
  const sep = dir.includes("\\") ? "\\" : "/";
  return dir.endsWith(sep) ? dir + name : dir + sep + name;
}

let singleton = null;

export function createFileBrowser() {
  if (singleton) return singleton;

  let resolveFn = null;
  let currentDir = "";

  const overlay = document.createElement("div");
  overlay.className = "ea-filebrowser-overlay";
  overlay.hidden = true;
  overlay.innerHTML = `
    <div class="ea-filebrowser" role="dialog" aria-label="Escolher arquivo">
      <div class="ea-filebrowser__path"></div>
      <div class="ea-filebrowser__error" hidden></div>
      <div class="ea-filebrowser__list"></div>
      <div class="ea-filebrowser__footer">
        <input type="text" class="ea-filebrowser__filename" placeholder="nome do arquivo" />
        <button type="button" class="ea-filebrowser__select">Selecionar</button>
        <button type="button" class="ea-filebrowser__cancel">Cancelar</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  const pathEl = overlay.querySelector(".ea-filebrowser__path");
  const errorEl = overlay.querySelector(".ea-filebrowser__error");
  const listEl = overlay.querySelector(".ea-filebrowser__list");
  const filenameInput = overlay.querySelector(".ea-filebrowser__filename");
  const selectBtn = overlay.querySelector(".ea-filebrowser__select");
  const cancelBtn = overlay.querySelector(".ea-filebrowser__cancel");

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  async function load(dir) {
    errorEl.hidden = true;
    try {
      const data = await getJSON(`/api/browse?path=${encodeURIComponent(dir || "")}`);
      currentDir = data.path;
      pathEl.textContent = currentDir;
      listEl.innerHTML = "";

      if (data.parent) {
        const up = document.createElement("button");
        up.type = "button";
        up.className = "ea-filebrowser__item ea-filebrowser__item--up";
        up.textContent = ".. (subir um nível)";
        up.addEventListener("click", () => load(data.parent));
        listEl.appendChild(up);
      }

      for (const entry of data.entries) {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "ea-filebrowser__item" + (entry.is_dir ? " ea-filebrowser__item--dir" : "");
        item.textContent = entry.is_dir ? `${entry.name}/` : entry.name;
        item.addEventListener("click", () => {
          if (entry.is_dir) {
            load(joinPath(currentDir, entry.name));
          } else {
            filenameInput.value = entry.name;
          }
        });
        listEl.appendChild(item);
      }
    } catch (err) {
      showError(err.message || String(err));
    }
  }

  // The pending resolve has to be read *before* close() clears it, or the
  // promise `open()` returned never settles and the caller's `await` hangs
  // forever -- the field keeps its old path and the screen looks inert.
  function settle(value) {
    const resolve = resolveFn;
    close();
    if (resolve) resolve(value);
  }

  selectBtn.addEventListener("click", () => {
    const name = filenameInput.value.trim();
    settle(name ? joinPath(currentDir, name) : currentDir);
  });
  cancelBtn.addEventListener("click", () => {
    settle(null);
  });
  filenameInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      selectBtn.click();
    }
  });

  function close() {
    overlay.hidden = true;
    resolveFn = null;
  }

  singleton = {
    open(initialPath) {
      overlay.hidden = false;
      filenameInput.value = initialPath ? initialPath.split(/[/\\]/).pop() : "";
      load(initialPath ? dirnameOf(initialPath) : "");
      return new Promise((resolve) => {
        resolveFn = resolve;
      });
    },
  };
  return singleton;
}
