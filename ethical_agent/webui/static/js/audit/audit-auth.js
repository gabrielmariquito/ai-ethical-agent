// Login, e a descrição honesta do que a senha é: a ressalva longa mora aqui
// como uma string só, idêntica à do README e do AUDIT_GUIDE.

import { postJSON } from "../api.js";

export const SECURITY_CAVEAT = [
  "Esta é uma barreira, não segurança.",
  "A senha da tela de auditoria existe para separar dois papéis — quem conversa " +
    "com o agente e quem audita as decisões — não para resistir a um atacante.",
  "O servidor roda em 127.0.0.1, sem HTTPS e sem infraestrutura de autenticação: " +
    "a senha e o código de sessão trafegam em texto claro pelo loopback, o código " +
    "de sessão vive apenas na memória do processo, e qualquer pessoa com acesso a " +
    "este computador pode ler logs/audit.jsonl diretamente, sem passar por esta tela.",
  "O cookie é HttpOnly, o que impede o JavaScript da página de lê-lo; não impede " +
    "que alguém sentado nesta máquina o veja nas ferramentas do navegador.",
  "O que a senha garante é que a trilha não abre por acidente, por curiosidade, ou " +
    "porque alguém digitou /audit na barra de endereços — que, num estudo com papéis " +
    "separados, é exatamente o que precisa valer.",
  "Não trate isto como controle de acesso a dado sensível.",
];

export function renderCaveat(hostEl) {
  hostEl.innerHTML = "";
  for (const paragraph of SECURITY_CAVEAT) {
    const p = document.createElement("p");
    p.textContent = paragraph;
    hostEl.appendChild(p);
  }
}

export function createLogin(els, onSuccess) {
  let lockoutTimer = null;

  function showError(message) {
    els.error.hidden = false;
    els.error.textContent = message;
  }

  function startLockoutCountdown(seconds) {
    if (lockoutTimer) clearInterval(lockoutTimer);
    let remaining = seconds;
    els.submit.disabled = true;
    const tick = () => {
      if (remaining <= 0) {
        clearInterval(lockoutTimer);
        lockoutTimer = null;
        els.submit.disabled = false;
        els.error.hidden = true;
        return;
      }
      showError(`Muitas tentativas. Tente novamente em ${remaining}s.`);
      remaining -= 1;
    };
    tick();
    lockoutTimer = setInterval(tick, 1000);
  }

  els.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    els.error.hidden = true;
    els.submit.disabled = true;
    try {
      const session = await postJSON("/api/audit/login", { password: els.password.value });
      els.password.value = "";
      onSuccess(session);
    } catch (err) {
      if (err.status === 429) {
        const match = /(\d+)s/.exec(err.message || "");
        startLockoutCountdown(match ? Number(match[1]) : 60);
        return;
      }
      showError(err.message || "Não foi possível entrar.");
      els.submit.disabled = false;
      els.password.focus();
      els.password.select();
    }
  });
}
