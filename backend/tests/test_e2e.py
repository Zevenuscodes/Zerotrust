"""End-to-end checks against a running instance (default http://localhost:8000).

Run before a demo to confirm the whole stack actually behaves:
    python backend/tests/test_e2e.py

Exits non-zero if any check fails. These hit the real API over HTTP rather
than importing the app, so they cover routing, auth, the DB and the risk
engine together -- which is where every bug in this project has actually
lived.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("ZT_BASE", "http://localhost:8000")

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
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(url, data=data, method=method or ("POST" if data else "GET"))
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


def ctx(fp="e2e-device"):
    return {"device_fingerprint": fp, "screen_width": 1920, "screen_height": 1080, "timezone": "Asia/Kolkata"}


def ks(dwell=90.0, flight=110.0, count=20):
    return {"key_count": count, "mean_dwell_ms": dwell, "std_dwell_ms": 15.0,
            "mean_flight_ms": flight, "std_flight_ms": 20.0}


def ms(vel=0.8, points=50):
    return {"point_count": points, "mean_velocity": vel, "std_velocity": 0.2,
            "mean_acceleration": 0.01, "direction_changes": 6}


def new_user(name, fp="e2e-device"):
    uname = f"{name}_{int(time.time() * 1000) % 10_000_000}"
    status, body = req("/auth/register", {"username": uname, "password": "P!123456",
                                          "keystroke": ks(), "mouse": ms(), "context": ctx(fp)})
    return uname, body.get("access_token"), status


def beat(token, operation="view", keystroke=None, mouse=None, fp="e2e-device", location=None):
    payload = {"keystroke": keystroke or ks(), "mouse": mouse or ms(),
               "context": ctx(fp), "operation": operation}
    if location:
        payload["simulated_location"] = location
    return req("/session/telemetry", payload, token)


print(f"\nZero Trust end-to-end checks against {BASE}\n")

# --- health / static -------------------------------------------------------
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
s, body = req("/auth/register", {"username": uname, "password": "P!123456",
                                 "keystroke": ks(), "mouse": ms(), "context": ctx()})
check("duplicate username rejected", s == 400, f"got {s}")
s, body = req("/auth/login", {"username": uname, "password": "wrong",
                              "keystroke": ks(), "mouse": ms(), "context": ctx()})
check("wrong password rejected", s == 401, f"got {s}")
s, body = req("/auth/login", {"username": uname, "password": "P!123456",
                              "keystroke": ks(), "mouse": ms(), "context": ctx()})
check("correct password accepted", s == 200 and bool(body.get("access_token")), f"got {s}")
s, _ = req("/session/telemetry", {"keystroke": ks(), "mouse": ms(), "context": ctx()}, token="garbage")
check("invalid token rejected", s == 401, f"got {s}")
s, _ = req("/session/telemetry", {"keystroke": ks(), "mouse": ms(), "context": ctx()})
check("missing token rejected", s == 401, f"got {s}")

# --- telemetry basics ------------------------------------------------------
print("\ntelemetry & trust vector")
_, token, _ = new_user("tele")
s, b = beat(token, "view")
check("telemetry accepted", s == 200, f"got {s}")
check("returns a trust vector of 3 components", len(b.get("trust_vector", [])) == 3)
check("returns 8 per-feature scores", len(b.get("feature_scores", [])) == 8,
      f"got {len(b.get('feature_scores', []))}")
check("returns context checks", len(b.get("context_checks", [])) >= 3)
check("echoes the operation back", b.get("operation") == "view")
vec = {v["operation"]: v for v in b.get("trust_vector", [])}
check("thresholds are per-operation (admin stricter than view)",
      vec.get("admin", {}).get("allow_threshold", 0) > vec.get("view", {}).get("allow_threshold", 99))
check("trust_score matches its vector component",
      abs(b["trust_score"] - vec["view"]["trust_score"]) < 0.1,
      f"{b['trust_score']} vs {vec['view']['trust_score']}")

# --- idle ------------------------------------------------------------------
print("\nidle heartbeats (must not be scored)")
_, token, _ = new_user("idle")
before = beat(token, "view")[1]["trust_score"]
s, b = beat(token, "view", keystroke=ks(0, 0, 0), mouse=ms(0, 0))
check("idle heartbeat accepted", s == 200, f"got {s}")
check("idle flagged as idle", b.get("idle") is True)
check("idle leaves trust unchanged", abs(b["trust_score"] - before) < 0.01,
      f"{before} -> {b['trust_score']}")
s2, b2 = beat(token, "view", keystroke=ks(0, 0, 0), mouse=ms(0, 0))
check("repeated idle does not terminate the session", s2 == 200, f"got {s2}")

# --- vector independence ---------------------------------------------------
print("\noperation independence")
_, token, _ = new_user("vec")
beat(token, "view")
b = beat(token, "admin", keystroke=ks(dwell=35, flight=28, count=30))[1]
v = {x["operation"]: x["trust_score"] for x in b["trust_vector"]}
check("anomaly on admin does not move view", v["view"] > 90, f"view={v['view']}")
check("anomaly on admin does not move edit", v["edit"] == 100.0, f"edit={v['edit']}")
check("anomaly on admin lowers admin", v["admin"] < v["view"], f"admin={v['admin']}")

# --- detector behaviour ----------------------------------------------------
print("\ndetector: consistent typing stays trusted, anomalies get caught")
_, token, _ = new_user("detect")
lo = 100.0
for i in range(12):
    b = beat(token, "view", keystroke=ks(dwell=90 + (i % 3) * 3, flight=110 - (i % 3) * 2))[1]
    if not b.get("idle"):
        lo = min(lo, b["behavior_score"])
check("consistent typing never scored below 55", lo >= 55, f"lowest was {lo:.1f}")

b_fast = beat(token, "view", keystroke=ks(dwell=32, flight=25, count=30))[1]["behavior_score"]
check("3x faster typing scored as anomalous", b_fast < 60, f"got {b_fast:.1f}")
b_slow = beat(token, "view", keystroke=ks(dwell=210, flight=420, count=8))[1]["behavior_score"]
check("very slow typing scored as anomalous", b_slow < 60, f"got {b_slow:.1f}")
b_mild = beat(token, "view", keystroke=ks(dwell=100, flight=102))[1]["behavior_score"]
check("mild natural drift still trusted", b_mild >= 55, f"got {b_mild:.1f}")

# --- context: unknown device ----------------------------------------------
print("\ncontext checks")
_, token, _ = new_user("ctx", fp="known-device")
b = beat(token, "admin", fp="brand-new-device")[1]
dev = next((c for c in b["context_checks"] if c["name"] == "Device fingerprint"), {})
check("unknown device penalised", dev.get("score", 100) < 100, f"{dev}")
check("unknown device costs more on admin than view",
      dev.get("score", 100) <= 55, f"admin device score {dev.get('score')}")

# --- impossible travel -----------------------------------------------------
print("\nimpossible travel (demo location)")
_, token, _ = new_user("travel")
beat(token, "view", location="mumbai")
b = beat(token, "admin", location="new_york")[1]
loc = next((c for c in b["context_checks"] if c["name"] == "Location plausibility"), {})
check("impossible travel detected", "Impossible travel" in loc.get("detail", ""), f"{loc.get('detail')}")
check("impossible travel lowers context score", b["context_score"] < 100, f"{b['context_score']}")

# --- status / calibration / logout ----------------------------------------
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

# --- termination revokes a still-valid JWT ---------------------------------
print("\nmid-session revocation")
_, token, _ = new_user("term")
killed = False
for _ in range(8):
    s, b = beat(token, "admin", keystroke=ks(dwell=300, flight=600, count=5), mouse=ms(vel=9.5))
    if s == 403 or (s == 200 and b.get("decision") == "terminate"):
        killed = True
        break
check("sustained anomaly terminates the session", killed)
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
