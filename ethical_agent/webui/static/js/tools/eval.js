import { getJSON, postJSON, showErrorBanner } from "../api.js";
import { renderNav } from "../nav.js";
import { initConfigPanel } from "../config-panel.js";
import { createFileBrowser } from "../file-browser.js";

const els = {
  nav: document.getElementById("ea-nav"),
  configToggle: document.getElementById("ea-config-toggle"),
  configPanel: document.getElementById("ea-config-panel"),
  bannerHost: document.getElementById("ea-banner-host"),
  form: document.getElementById("ea-eval-form"),
  dataset: document.getElementById("ea-eval-dataset"),
  browseBtn: document.getElementById("ea-eval-browse"),
  engine: document.getElementById("ea-eval-engine"),
  half: document.getElementById("ea-eval-half"),
  papel: document.getElementById("ea-eval-papel"),
  submitBtn: document.getElementById("ea-eval-submit"),
  result: document.getElementById("ea-eval-result"),
};

let configPanel = null;
// value -> label e value -> papel, vindos de /api/choices. Nenhum valor
// canônico de engine ou de metade é literal neste arquivo: handlers_choices.py
// existe para ser a fonte única desse vocabulário, e a tela de Eval não abre
// exceção para si mesma.
let rotuloDoMotor = new Map();
let papelDaMetade = new Map();
const fileBrowser = createFileBrowser();

function clearBanners() {
  els.bannerHost.innerHTML = "";
}

function buildBox(avaliacao, datasetNome) {
  const box = document.createElement("section");
  box.className = "ea-tool-result ea-eval-box";

  // Cada caixa se nomeia inteira. Uma captura de tela de uma caixa só tem de
  // dizer de que dataset, de que engine e de que metade ela é -- antes desta
  // leva não dizia nem o dataset, e quem lia a imagem depois não sabia se era o
  // conjunto curado ou um dos externos.
  const title = document.createElement("h2");
  title.className = "ea-eval-box__title";
  const kind = avaliacao.engine_kind;
  title.textContent =
    `${datasetNome} · ${rotuloDoMotor.get(kind) || kind}` +
    ` · metade ${avaliacao.divisao.metade}`;
  box.appendChild(title);

  // O papel da metade vem do servidor e fica VISÍVEL na caixa, não em ajuda nem
  // em tooltip. Vai também dentro do report_text, então o texto copiado leva o
  // papel junto.
  if (avaliacao.papel) {
    const papel = document.createElement("p");
    papel.className = "ea-eval-box__papel";
    papel.textContent = `${avaliacao.divisao.metade} — ${avaliacao.papel}`;
    box.appendChild(papel);
  }

  const summary = document.createElement("p");
  summary.className = "ea-tool-summary";
  const mismatchCount = (avaliacao.mismatches || []).length;
  // Subtraído, não arredondado de `decision_accuracy`: um caso é acerto
  // exatamente quando não virou divergência, e as duas contagens têm de
  // fechar com o total na mesma linha em que aparecem juntas.
  const hitCount = avaliacao.total_cases - mismatchCount;
  summary.textContent =
    `${avaliacao.total_cases} casos · ${hitCount} acerto${hitCount === 1 ? "" : "s"} · ` +
    `${mismatchCount} divergência${mismatchCount === 1 ? "" : "s"} da decisão esperada`;
  box.appendChild(summary);

  const report = document.createElement("pre");
  report.className = "ea-eval-report";
  report.textContent = avaliacao.report_text;
  box.appendChild(report);

  return box;
}

function renderResult(data) {
  els.result.innerHTML = "";

  // `=== false` e não `!...`: `null` é o que a metade inteira devolve, e
  // "ninguém computou o gap" não é "as metades não são comparáveis". Mesma
  // disciplina do `undefined` em nav.js.
  const incomparavel = data.avaliacoes.some(
    (a) => a.divisao && a.divisao.acuracia_comparavel === false
  );
  if (incomparavel) {
    const nota = document.createElement("p");
    nota.className = "ea-tool-notices";
    nota.textContent =
      "As metades deste dataset têm proporções DENY/ALLOW diferentes o bastante " +
      "para que acurácia e F1 não sejam comparáveis entre elas. Compare recall — " +
      "cada caixa repete o aviso com o número medido.";
    els.result.appendChild(nota);
  }

  // Uma caixa por avaliação, para que cada uma possa ser lida, copiada ou
  // capturada isoladamente.
  for (const avaliacao of data.avaliacoes) {
    els.result.appendChild(buildBox(avaliacao, data.dataset_nome));
  }
}

function mostrarPapel() {
  els.papel.textContent = papelDaMetade.get(els.half.value) || "";
}

els.browseBtn.addEventListener("click", async () => {
  const picked = await fileBrowser.open(els.dataset.value);
  if (picked) {
    els.dataset.value = picked;
    els.dataset.title = picked;
  }
});

els.half.addEventListener("change", mostrarPapel);

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearBanners();
  els.submitBtn.disabled = true;
  els.submitBtn.textContent = "Rodando…";
  try {
    const config = configPanel.getConfig();
    // `engine` e `half` viajam no TOPO do corpo, nunca dobrados dentro de
    // `config`: `config` é o objeto do painel compartilhado que toda tela manda
    // igual, e o motor desta execução é outro fato. É essa separação que
    // impede a escolha daqui de alcançar a tela de conversa.
    const data = await postJSON("/api/eval", {
      dataset: els.dataset.value,
      engine: els.engine.value,
      half: els.half.value,
      config,
    });
    renderResult(data);
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  } finally {
    els.submitBtn.disabled = false;
    els.submitBtn.textContent = "Rodar eval";
  }
});

function popular(selectEl, opcoes) {
  selectEl.innerHTML = "";
  for (const opt of opcoes) {
    const option = document.createElement("option");
    option.value = opt.value;
    option.textContent = opt.label;
    selectEl.appendChild(option);
  }
}

async function init() {
  // sessionActive is true by construction: this page is session-gated in
  // httphandler's GATED_PAGES, so reaching this code means a session exists.
  renderNav(els.nav, "/eval", { sessionActive: true });
  try {
    configPanel = await initConfigPanel(els.configPanel, els.configToggle);
    // Re-render now that we know whether the audit screen exists on this
    // server (initConfigPanel already fetched /api/choices).
    renderNav(els.nav, "/eval", { auditEnabled: configPanel.auditScreenEnabled, sessionActive: true });
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
    return;
  }
  try {
    const choices = await getJSON("/api/choices");
    els.dataset.value = choices.dataset_default;
    els.dataset.title = choices.dataset_default;

    popular(els.engine, choices.eval_engines);
    rotuloDoMotor = new Map(choices.eval_engines.map((o) => [o.value, o.label]));
    // Semeado do painel compartilhado UMA vez, e nunca escrito de volta: este
    // <select> não tem listener que grave, e esta tela não alcança o
    // armazenamento por aba onde o painel guarda os campos dele (config-panel.js
    // é o único que escreve lá). O padrão é o motor configurado, não a
    // comparação -- o primeiro carregamento é idêntico ao de antes desta leva.
    els.engine.value = configPanel.getConfig().engine;

    popular(els.half, choices.halves);
    papelDaMetade = new Map(choices.halves.map((o) => [o.value, o.papel]));
    els.half.value = choices.halves[0].value;
    mostrarPapel();
  } catch (err) {
    showErrorBanner(els.bannerHost, err);
  }
}

init();
