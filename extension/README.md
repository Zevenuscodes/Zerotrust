# Zero Trust browser extension (proof of concept)

Extends the continuous-authentication risk engine beyond the web app to any
site you explicitly enable, using the same backend (`/auth/*`, `/session/*`).

## How it works

- **Nothing runs until you add a site.** The extension has no blanket
  `<all_urls>` permission — adding a site in the popup triggers a real Chrome
  permission prompt scoped to that one domain (`chrome.permissions.request`).
  This mirrors the project's own least-privilege principle instead of
  contradicting it.
- Once granted, `background.js` injects `telemetry-lib.js` + `content.js`
  into that site's tabs. The content script captures the same keystroke/mouse
  features as the web app and posts a heartbeat every 12s.
- All backend calls (`/session/telemetry`, `/session/mfa/verify`) are made
  from the **background service worker**, not the content script, so they
  aren't subject to the host page's Content-Security-Policy (many sites,
  e.g. Facebook, set a strict `connect-src` that would otherwise block them).
- On `allow`: a small pill bottom-right shows the live score.
- On `stepup`: the pill expands into an OTP form (demo code `123456`).
- On `terminate`: a full-tab dimmed overlay appears. **This does not log you
  out of the actual site** (that would require manipulating the site's own
  session cookies, which most sites' Terms of Service prohibit for
  extensions) — it's a visible, honest demonstration that the Zero Trust
  layer stopped trusting the tab, not a claim that it controls the site's
  auth.

## Load it (Chrome/Edge/Brave)

1. Make sure the backend is running (`docker compose up -d` from the repo
   root) at `http://localhost:8000`.
2. Go to `chrome://extensions`, enable **Developer mode**, click
   **Load unpacked**, and select this `extension/` folder.
3. Click the extension icon → **Register** (same baseline-passphrase flow as
   the web app — it's the same account/backend).
4. Add a site to monitor (e.g. `github.com`) and accept the permission
   prompt.
5. Browse that site, type/move normally for a heartbeat or two, then type
   very differently to watch the pill go orange (step-up) or red
   (terminated/flagged).

## Why not literally "all websites"

Covered in-repo as a deliberate scope decision, not a limitation we forgot:
watching every site by default would need a blanket `<all_urls>` grant,
which is both a bad security posture for a *Zero Trust* project to ship and
against most sites' ToS to act on. Per-site opt-in keeps the demo honest and
matches the same "narrow, explicit trust" principle the backend's IAM role
and security groups already apply.
