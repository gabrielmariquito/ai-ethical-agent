// Login. A ressalva de que a senha é barreira e não segurança saiu desta tela;
// segue inteira no README e no AUDIT_GUIDE, que é onde o teste a ancora.

import { postJSON } from "../api.js";

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
