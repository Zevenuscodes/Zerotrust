"""End-to-end checks against a running instance (default http://localhost:8001).

Run before a demo to confirm the whole stack actually behaves:
    python backend/tests/test_e2e.py

Exits non-zero if any check fails. These hit the real API over HTTP rather
than importing the app, so they cover routing, auth, the DB and the risk
engine together -- which is where every bug in this project has lived.
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("ZT_BASE", "http://localhost:8001")

_passed, _failed = 0, []


def check(name, condition, detail=""):
    global _passed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed.append(name)
        print(f"  FAIL  {name}  {detail}")


def req(path, payload=None, token=None, method=None):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, method=method or ("POST" if data else "GET"))
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body}


def env(**overrides):
    """A consistent machine. Overriding any field simulates the session
    being presented from a different one."""
    base = {
        "device_fingerprint": "e2e-device", "canvas_hash": "canvas-aaa", "webgl_hash": "gpu-aaa",
        "user_agent": "Mozilla/5.0 (Macintosh) Chrome/120", "platform": "MacIntel",
        "screen_width": 1920, "screen_height": 1080, "color_depth": 24,
        "hardware_concurrency": 8, "device_memory": 16, "timezone": "Asia/Kolkata",
        "timezone_offset_min": 330, "languages": "en-US,en",
        "client_time_ms": time.time() * 1000,
    }
    base.update(overrides)
    return base


def human(**overrides):
    """Interaction that looks human: irregular gaps, plausible reaction time."""
    base = {
        "action_count": 25, "interval_cv": 0.65, "mean_interval_ms": 800,
        "time_to_first_action_ms": 1400, "clicks_without_precursor": 0,
        "pastes_into_sensitive": 0, "saw_pointer_movement": True, "headless_hints": [],
    }
    base.update(overrides)
    return base


def new_user(name, environment=None):
    uname = f"{name}_{int(time.time() * 1000) % 10_000_000}_{random.randint(0, 999)}"
    status, body = req("/auth/register", {
        "username": uname, "password": "P!123456", "environment": environment or env(),
    })
    return uname, body.get("access_token"), status


def beat(token, operation="view", environment=None, automation=None, location=None):
    payload = {
        "environment": environment or env(),
        "automation": automation or human(),
        "operation": operation,
    }
    if location:
        payload["simulated_location"] = location
    return req("/session/telemetry", payload, token)


print(f"\nZero Trust end-to-end checks against {BASE}\n")

# --- health / routing ------------------------------------------------------
print("health & routing")
s, _ = req("/health")
check("/health returns 200", s == 200, f"got {s}")
try:
    with urllib.request.urlopen(f"{BASE}/dashboard", timeout=20) as r:
        spa = r.status
except Exception as e:
    spa = str(e)
check("SPA deep link /dashboard serves the app", spa == 200, f"got {spa}")

# --- auth ------------------------------------------------------------------
print("\nauth")
uname, token, s = new_user("auth")
check("register returns a token", bool(token), f"status {s}")
s, _ = req("/auth/register", {"username": uname, "password": "P!123456", "environment": env()})
check("duplicate username rejected", s == 400, f"got {s}")
s, _ = req("/auth/login", {"username": uname, "password": "wrong", "environment": env()})
check("wrong password rejected", s == 401, f"got {s}")
s, b = req("/auth/login", {"username": uname, "password": "P!123456", "environment": env()})
check("correct password accepted", s == 200 and bool(b.get("access_token")), f"got {s}")
s, _ = req("/session/telemetry", {"environment": env(), "automation": human()}, token="garbage")
check("invalid token rejected", s == 401, f"got {s}")
s, _ = req("/session/telemetry", {"environment": env(), "automation": human()})
check("missing token rejected", s == 401, f"got {s}")

# --- telemetry basics ------------------------------------------------------
print("\ntelemetry & trust vector")
_, token, _ = new_user("tele")
s, b = beat(token, "view")
check("telemetry accepted", s == 200, f"got {s}")
check("returns a trust vector of 3 components", len(b.get("trust_vector", [])) == 3)
check("returns all 4 signal families", len(b.get("family_scores", [])) == 4,
      f"got {[f['name'] for f in b.get('family_scores', [])]}")
check("families carry per-operation weights",
      all("weight" in f for f in b.get("family_scores", [])))
check("returns individual checks", len(b.get("context_checks", [])) >= 5)
vec = {v["operation"]: v for v in b.get("trust_vector", [])}
check("thresholds are per-operation (admin stricter than view)",
      vec["admin"]["allow_threshold"] > vec["view"]["allow_threshold"])
check("clean session scores well", b["trust_score"] >= 90, f"{b['trust_score']}")
check("clean session is allowed", b["decision"] == "allow", b["decision"])

# --- per-operation weighting -----------------------------------------------
print("\nper-operation signal weighting")
_, ta, _ = new_user("wt_a")
wa = {f["name"]: f["weight"] for f in beat(ta, "admin")[1]["family_scores"]}
_, tv, _ = new_user("wt_v")
wv = {f["name"]: f["weight"] for f in beat(tv, "view")[1]["family_scores"]}
check("admin weights session integrity above view", wa["integrity"] > wv["integrity"],
      f"admin {wa['integrity']} vs view {wv['integrity']}")
check("view weights learned habits above admin", wv["patterns"] > wa["patterns"],
      f"view {wv['patterns']} vs admin {wa['patterns']}")
check("each operation's weights sum to 1", abs(sum(wa.values()) - 1.0) < 0.001, f"{sum(wa.values())}")

# --- idle ------------------------------------------------------------------
print("\nidle intervals (no interaction = no evidence)")
_, token, _ = new_user("idle")
before = beat(token, "view")[1]["trust_score"]
s, b = beat(token, "view", automation=human(action_count=0))
check("idle interval accepted", s == 200, f"got {s}")
check("idle flagged as idle", b.get("idle") is True)
check("idle leaves trust unchanged", abs(b["trust_score"] - before) < 0.01,
      f"{before} -> {b['trust_score']}")
s2, _ = beat(token, "view", automation=human(action_count=0))
check("repeated idle does not terminate the session", s2 == 200, f"got {s2}")

# --- session integrity: the headline signal --------------------------------
print("\nsession integrity (machine changed under a live session)")
_, token, _ = new_user("integ")
beat(token, "view")
b = beat(token, "admin", environment=env(hardware_concurrency=4))[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("changed CPU core count is detected", fam["integrity"] < 70, f"{fam['integrity']}")
check("it is reported as a reason", any("mid-session" in r for r in b["reasons"]), b["reasons"])

_, token, _ = new_user("integ2")
beat(token, "view")
b = beat(token, "admin", environment=env(webgl_hash="gpu-different"))[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("changed GPU renderer is detected", fam["integrity"] < 70, f"{fam['integrity']}")

_, token, _ = new_user("integ3")
beat(token, "view")
b = beat(token, "admin", environment=env(screen_width=1280, screen_height=720))[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("changed screen size is detected", fam["integrity"] < 80, f"{fam['integrity']}")

_, token, _ = new_user("integ4")
beat(token, "view")
b = beat(token, "admin")[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("an unchanged machine scores full integrity", fam["integrity"] == 100.0, f"{fam['integrity']}")

# --- automation detection --------------------------------------------------
print("\nautomation detection")
_, token, _ = new_user("auto1")
b = beat(token, "view", automation=human(headless_hints=["webdriver"]))[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("navigator.webdriver is detected", fam["automation"] < 50, f"{fam['automation']}")

_, token, _ = new_user("auto2")
b = beat(token, "view", automation=human(interval_cv=0.02))[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("metronomic action timing is detected", fam["automation"] < 60, f"{fam['automation']}")

_, token, _ = new_user("auto3")
b = beat(token, "view", automation=human(time_to_first_action_ms=20))[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("superhuman reaction time is detected", fam["automation"] < 80, f"{fam['automation']}")

_, token, _ = new_user("auto4")
b = beat(token, "view", automation=human(clicks_without_precursor=3))[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("clicks with no pointer movement are detected", fam["automation"] < 80, f"{fam['automation']}")

_, token, _ = new_user("auto5")
b = beat(token, "view")[1]
fam = {f["name"]: f["score"] for f in b["family_scores"]}
check("genuine human interaction scores full", fam["automation"] == 100.0, f"{fam['automation']}")

# --- impossible conditions -------------------------------------------------
print("\nimpossible conditions")
_, token, _ = new_user("travel")
beat(token, "view", location="mumbai")
b = beat(token, "admin", location="new_york")[1]
loc = next((c for c in b["context_checks"] if c["name"] == "Travel plausibility"), {})
check("impossible travel is detected", "Impossible travel" in loc.get("detail", ""), loc.get("detail"))

_, token, _ = new_user("skew")
b = beat(token, "view", environment=env(client_time_ms=(time.time() - 3600) * 1000))[1]
clock = next((c for c in b["context_checks"] if c["name"] == "Clock agreement"), {})
check("client clock skew is detected", clock.get("score", 100) < 100, clock.get("detail"))

_, token, _ = new_user("conc")
beat(token, "view", location="mumbai")
b = beat(token, "view", location="london")[1]
conc = next((c for c in b["context_checks"] if c["name"] == "Concurrent networks"), {})
check("same session from two networks is detected", conc.get("score", 100) < 100, conc.get("detail"))

# --- operation independence ------------------------------------------------
print("\noperation independence")
_, token, _ = new_user("vec")
beat(token, "view")
b = beat(token, "admin", environment=env(hardware_concurrency=2),
         automation=human(headless_hints=["webdriver"]))[1]
v = {x["operation"]: x["trust_score"] for x in b["trust_vector"]}
check("an anomaly on admin does not move view", v["view"] > 90, f"view={v['view']}")
check("an anomaly on admin does not move edit", v["edit"] == 100.0, f"edit={v['edit']}")
check("an anomaly on admin lowers admin", v["admin"] < v["view"], f"admin={v['admin']}")

# --- responsiveness --------------------------------------------------------
print("\ntrust responsiveness")
_, token, _ = new_user("resp")
start = beat(token, "view")[1]["trust_score"]
for _ in range(5):
    bad = beat(token, "view", environment=env(platform="Win32", webgl_hash="gpu-x"),
               automation=human(headless_hints=["webdriver", "no_plugins"]))[1]
check("sustained anomaly drives trust down", bad["trust_score"] < start - 20,
      f"{start:.1f} -> {bad['trust_score']:.1f}")
check("sustained anomaly leaves 'allow'", bad["decision"] != "allow", bad["decision"])
low = bad["trust_score"]
for _ in range(4):
    good = beat(token, "view")[1]
check("trust recovers once signals are clean", good["trust_score"] > low + 5,
      f"{low:.1f} -> {good['trust_score']:.1f}")

# --- other endpoints -------------------------------------------------------
print("\nother endpoints")
_, token, _ = new_user("misc")
beat(token, "view")
s, b = req("/session/status", token=token)
check("/session/status returns 200", s == 200, f"got {s}")
check("/session/status includes the trust vector", len(b.get("trust_vector", [])) == 3)
s, b = req("/session/calibration", token=token)
check("/session/calibration reachable", s == 200, f"got {s}")
check("/session/calibration covers every operation",
      isinstance(b, dict) and {"view", "edit", "admin"} <= set(b.keys()), f"{list(b)[:5]}")
s, _ = req("/session/mfa/verify", {"otp": "123456"}, token=token)
check("MFA verify rejected when nothing is pending", s == 400, f"got {s}")
s, _ = req("/session/logout", {}, token=token)
check("logout returns 200", s == 200, f"got {s}")
s, _ = beat(token, "view")
check("token unusable after logout", s == 401, f"got {s}")

# --- fixed-phrase step-up --------------------------------------------------
print("\nfixed-phrase biometric step-up")
PHRASE = "the quick zero trust fox verifies every packet"


def phrase_sample(dwell=95.0, flight=150.0, seed=0):
    rnd = random.Random(seed)
    sig = [rnd.uniform(0.8, 1.2) for _ in PHRASE]
    jitter = random.Random(seed * 977 + 1)
    return {
        "phrase": PHRASE,
        "dwell_ms": [round(dwell * s * jitter.uniform(0.92, 1.08), 1) for s in sig],
        "flight_ms": [None] + [round(flight * s * jitter.uniform(0.92, 1.08), 1) for s in sig[1:]],
    }


uname = f"phrase_{int(time.time() * 1000) % 10_000_000}"
s, body = req("/auth/register", {
    "username": uname, "password": "P!123456", "environment": env(device_fingerprint="phrase-dev"),
    "phrase_enrollments": [phrase_sample(seed=1) for _ in range(4)],
})
check("register accepts phrase enrollments", s == 200 and bool(body.get("access_token")), f"got {s}")
ptoken = body.get("access_token")
penv = env(device_fingerprint="phrase-dev")

s, _ = req("/session/phrase/verify", {"timings": phrase_sample(seed=1)}, ptoken)
check("phrase verify rejected when no challenge pending", s == 400, f"got {s}")

beat(ptoken, "admin", environment=penv)
pending = False
for _ in range(6):
    # A mid-severity anomaly: enough to fall out of "allow" on admin
    # (threshold 75) without collapsing past "stepup" (55).
    s, b = beat(ptoken, "admin",
                environment=env(device_fingerprint="phrase-dev", screen_width=1280),
                automation=human())
    if s == 200 and b.get("mfa_pending"):
        pending = True
        break
    if s != 200 or b.get("decision") == "terminate":
        break
check("anomaly raises a step-up challenge", pending,
      f"decision {b.get('decision')} at {b.get('trust_score')}")

if pending:
    s, b = req("/session/phrase/verify", {"timings": phrase_sample(dwell=160, flight=300, seed=42)}, ptoken)
    check("impostor rhythm is rejected", s == 200 and b.get("verified") is False,
          f"status {s} score {b.get('phrase_score')}")
    s, b = req("/session/phrase/verify", {"timings": phrase_sample(seed=1)}, ptoken)
    check("genuine rhythm is accepted", s == 200 and b.get("verified") is True,
          f"status {s} score {b.get('phrase_score')}")
    check("accepting restores trust for that operation", (b.get("trust_score") or 0) >= 70,
          f"{b.get('trust_score')}")
    s, _ = req("/session/phrase/verify", {"timings": phrase_sample(seed=1)}, ptoken)
    check("challenge is consumed after success", s == 400, f"got {s}")

# --- mid-session revocation ------------------------------------------------
print("\nmid-session revocation")
_, token, _ = new_user("term")
killed = False
for _ in range(10):
    s, b = beat(token, "admin",
                environment=env(hardware_concurrency=1, webgl_hash="gpu-z", platform="Linux x86_64"),
                automation=human(headless_hints=["webdriver", "headless_ua", "no_plugins"],
                                 interval_cv=0.01, time_to_first_action_ms=5))
    if s == 403 or (s == 200 and b.get("decision") == "terminate"):
        killed = True
        break
check("a hijacked-looking session is terminated", killed)
if killed:
    s, _ = beat(token, "view")
    check("unexpired JWT rejected after termination", s == 403, f"got {s}")

# --- summary ---------------------------------------------------------------
total = _passed + len(_failed)
print(f"\n{'=' * 52}")
print(f"{_passed}/{total} checks passed")
if _failed:
    print("\nFAILED:")
    for f in _failed:
        print(f"  - {f}")
    sys.exit(1)
print("all green")
