const BASELINE_PASSPHRASE = "the quick zero trust fox verifies every packet";
const app = document.getElementById("app");

let authTab = "login"; // "login" | "register"


async function store(keys) {
  return chrome.storage.local.get(keys);
}
async function setStore(obj) {
  return chrome.storage.local.set(obj);
}

async function apiBase() {
  const { zt_api_base } = await store(["zt_api_base"]);
  return zt_api_base || "http://localhost:8000";
}

async function apiRequest(path, { method = "GET", body, auth = false } = {}) {
  const base = await apiBase();
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const { zt_token } = await store(["zt_token"]);
    if (zt_token) headers.Authorization = `Bearer ${zt_token}`;
  }
  const res = await fetch(`${base}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function colorFor(score) {
  if (score >= 70) return "#1a9850";
  if (score >= 40) return "#f39c12";
  return "#d73027";
}

async function render() {
  const { zt_token, zt_username } = await store(["zt_token", "zt_username"]);
  if (zt_token) {
    await renderDashboard(zt_username);
  } else {
    renderAuth();
  }
}

function renderAuth() {
  app.innerHTML = `
    <div class="brand"><span class="dot"></span><h1>Zero Trust Continuous Auth</h1></div>
    <div class="tabs">
      <button id="tab-login" class="${authTab === "login" ? "active" : ""}">Log in</button>
      <button id="tab-register" class="${authTab === "register" ? "active" : ""}">Register</button>
    </div>
    <div id="auth-form"></div>
  `;
  document.getElementById("tab-login").onclick = () => { authTab = "login"; renderAuth(); };
  document.getElementById("tab-register").onclick = () => { authTab = "register"; renderAuth(); };
  authTab === "login" ? renderLoginForm() : renderRegisterForm();
}

function renderLoginForm() {
  const el = document.getElementById("auth-form");
  el.innerHTML = `
    <form id="login-form">
      <label>Username <input id="login-username" required /></label>
      <label>Password <input id="login-password" type="password" required /></label>
      <p class="error" id="login-error" style="display:none"></p>
      <button class="primary" type="submit" id="login-submit">Log in</button>
    </form>
  `;
  const passwordInput = document.getElementById("login-password");

  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("login-username").value;
    const password = document.getElementById("login-password").value;
    const errEl = document.getElementById("login-error");
    const submitBtn = document.getElementById("login-submit");
    errEl.style.display = "none";
    submitBtn.disabled = true;
    submitBtn.textContent = "Logging in...";
    try {
      const resp = await apiRequest("/auth/login", {
        method: "POST",
        body: { username, password, environment: window.ZT.getEnvironment() },
      });
      await setStore({ zt_token: resp.access_token, zt_username: username, zt_session_id: resp.session_id });
      render();
    } catch (err) {
      errEl.textContent = err.message || "Login failed";
      errEl.style.display = "block";
      submitBtn.disabled = false;
      submitBtn.textContent = "Log in";
    }
  });
}

function renderRegisterForm() {
  const el = document.getElementById("auth-form");
  el.innerHTML = `
    <p class="muted">This baseline sample trains your personal behavior profile. It's the same account/backend the web app uses.</p>
    <form id="register-form">
      <label>Username <input id="reg-username" required /></label>
      <label>Password <input id="reg-password" type="password" required /></label>
      <label>
        Type this passphrase exactly:
        <code class="passphrase">${BASELINE_PASSPHRASE}</code>
        <input id="reg-passphrase" required />
      </label>
      <p class="error" id="reg-error" style="display:none"></p>
      <button class="primary" type="submit" id="reg-submit">Register</button>
    </form>
  `;
  const passphraseInput = document.getElementById("reg-passphrase");

  document.getElementById("register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const username = document.getElementById("reg-username").value;
    const password = document.getElementById("reg-password").value;
    const typed = document.getElementById("reg-passphrase").value.trim();
    const errEl = document.getElementById("reg-error");
    const submitBtn = document.getElementById("reg-submit");
    errEl.style.display = "none";

    if (typed !== BASELINE_PASSPHRASE) {
      errEl.textContent = "Please type the baseline passphrase exactly as shown.";
      errEl.style.display = "block";
      return;
    }

    submitBtn.disabled = true;
    submitBtn.textContent = "Registering...";
    try {
      const resp = await apiRequest("/auth/register", {
        method: "POST",
        body: { username, password, environment: window.ZT.getEnvironment() },
      });
      await setStore({ zt_token: resp.access_token, zt_username: username, zt_session_id: resp.session_id });
      render();
    } catch (err) {
      errEl.textContent = err.message || "Registration failed";
      errEl.style.display = "block";
      submitBtn.disabled = false;
      submitBtn.textContent = "Register";
    }
  });
}

function normalizeHostname(input) {
  let v = input.trim().toLowerCase();
  v = v.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
  return v;
}

async function renderDashboard(username) {
  const {
    zt_enabled_sites = [],
    zt_last_score,
    zt_last_decision,
    zt_last_site,
    zt_last_reasons = [],
    zt_api_base,
  } = await store([
    "zt_enabled_sites",
    "zt_last_score",
    "zt_last_decision",
    "zt_last_site",
    "zt_last_reasons",
    "zt_api_base",
  ]);

  const hasScore = typeof zt_last_score === "number";
  const score = hasScore ? zt_last_score : 100;
  const decision = zt_last_decision || "allow";

  app.innerHTML = `
    <div class="header-row">
      <span class="who">${username}</span>
      <button id="logout-btn">Log out</button>
    </div>

    <div class="score-card">
      <div class="score-row">
        <span class="score-num" style="color:${colorFor(score)}">${hasScore ? score.toFixed(1) : "--"}</span>
        <span class="score-decision" style="background:${colorFor(score)}22;color:${colorFor(score)}">${decision}</span>
      </div>
      <div class="score-bar-track">
        <div class="score-bar-fill" style="width:${score}%;background:${colorFor(score)}"></div>
      </div>
      ${zt_last_site ? `<div class="score-site">Last measured on ${zt_last_site}</div>` : `<div class="score-site">No telemetry yet -- browse a monitored site.</div>`}
      ${zt_last_reasons.length ? `<ul class="score-reasons">${zt_last_reasons.map((r) => `<li>${r}</li>`).join("")}</ul>` : ""}
    </div>

    <div class="sites-section">
      <h2>Monitored sites</h2>
      <div id="site-list">
        ${
          zt_enabled_sites.length
            ? zt_enabled_sites.map((s) => `
              <div class="site-row">
                <span>${s}</span>
                <button data-site="${s}" class="remove-site">Remove</button>
              </div>`).join("")
            : `<div class="empty-note">No sites yet -- add one below to start monitoring behavior there.</div>`
        }
      </div>
      <div class="add-site-row">
        <input id="add-site-input" placeholder="e.g. facebook.com" />
        <button id="add-site-btn">Add + Grant</button>
      </div>
      <p class="error" id="site-error" style="display:none"></p>
    </div>

    <div class="settings-row">
      <label>Backend URL <input id="api-base-input" value="${zt_api_base || "http://localhost:8000"}" /></label>
    </div>
  `;

  document.getElementById("logout-btn").addEventListener("click", async () => {
    try {
      await apiRequest("/session/logout", { method: "POST", auth: true });
    } catch {
      /* best-effort */
    }
    await chrome.storage.local.remove(["zt_token", "zt_username", "zt_session_id"]);
    render();
  });

  document.querySelectorAll(".remove-site").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const site = btn.dataset.site;
      await chrome.permissions.remove({ origins: [`*://${site}/*`, `*://www.${site}/*`] });
      const { zt_enabled_sites: sites = [] } = await store(["zt_enabled_sites"]);
      await setStore({ zt_enabled_sites: sites.filter((s) => s !== site) });
      renderDashboard(username);
    });
  });

  document.getElementById("add-site-btn").addEventListener("click", async () => {
    const input = document.getElementById("add-site-input");
    const errEl = document.getElementById("site-error");
    errEl.style.display = "none";
    const hostname = normalizeHostname(input.value);
    if (!hostname || !hostname.includes(".")) {
      errEl.textContent = "Enter a valid domain, e.g. facebook.com";
      errEl.style.display = "block";
      return;
    }
    try {
      const granted = await chrome.permissions.request({
        origins: [`*://${hostname}/*`, `*://www.${hostname}/*`],
      });
      if (!granted) {
        errEl.textContent = "Permission denied -- this site won't be monitored.";
        errEl.style.display = "block";
        return;
      }
      const { zt_enabled_sites: sites = [] } = await store(["zt_enabled_sites"]);
      if (!sites.includes(hostname)) {
        await setStore({ zt_enabled_sites: [...sites, hostname] });
      }
      renderDashboard(username);
    } catch (err) {
      errEl.textContent = err.message || "Could not request permission";
      errEl.style.display = "block";
    }
  });

  document.getElementById("api-base-input").addEventListener("change", async (e) => {
    await setStore({ zt_api_base: e.target.value.trim() });
  });
}

render();
