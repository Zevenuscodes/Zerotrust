// Service worker: injects the content script only into tabs on sites the user
// has explicitly enabled + granted host permission for, and relays telemetry/
// MFA calls to the backend (done here, not in content.js, so requests aren't
// subject to the host page's Content-Security-Policy).

const DEFAULT_API_BASE = "http://localhost:8000";

async function getStore(keys) {
  return chrome.storage.local.get(keys);
}

async function apiBase() {
  const { zt_api_base } = await getStore(["zt_api_base"]);
  return zt_api_base || DEFAULT_API_BASE;
}

function hostnameOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return null;
  }
}

async function isSiteEnabled(hostname) {
  if (!hostname) return false;
  const { zt_enabled_sites = [] } = await getStore(["zt_enabled_sites"]);
  return zt_enabled_sites.includes(hostname);
}

async function maybeInject(tabId, url) {
  const hostname = hostnameOf(url);
  if (!hostname || !(await isSiteEnabled(hostname))) return;

  const granted = await chrome.permissions.contains({
    origins: [`*://${hostname}/*`, `*://www.${hostname}/*`],
  });
  if (!granted) return; // user enabled the site but hasn't granted the permission prompt

  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ["telemetry-lib.js", "content.js"],
    });
  } catch {
    // tab may not be scriptable (chrome:// pages, the Web Store, etc.) -- ignore
  }
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.url) {
    maybeInject(tabId, tab.url);
  }
});

async function setBadge(tabId, score, decision) {
  if (!tabId) return;
  const color = decision === "allow" ? "#1a9850" : decision === "stepup" ? "#f39c12" : "#d73027";
  try {
    await chrome.action.setBadgeText({ tabId, text: String(Math.round(score)) });
    await chrome.action.setBadgeBackgroundColor({ tabId, color });
  } catch {
    // tab may have closed already
  }
}

const lastDecisionByTab = new Map();

async function notifyIfChanged(tabId, decision, trustScore) {
  const prev = lastDecisionByTab.get(tabId);
  lastDecisionByTab.set(tabId, decision);
  if (decision === prev) return;
  if (decision === "stepup") {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title: "Zero Trust: verification needed",
      message: `Trust score dropped to ${trustScore.toFixed(1)}. Verify in the page to keep this tab trusted.`,
    });
  } else if (decision === "terminate") {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon128.png",
      title: "Zero Trust: session flagged",
      message: `Trust score fell to ${trustScore.toFixed(1)}. This tab is no longer being trusted.`,
    });
  }
}

async function handleTelemetry(payload, tab) {
  const { zt_token } = await getStore(["zt_token"]);
  if (!zt_token) return { status: "unauthenticated" };

  const base = await apiBase();
  let res;
  try {
    res = await fetch(`${base}/session/telemetry`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${zt_token}` },
      body: JSON.stringify(payload),
    });
  } catch {
    return { status: "error", message: "Could not reach backend" };
  }

  if (res.status === 401 || res.status === 403) {
    await chrome.storage.local.remove(["zt_token", "zt_username", "zt_session_id"]);
    return { status: "unauthenticated" };
  }
  if (!res.ok) return { status: "error", message: `HTTP ${res.status}` };

  const data = await res.json();
  if (tab && tab.id) {
    setBadge(tab.id, data.trust_score, data.decision);
    notifyIfChanged(tab.id, data.decision, data.trust_score);
  }
  await chrome.storage.local.set({
    zt_last_score: data.trust_score,
    zt_last_decision: data.decision,
    zt_last_reasons: data.reasons || [],
    zt_last_site: tab && tab.url ? hostnameOf(tab.url) : null,
  });
  return { status: "ok", ...data };
}

async function handleVerifyMfa(otp) {
  const { zt_token } = await getStore(["zt_token"]);
  if (!zt_token) return { verified: false };
  const base = await apiBase();
  try {
    const res = await fetch(`${base}/session/mfa/verify`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${zt_token}` },
      body: JSON.stringify({ otp }),
    });
    if (!res.ok) return { verified: false };
    return res.json();
  } catch {
    return { verified: false };
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "zt:telemetry") {
    handleTelemetry(message.payload, sender.tab).then(sendResponse);
    return true;
  }
  if (message?.type === "zt:verify-mfa") {
    handleVerifyMfa(message.otp).then(sendResponse);
    return true;
  }
  return false;
});

chrome.runtime.onInstalled.addListener(async () => {
  const { zt_api_base, zt_enabled_sites } = await getStore(["zt_api_base", "zt_enabled_sites"]);
  const updates = {};
  if (!zt_api_base) updates.zt_api_base = DEFAULT_API_BASE;
  if (!zt_enabled_sites) updates.zt_enabled_sites = [];
  if (Object.keys(updates).length) await chrome.storage.local.set(updates);
});
