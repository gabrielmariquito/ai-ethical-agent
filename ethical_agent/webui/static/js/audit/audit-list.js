// The record list: what the auditor picks from.
//
// Two things this screen must not do quietly. It must not make DENY and
// REWRITE look alike -- a block and an e-mail redaction differ enough in
// gravity that an auditor needs to know where to start. And it must not hide
// the cost of its own filter: the default view is narrow, so how much was
// skipped, and how far the scan got, are always on screen.

import { getJSON } from "../api.js";
import { gravityLabel, kindLabel, formatTimestamp } from "./audit-layers.js";
import { track } from "./audit-telemetry.js";

const KIND_CHIPS = [
  { key: "web_chat", label: "Conversas" },
  { key: "cli_process", label: "Linha de comando" },
  { key: "demo", label: "Demonstrações" },
  { key: "check", label: "Avaliações de texto" },
  { key: "synthetic", label: "Dados sintéticos" },
];

export function createList(listEl, footerEl, filterEl, onSelect) {
  let kinds = ["web_chat"];
  let cursor = null;
  let fileSize = null;
  let reachedStart = false;
  let rows = [];
  let selectedId = null;
  let loading = false;

  function chipsRow() {
    filterEl.innerHTML = "";
    const label = document.createElement("span");
    label.className = "ea-audit-filter__label";
    label.textContent = "Mostrar:";
    filterEl.appendChild(label);

    for (const chip of KIND_CHIPS) {
      const btn = document.createElement("button");
      btn.type = "button";
      const on = kinds === null || kinds.includes(chip.key);
      btn.className = `ea-audit-chip${on ? " ea-audit-chip--on" : ""}`;
      btn.setAttribute("aria-pressed", String(on));
      btn.textContent = chip.label;
      btn.addEventListener("click", () => {
        const current = kinds === null ? KIND_CHIPS.map((c) => c.key) : kinds.slice();
        const next = current.includes(chip.key)
          ? current.filter((k) => k !== chip.key)
          : current.concat([chip.key]);
        setKinds(next.length ? next : ["web_chat"]);
      });
      filterEl.appendChild(btn);
    }

    const all = document.createElement("button");
    all.type = "button";
    all.className = "ea-audit-chip ea-audit-chip--all";
    all.textContent = kinds === null ? "Voltar ao padrão" : "Mostrar tudo";
    all.addEventListener("click", () => setKinds(kinds === null ? ["web_chat"] : null));
    filterEl.appendChild(all);
  }

  function setKinds(next) {
    const from = kinds === null ? ["all"] : kinds.slice();
    kinds = next;
    track("filter_changed", { from_kinds: from, to_kinds: next === null ? ["all"] : next });
    reload();
  }

  function rowEl(record) {
    const item = document.createElement("button");
    item.type = "button";
    // Gravity varies three independent channels -- rail, weight and words --
    // never hue alone, so the distinction survives a colour-blind reader and
    // a greyscale screenshot.
    item.className = `ea-audit-row ea-audit-row--${record.gravity}`;
    if (record.event_id === selectedId) item.classList.add("ea-audit-row--selected");
    item.setAttribute("aria-pressed", String(record.event_id === selectedId));

    const head = document.createElement("div");
    head.className = "ea-audit-row__head";
    if (record.gravity !== "none") {
      const badge = document.createElement("span");
      badge.className = `ea-audit-badge ea-audit-badge--${record.gravity}`;
      badge.textContent = gravityLabel(record.gravity);
      head.appendChild(badge);
    }
    const when = document.createElement("span");
    when.className = "ea-audit-row__when";
    when.textContent = formatTimestamp(record.timestamp);
    head.appendChild(when);
    if (kinds === null || kinds.length > 1) {
      const kind = document.createElement("span");
      kind.className = "ea-audit-row__kind";
      kind.textContent = kindLabel(record.kind);
      head.appendChild(kind);
    }
    item.appendChild(head);

    const preview = document.createElement("div");
    preview.className = "ea-audit-row__preview";
    if (record.preview) {
      preview.textContent = record.preview;
    } else {
      preview.classList.add("ea-audit-row__preview--absent");
      preview.textContent = "(registro de saída, sem texto de entrada)";
    }
    item.appendChild(preview);

    if (record.conversation_id) {
      const meta = document.createElement("div");
      meta.className = "ea-audit-row__meta";
      meta.textContent = `conversa · turno ${record.turn_index ?? "?"}`;
      item.appendChild(meta);
    }

    item.addEventListener("click", () => {
      selectedId = record.event_id;
      for (const node of listEl.querySelectorAll(".ea-audit-row--selected")) {
        node.classList.remove("ea-audit-row--selected");
        node.setAttribute("aria-pressed", "false");
      }
      item.classList.add("ea-audit-row--selected");
      item.setAttribute("aria-pressed", "true");
      onSelect(record, "list");
    });
    return item;
  }

  function renderFooter(page) {
    footerEl.innerHTML = "";

    const scan = page.scan || {};
    if (scan.filtered_out > 0 || scan.exhausted_budget) {
      const note = document.createElement("p");
      note.className = "ea-audit-scan";
      const parts = [];
      if (scan.exhausted_budget) {
        parts.push(
          `Varri ${scan.lines_examined.toLocaleString("pt-BR")} linhas da trilha a partir daqui`
        );
      } else {
        parts.push(`Varri ${scan.lines_examined.toLocaleString("pt-BR")} linhas`);
      }
      parts.push(
        `e encontrei ${rows.length.toLocaleString("pt-BR")} registro(s) que passam no filtro atual`
      );
      if (scan.filtered_out > 0) {
        parts.push(`(${scan.filtered_out.toLocaleString("pt-BR")} ignorados pelo filtro)`);
      }
      note.textContent = `${parts.join(" ")}.`;
      footerEl.appendChild(note);
    }

    if (scan.unreadable_lines > 0) {
      const bad = document.createElement("p");
      bad.className = "ea-audit-scan ea-audit-scan--warn";
      bad.textContent = `${scan.unreadable_lines} linha(s) da trilha não puderam ser lidas e foram contadas, não ignoradas em silêncio.`;
      footerEl.appendChild(bad);
    }

    if (reachedStart) {
      const end = document.createElement("p");
      end.className = "ea-audit-scan";
      end.textContent = "Fim da trilha: não há registros anteriores a este.";
      footerEl.appendChild(end);
      return;
    }

    const more = document.createElement("button");
    more.type = "button";
    more.className = "ea-audit-more";
    more.textContent = "Continuar varrendo";
    more.addEventListener("click", () => load({ append: true }));
    footerEl.appendChild(more);

    const hint = document.createElement("p");
    hint.className = "ea-audit-scan ea-audit-scan--hint";
    hint.textContent = "Segue exatamente do ponto onde a varredura parou.";
    footerEl.appendChild(hint);
  }

  async function load({ append }) {
    if (loading) return;
    loading = true;
    try {
      const params = new URLSearchParams();
      params.set("kinds", kinds === null ? "all" : kinds.join(","));
      if (append && cursor) params.set("cursor", cursor);
      if (append && fileSize !== null) params.set("since_size", String(fileSize));
      const page = await getJSON(`/api/audit/records?${params.toString()}`);

      if (!append) {
        rows = [];
        listEl.innerHTML = "";
      }
      rows = rows.concat(page.records);
      for (const record of page.records) listEl.appendChild(rowEl(record));

      cursor = page.next_cursor;
      fileSize = page.file_size;
      reachedStart = page.reached_start_of_file;

      if (rows.length === 0) {
        const empty = document.createElement("p");
        empty.className = "ea-audit-list__empty";
        empty.textContent =
          "Nenhum registro passa no filtro atual nesta parte da trilha.";
        listEl.appendChild(empty);
      }

      renderFooter(page);
      track("list_page_loaded", {
        cursor: append && cursor ? String(cursor) : null,
        limit: 50,
        kinds: kinds === null ? ["all"] : kinds,
        returned: page.records.length,
        lines_examined: page.scan.lines_examined,
        exhausted_budget: page.scan.exhausted_budget,
        filtered_out: page.scan.filtered_out,
      });
    } catch (err) {
      if (err && err.status === 409) {
        // The trail was rewritten under us, so the byte offsets we were
        // paging with mean nothing now. Restarting silently would be worse:
        // an audit tool that papers over its subject changing is the wrong
        // tool.
        footerEl.innerHTML = "";
        const warn = document.createElement("p");
        warn.className = "ea-audit-scan ea-audit-scan--warn";
        warn.textContent =
          "A trilha mudou de tamanho desde a página anterior; recomeçando do topo para não misturar posições antigas com novas.";
        footerEl.appendChild(warn);
        cursor = null;
        fileSize = null;
        loading = false;
        await load({ append: false });
        return;
      }
      throw err;
    } finally {
      loading = false;
    }
  }

  function reload() {
    cursor = null;
    fileSize = null;
    reachedStart = false;
    chipsRow();
    return load({ append: false });
  }

  return {
    start() {
      chipsRow();
      return load({ append: false });
    },
    reload,
    selectById(eventId) {
      selectedId = eventId;
      const index = rows.findIndex((r) => r.event_id === eventId);
      if (index >= 0) {
        const nodes = listEl.querySelectorAll(".ea-audit-row");
        for (const node of nodes) {
          node.classList.remove("ea-audit-row--selected");
          node.setAttribute("aria-pressed", "false");
        }
        if (nodes[index]) {
          nodes[index].classList.add("ea-audit-row--selected");
          nodes[index].setAttribute("aria-pressed", "true");
        }
      }
    },
  };
}
