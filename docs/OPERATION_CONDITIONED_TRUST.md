# Operation-Conditioned Trust (design + implementation map)

Every continuous-authentication system surveyed for this project — including
commercial behavioral-biometrics products — computes **one scalar trust
score** from **one behavioral baseline per user**, then compares it against
fixed thresholds. That shared design has a specific weakness: a user's
typing/mouse behavior while composing a report is not the same distribution
as their behavior while deleting records or touching admin settings. One
global baseline concentrates false positives (and false negatives) exactly
on the operations where they're most costly.

This document describes the pivot implemented here: trust is not a scalar
`T(t)`, it's a **vector** `T(t) ∈ [0,100]^k`, one component per *operation
class*, each with its own behavioral baseline, context weights, decay rate,
and decision thresholds.

## The model

```
T_r(t) = T_r(t-1)·e^(-λ_r·Δt) + (1 - e^(-λ_r·Δt))·evidence_r(t)

evidence_r(t) = clamp(0.6·behavior_score(x|r) + 0.4·context_score(x|r) - transition_penalty, 0, 100)
```

- `r` — an operation class (`view`, `edit`, `admin` in this implementation)
- `behavior_score(x|r)` — anomaly score of the current sample against a
  baseline trained **only on that user's history for operation `r`**, not
  their global history
- `context_score(x|r)` — the same device-fingerprint / impossible-travel
  checks as before, but penalized by **per-operation weights** `w_i,r`
  (an unfamiliar device costs far more on `admin` than on `view`)
- `transition_penalty` — a penalty when the jump from the user's last
  operation to this one is unusually rare for them specifically (the
  navigation-sequence signal, described below)
- `λ_r` — decay rate: how "sticky" trust is for that operation. `view` has a
  small `λ` (slow decay, ~115s half-life); `admin` has a large `λ` (fast
  decay, ~11.5s half-life — must be re-earned almost every heartbeat)

Decay is applied **lazily**: `Δt` is the real elapsed time since that
specific operation's component was last touched, computed at the moment a
new sample for that operation arrives. There's no background ticker constantly
decaying idle components — an operation you haven't touched in an hour
doesn't silently drift; it only updates the next time you actually perform it.

## Why this is a real difference, not a threshold trick

The naive way to "add operations" would be to keep one global trust score and
just use different thresholds per operation. That's a config change, not a
different model — the underlying `s(x)` is still one distribution. Here,
`s(x | r)` is a **separate trained model per (user, operation)** pair
(`operation_behavior_score` trains a separate `IsolationForest` per
operation, keyed `{user_id}__{operation}` in the model store), so the
thing being compared against changes, not just the number it's compared to.

## Operation-sequence anomaly (the secondary signal, now actually used)

The original design listed session-navigation flow as a collected context
signal but never used it in the scoring math. It's wired in now:
`OperationTransition` accumulates a per-user frequency table of
`(from_operation → to_operation)` transitions. When a user jumps to an
operation that's historically rare from wherever they just were (e.g.
straight to `admin` without their usual path through `view`), it's scored
as its own penalty (`transition_penalty` in `risk_engine.py`) and surfaced
as a `"Navigation pattern"` context check with a human-readable reason,
alongside the existing device/location checks.

## What's a starter, not a finished mechanism

**Threshold/weight calibration** (`risk_engine.suggest_threshold_calibration`)
is a simple frequency heuristic over the `RiskEvent` audit log (if step-ups
fire on more than 25% of a sensitive operation's events, nudge that
operation's threshold down slightly) — not a full
`argmin_θ friction_cost·P(false step-up) + breach_cost·P(missed attack)`
optimizer. A real cost-optimal calibration needs labeled incident data or a
simulated attacker model to estimate a breach likelihood from; an audit log
alone only tells you how often *this system* chose to challenge, not how
often it was *right* to. The current defaults in
`config.OPERATION_CONFIG` (decay rates, context weights, thresholds) are
project design choices, the same status as the original 0.6/0.4
behavior/context split — documented, tunable, not derived from a
calibration run.

**Predictive trust pre-warming** (mentioned as a secondary angle) is *not*
implemented — this API is synchronous request/response with no request
queue to pre-warm ahead of, so there's no real latency problem for it to
solve at this scale. Noted here as an intentional scope cut, not an
oversight.

**Session-level enforcement is still all-or-nothing.** A `terminate`
decision on *any* operation still ends the whole `AuthSession` (same
mechanism as the original scalar model: the session's `status` flips and
`deps.get_current_session` 403s all further requests). Making enforcement
itself per-operation (e.g. only locking out `admin` while `view` stays live)
would be a further architectural change beyond scoring, not attempted here.

## Implementation map

| Concept | Code |
|---|---|
| Per-operation behavioral baseline `s(x\|r)` | `risk_engine.operation_behavior_score` |
| Per-operation context weights `w_i,r` | `risk_engine.operation_context_score`, `config.OPERATION_CONFIG[op]["device_weight"/"location_weight"]` |
| Navigation-sequence penalty | `risk_engine.transition_penalty`, `models.OperationTransition` |
| Vector state + lazy decay | `risk_engine.update_trust_vector`, `models.OperationTrust` |
| Per-operation thresholds `θ_r` | `config.OPERATION_CONFIG[op]["allow_threshold"/"stepup_threshold"]` |
| Calibration starter | `risk_engine.suggest_threshold_calibration` |
| Operation tagging on training data | `models.BehaviorSample.operation` |
| API surface | `schemas.TelemetryRequest.operation`, `schemas.SessionStatusResponse.trust_vector` |
| UI: operation selector + vector display | `frontend/src/pages/Dashboard.jsx`, `frontend/src/components/TrustVectorPanel.jsx` |

## Prior art positioning

Scalar, single-baseline continuous-authentication systems (commercial
products like BioCatch/Plurilock, and the academic keystroke/mouse-dynamics
literature surveyed earlier in this project) compute one `s(x)` per user and
compare it to one set of thresholds regardless of what the user is doing.
The operation-conditioned model here is a different claim: trust is
operation-indexed, each component has its own baseline, decay rate, and
context weights, calibrated (in principle) via cost-sensitive optimization
per operation class rather than hand-set globally.

**Two caveats, unchanged from the original analysis this document
implements:** this is still engineering documentation, not a formal patent
search — search Google Patents for "operation-specific" / "context-
conditioned" behavioral baselines before relying on the novelty claim. And
if a patent filing is actually intended, don't present this version
publicly (a project review counts, if it's open) before filing.
