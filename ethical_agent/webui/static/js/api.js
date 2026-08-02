// Small fetch wrappers shared by every screen. No framework, no build step --
// this is loaded as a native ES module (<script type="module">).

export class ApiError extends Error {
  constructor(status, error, message) {
    super(message);
    this.status = status;
    this.error = error;
  }
}

async function request(method, path, body) {
  const init = { method, headers: {} };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json; charset=utf-8";
    init.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch (networkErr) {
    throw new ApiError(0, "network_error", "Não foi possível falar com o servidor local. Ele ainda está rodando?");
  }
  let payload = null;
  try {
    payload = await response.json();
  } catch (_parseErr) {
    payload = null;
  }
  if (!response.ok) {
    const error = (payload && payload.error) || "unknown_error";
    const message = (payload && payload.message) || `HTTP ${response.status}`;
    throw new ApiError(response.status, error, message);
  }
  return payload;
}

export function getJSON(path) {
  return request("GET", path);
}

export function postJSON(path, body) {
  return request("POST", path, body === undefined ? {} : body);
}

// Renders a dismissible error banner into `container` (prepended). Callers
// pass the caught ApiError (or any Error) directly.
export function showErrorBanner(container, err) {
  const banner = document.createElement("div");
  banner.className = "ea-error-banner";
  banner.setAttribute("role", "alert");
  const text = document.createElement("span");
  text.textContent = err && err.message ? err.message : String(err);
  banner.appendChild(text);
  const close = document.createElement("button");
  close.type = "button";
  close.className = "ea-error-banner__close";
  close.setAttribute("aria-label", "Fechar aviso");
  close.textContent = "×";
  close.addEventListener("click", () => banner.remove());
  banner.appendChild(close);
  container.prepend(banner);
  return banner;
}
