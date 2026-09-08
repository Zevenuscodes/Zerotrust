// Injected only into tabs whose site the user explicitly enabled (see background.js).
// Captures the same keystroke/mouse features the web app does, asks the
// background service worker to score them against the backend risk engine
// every 12s, and renders a small on-page indicator that reacts to the result.
(function () {
  if (window.__ztContentLoaded) return;
  window.__ztContentLoaded = true;

  const TELEMETRY_INTERVAL_MS = 12000;
  const keystrokeTracker = window.ZT.createKeystrokeTracker();
  const mouseTracker = window.ZT.createMouseTracker();
  keystrokeTracker.attach(document);
  mouseTracker.attach(document);

  // --- Shadow-DOM UI, isolated from the host page's CSS ---
  const host = document.createElement("div");
  host.id = "zt-ext-root";
  host.style.all = "initial";
  document.documentElement.appendChild(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
    <style>
      :host { all: initial; }
      * { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }
      .pill {
        position: fixed; bottom: 18px; right: 18px; z-index: 2147483000;
        display: flex; align-items: center; gap: 8px;
        background: #171a21; color: #e7e9ec; border-radius: 999px;
        padding: 8px 14px 8px 10px; box-shadow: 0 6px 20px rgba(0,0,0,.35);
        cursor: pointer; font-size: 13px; border: 1px solid rgba(255,255,255,.08);
        transition: transform .15s ease;
      }
      .pill:hover { transform: translateY(-1px); }
      .dot { width: 9px; height: 9px; border-radius: 50%; background: #1a9850; flex: none; }
      .score { font-weight: 600; font-variant-numeric: tabular-nums; }
      .label { opacity: .7; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; }
      .card {
        position: fixed; bottom: 60px; right: 18px; z-index: 2147483000;
        width: 260px; background: #171a21; color: #e7e9ec; border-radius: 14px;
        padding: 16px; box-shadow: 0 12px 32px rgba(0,0,0,.45);
        border: 1px solid rgba(255,255,255,.08); display: none;
      }
      .card.open { display: block; }
      .card h3 { margin: 0 0 6px; font-size: 14px; }
      .card p { margin: 0 0 10px; font-size: 12.5px; opacity: .8; line-height: 1.4; }
      .card input {
        width: 100%; padding: 8px 10px; border-radius: 8px; border: 1px solid #2a2f3a;
        background: #0f1115; color: #e7e9ec; font-size: 15px; letter-spacing: .15em;
        text-align: center; margin-bottom: 8px;
      }
      .card button {
        width: 100%; padding: 8px 10px; border-radius: 8px; border: none;
        background: #3b82f6; color: white; font-size: 13px; cursor: pointer;
      }
      .card .err { color: #ff6b6b; font-size: 12px; margin: 0 0 8px; }
      .overlay {
        position: fixed; inset: 0; z-index: 2147483647; display: none;
        background: rgba(8,9,12,.88); backdrop-filter: blur(3px);
        align-items: center; justify-content: center; color: #e7e9ec; text-align: center;
      }
      .overlay.open { display: flex; }
      .overlay .box { max-width: 380px; padding: 28px; }
      .overlay h2 { margin: 0 0 10px; font-size: 20px; }
      .overlay p { font-size: 13.5px; opacity: .85; line-height: 1.5; margin: 0 0 18px; }
      .overlay button {
        padding: 9px 16px; border-radius: 8px; border: none; background: #3b82f6;
        color: white; font-size: 13.5px; cursor: pointer;
      }
      .reasons { margin: 8px 0 0; padding-left: 16px; font-size: 11.5px; opacity: .75; }
    </style>
    <div class="pill" id="zt-pill">
      <span class="dot" id="zt-dot"></span>
      <span class="score" id="zt-score">--</span>
      <span class="label" id="zt-label">zero trust</span>
    </div>
    <div class="card" id="zt-card">
      <div id="zt-card-body"></div>
    </div>
    <div class="overlay" id="zt-overlay">
      <div class="box">
        <h2>Session flagged</h2>
        <p id="zt-overlay-text">Your behavior on this tab stopped matching your profile. This tab's Zero Trust monitor has paused and is no longer verifying you as trusted here.</p>
        <button id="zt-overlay-dismiss">Dismiss</button>
      </div>
    </div>
  `;

  const pillEl = root.getElementById("zt-pill");
  const dotEl = root.getElementById("zt-dot");
  const scoreEl = root.getElementById("zt-score");
  const labelEl = root.getElementById("zt-label");
  const cardEl = root.getElementById("zt-card");
  const cardBody = root.getElementById("zt-card-body");
  const overlayEl = root.getElementById("zt-overlay");

  root.getElementById("zt-overlay-dismiss").addEventListener("click", () => {
    overlayEl.classList.remove("open");
  });

  function colorFor(score) {
    if (score >= 70) return "#1a9850";
    if (score >= 40) return "#f39c12";
    return "#d73027";
  }

  function renderPill(score, decision) {
    scoreEl.textContent = Math.round(score);
    dotEl.style.background = colorFor(score);
    labelEl.textContent = decision === "allow" ? "zero trust" : decision === "stepup" ? "verify needed" : "flagged";
  }

  function renderUnauth() {
    scoreEl.textContent = "--";
    dotEl.style.background = "#6b7280";
    labelEl.textContent = "not signed in";
    cardEl.classList.remove("open");
  }

  function openStepupCard(reasons) {
    cardBody.innerHTML = `
      <h3>Step-up verification</h3>
      <p>Your typing/mouse pattern on this tab looked unusual. Enter the one-time code to keep this tab trusted. (Demo OTP: 123456)</p>
      <input id="zt-otp" maxlength="6" placeholder="6-digit code" />
      <div class="err" id="zt-otp-err" style="display:none"></div>
      <button id="zt-otp-submit">Verify</button>
    `;
    cardEl.classList.add("open");
    root.getElementById("zt-otp-submit").addEventListener("click", async () => {
      const otp = root.getElementById("zt-otp").value.trim();
      const errEl = root.getElementById("zt-otp-err");
      const resp = await chrome.runtime.sendMessage({ type: "zt:verify-mfa", otp });
      if (resp && resp.verified) {
        cardEl.classList.remove("open");
        renderPill(resp.trust_score, "allow");
      } else {
        errEl.textContent = "Incorrect code, try again.";
        errEl.style.display = "block";
      }
    });
  }

  pillEl.addEventListener("click", () => {
    if (cardEl.classList.contains("open")) {
      cardEl.classList.remove("open");
    } else if (cardBody.innerHTML) {
      cardEl.classList.add("open");
    }
  });

  async function sendTelemetry() {
    const keystroke = keystrokeTracker.snapshot();
    const mouse = mouseTracker.snapshot();
    const context = window.ZT.getContextInfo();

    let resp;
    try {
      resp = await chrome.runtime.sendMessage({
        type: "zt:telemetry",
        payload: { keystroke, mouse, context },
      });
    } catch {
      return; // extension context gone (e.g. reloaded) -- stop quietly
    }

    if (!resp || resp.status === "unauthenticated") {
      renderUnauth();
      return;
    }
    if (resp.status === "error") {
      return;
    }

    renderPill(resp.trust_score, resp.decision);

    if (resp.decision === "stepup") {
      openStepupCard(resp.reasons);
    } else if (resp.decision === "terminate") {
      cardEl.classList.remove("open");
      const reasonsHtml = (resp.reasons || [])
        .map((r) => `<li>${r}</li>`)
        .join("");
      root.getElementById("zt-overlay-text").innerHTML =
        `Your behavior on this tab stopped matching your profile (trust score ${resp.trust_score.toFixed(
          1
        )}). This tab's Zero Trust monitor has paused and is no longer verifying you as trusted here.` +
        (reasonsHtml ? `<ul class="reasons">${reasonsHtml}</ul>` : "");
      overlayEl.classList.add("open");
    } else {
      cardEl.classList.remove("open");
    }
  }

  sendTelemetry();
  const interval = setInterval(sendTelemetry, TELEMETRY_INTERVAL_MS);
  window.addEventListener("pagehide", () => clearInterval(interval));
})();
