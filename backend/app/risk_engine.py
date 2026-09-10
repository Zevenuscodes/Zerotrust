"""AI-based risk analysis: turns a live behavior+context sample into an
operation-conditioned trust VECTOR and a policy decision.

This is the operation-conditioned pivot on the original scalar design: every
system that computes one global trust score with one behavioral baseline per
user shares the same weakness -- a user's typing/mouse behavior composing a
report is not the same distribution as their behavior deleting records or
touching admin settings, so a single baseline concentrates false positives
(and false negatives) exactly on the sensitive operations. Here, trust is a
vector T(t) in [0,100]^k, one component per operation class in
config.OPERATION_CLASSES, each with its own:

  - behavior baseline    (operation_behavior_score)  -- s(x | r), not s(x)
  - context weights      (operation_context_score)   -- w_i,r, not fixed w_i
  - navigation-sequence check (transition_penalty)    -- unused signal, wired in
  - decay rate            (update_trust_vector)        -- lambda_r
  - decision thresholds   (config.OPERATION_CONFIG)    -- theta_r, not global

  T_r(t) = T_r(t-1)*e^(-lambda_r*dt) + (1-e^(-lambda_r*dt)) * evidence_r(t)
  evidence_r(t) = clamp(0.6*behavior_score(x|r) + 0.4*context_score(x|r) - transition_penalty, 0, 100)

behavior_score(x|r): per-(user, operation) IsolationForest trained on that
  operation's accumulated keystroke/mouse feature vectors. Bootstraps from
  all-operation history when the operation itself doesn't have
  MIN_SAMPLES_FOR_MODEL samples yet, so a brand-new operation class still
  gets a meaningful score instead of a cold-start default (the response
  flags `bootstrapped=True` when this happens, so it's never silently
  conflated with a real operation-specific reading).

context_score(x|r): rule-based checks against the user's known-device/
  location history, weighted per operation (config.OPERATION_CONFIG).

transition_penalty: is this operation an unusual jump from the user's last
  operation, per their own historical transition frequencies?
"""

import math
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.config import OPERATION_CONFIG, TRANSITION_MAX_PENALTY, TRANSITION_MIN_HISTORY, TRANSITION_RARE_FREQUENCY
from app.model_store import model_store
from app.models import AuthSession, BehaviorSample, KnownContext, OperationTransition, OperationTrust
from app.schemas import ContextSample, KeystrokeSample, MouseSample

# An IsolationForest needs meaningfully more than a handful of points in this
# 8-dimensional feature space to say anything at all. Measured on this
# feature set: at 5 samples it returns the *same* score for a normal sample
# and a 3x-faster-typing anomaly (no discriminative power whatsoever), and it
# only starts ranking anomalies below normal samples at ~10, with clear
# separation from ~20. Handing over to it at 5 produced a large scoring
# discontinuity -- identical behavior scored ~96 on the statistical path and
# ~50 the moment the forest took over. Below this threshold the standardized
# per-feature distance path is both better behaved and better calibrated.
MIN_SAMPLES_FOR_MODEL = 20
FEATURE_ORDER = [
    "mean_dwell_ms",
    "std_dwell_ms",
    "mean_flight_ms",
    "std_flight_ms",
    "mean_velocity",
    "std_velocity",
    "mean_acceleration",
    "direction_changes",
]

# km/h an implied-travel-speed above this is not humanly possible between two logins
IMPOSSIBLE_TRAVEL_KMH = 900.0
EARTH_RADIUS_KM = 6371.0


def featurize(keystroke: KeystrokeSample, mouse: MouseSample) -> dict:
    return {
        "mean_dwell_ms": keystroke.mean_dwell_ms,
        "std_dwell_ms": keystroke.std_dwell_ms,
        "mean_flight_ms": keystroke.mean_flight_ms,
        "std_flight_ms": keystroke.std_flight_ms,
        "mean_velocity": mouse.mean_velocity,
        "std_velocity": mouse.std_velocity,
        "mean_acceleration": mouse.mean_acceleration,
        "direction_changes": float(mouse.direction_changes),
    }


def _vector(features: dict) -> np.ndarray:
    return np.array([[features[k] for k in FEATURE_ORDER]], dtype=float)


def _history_matrix(samples: List[BehaviorSample]) -> np.ndarray:
    return np.array(
        [[s.features.get(k, 0.0) for k in FEATURE_ORDER] for s in samples], dtype=float
    )


# How much natural sample-to-sample variation to assume for a feature before
# any real variance has been observed (e.g. a single baseline sample, where
# std is literally 0). A flat absolute floor here is wrong: 1.0 is far too
# tight for a ~90ms dwell-time feature (any normal 15-20ms human variation
# between heartbeats reads as a huge z-score) and too loose for a ~0.01
# acceleration feature. Scaling the floor to the feature's own magnitude
# fixes both directions at once.
RELATIVE_STD_FLOOR = 0.15
ABSOLUTE_STD_FLOOR = 1e-3

# Minimum spread to assume among IsolationForest score_samples values. Their
# scale is unrelated to the raw features', so this needs its own floor.
ISOFOREST_SCORE_STD_FLOOR = 0.01


def _safe_std(std: np.ndarray, mean: np.ndarray) -> np.ndarray:
    return np.maximum(std, np.maximum(RELATIVE_STD_FLOOR * np.abs(mean), ABSOLUTE_STD_FLOOR))


def _per_feature_scores(features: dict, history: np.ndarray) -> List[dict]:
    """Per-parameter breakdown: how far each individual feature sits from the
    (operation-specific) historical baseline used for this evaluation."""
    if history.shape[0] == 0:
        return [
            {"name": k, "value": round(features[k], 3), "baseline_mean": None, "z_score": 0.0, "score": 100.0}
            for k in FEATURE_ORDER
        ]

    centroid = history.mean(axis=0)
    std = history.std(axis=0)
    std_safe = _safe_std(std, centroid)
    vector = _vector(features)[0]

    results = []
    for i, key in enumerate(FEATURE_ORDER):
        z = abs(float((vector[i] - centroid[i]) / std_safe[i]))
        score = max(0.0, min(100.0, 100.0 - z * 20.0))
        results.append(
            {
                "name": key,
                "value": round(float(vector[i]), 3),
                "baseline_mean": round(float(centroid[i]), 3),
                "z_score": round(z, 3),
                "score": round(score, 1),
            }
        )
    return results


def _samples_for(db: DBSession, user_id: str, operation: Optional[str]) -> List[BehaviorSample]:
    q = db.query(BehaviorSample).filter(BehaviorSample.user_id == user_id)
    if operation is not None:
        q = q.filter(BehaviorSample.operation == operation)
    return q.order_by(BehaviorSample.created_at.asc()).all()


def operation_behavior_score(
    db: DBSession, user_id: str, operation: str, features: dict
) -> Tuple[float, List[dict], bool]:
    """s(x | r): anomaly score of `features` against the baseline for this
    (user, operation) pair specifically -- not the user's global baseline.
    Returns (score, per_feature_breakdown, bootstrapped) where bootstrapped
    is True when this operation didn't yet have enough of its own history
    and the all-operations history was used to avoid a meaningless cold-start
    default."""
    op_samples = _samples_for(db, user_id, operation)
    bootstrapped = False
    samples = op_samples
    if len(op_samples) < MIN_SAMPLES_FOR_MODEL:
        samples = _samples_for(db, user_id, None)
        bootstrapped = True

    vector = _vector(features)
    history = _history_matrix(samples)
    feature_scores = _per_feature_scores(features, history)

    if not samples:
        return 100.0, feature_scores, bootstrapped

    # The standardized-distance detector ALWAYS runs, at every sample count.
    # It is well behaved on the handful of samples a real user actually
    # accumulates, it is monotonic (further from baseline always scores
    # lower), and it is directly interpretable -- the same z-scores shown in
    # the per-parameter breakdown. The IsolationForest below can only pull
    # this score down, never push it up, so an anomaly this detector catches
    # can never be masked by the forest calling it normal.
    centroid = history.mean(axis=0)
    std = history.std(axis=0)
    std_safe = _safe_std(std, centroid)
    z = np.abs((vector[0] - centroid) / std_safe)
    # RMS, not a plain mean: typing unusually fast only shifts the 4
    # keystroke features, leaving the 4 mouse features near-baseline. A
    # plain average lets those unaffected features dilute a real
    # keystroke anomaly by ~half. RMS weights large deviations more
    # heavily so a strong anomaly in a subset of features isn't washed
    # out by the features that were never going to move.
    agg_z = float(np.sqrt(np.mean(z ** 2)))
    statistical_score = float(max(0.0, 100.0 - agg_z * 20.0))

    if len(samples) < MIN_SAMPLES_FOR_MODEL:
        return statistical_score, feature_scores, bootstrapped

    # model key includes the operation so "view"/"edit"/"admin" baselines
    # for the same user never overwrite each other in the ModelStore.
    # contamination is low, not 0.15: this history is only ever samples the
    # engine already decided to trust (allow-decisions), so assuming 15% of
    # it is anomalous makes the model carve a needlessly tight boundary
    # around the user's own normal behavior.
    model = IsolationForest(n_estimators=100, contamination=0.02, random_state=42)
    model.fit(history)
    model_store.save(f"{user_id}__{operation}" if not bootstrapped else f"{user_id}__all", model)

    # Score the new sample RELATIVE to how the user's own history scores,
    # rather than against an assumed absolute range. decision_function does
    # not really span [-0.5, 0.5] -- for a tight cluster it returns values
    # near 0, so a fixed (raw + 0.5) * 100 mapping pins even perfectly
    # consistent behavior into a ~45-60 band forever. Measuring how far
    # below the training set's own mean anomaly score this sample falls,
    # in units of that set's spread, is self-calibrating per user and uses
    # the same "deviation * 20" scale as the cold-start branch above -- so
    # crossing MIN_SAMPLES_FOR_MODEL no longer produces a scoring cliff.
    train_scores = model.score_samples(history)
    new_score = float(model.score_samples(vector)[0])
    ref_mean = float(train_scores.mean())
    # Floor is a small absolute value on the score_samples scale (which spans
    # roughly 0.05-0.1 across a trained set). RELATIVE_STD_FLOOR is deliberately
    # NOT used here: it is a fraction of a feature's magnitude, which is
    # meaningful for raw features (15% of a 90ms dwell time is real jitter) but
    # meaningless against score_samples' arbitrary ~-0.47 offset, where it would
    # dwarf the true spread and flatten every anomaly into "normal".
    ref_std = float(max(train_scores.std(), ISOFOREST_SCORE_STD_FLOOR))

    deviation = max(0.0, (ref_mean - new_score) / ref_std)  # only penalize being MORE anomalous than usual
    forest_score = float(max(0.0, min(100.0, 100.0 - deviation * 20.0)))

    # Take the more conservative of the two detectors. The forest contributes
    # genuine value -- it can catch odd *combinations* of features that each
    # look individually normal, which per-feature distance cannot -- but it
    # must not be able to vouch for a sample the statistical detector has
    # already flagged. Measured on this feature set, the forest scored a
    # 210ms-dwell / 420ms-flight sample (vs a 90/110 baseline) as perfectly
    # normal; min() makes that impossible to act on.
    return min(statistical_score, forest_score), feature_scores, bootstrapped


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def operation_context_score(
    db: DBSession,
    user_id: str,
    operation: str,
    context: ContextSample,
    geo: Tuple[float, float, str, str] | None,
) -> Tuple[float, List[str], List[dict]]:
    """w_i,r applied: the same unrecognized-device / impossible-travel checks
    as before, but penalized by this operation's own weights -- an
    unfamiliar device costs far more on "admin" than on "view"."""
    cfg = OPERATION_CONFIG[operation]
    score = 100.0
    reasons: List[str] = []
    checks: List[dict] = []

    known = (
        db.query(KnownContext)
        .filter(KnownContext.user_id == user_id, KnownContext.device_fingerprint == context.device_fingerprint)
        .first()
    )
    if known is None:
        score -= cfg["device_weight"]
        reasons.append(f"Unrecognized device fingerprint (weighted {cfg['device_weight']:.0f} for '{operation}')")
        checks.append(
            {
                "name": "Device fingerprint",
                "score": max(0.0, 100.0 - cfg["device_weight"]),
                "detail": f"Unrecognized device -- {cfg['device_weight']:.0f}pt penalty for '{operation}'",
            }
        )
    else:
        checks.append({"name": "Device fingerprint", "score": 100.0, "detail": "Recognized device"})

    if geo is None:
        checks.append({"name": "Location plausibility", "score": 100.0, "detail": "No geolocation available"})
    else:
        lat, lon, city, country = geo
        last_known = (
            db.query(KnownContext)
            .filter(KnownContext.user_id == user_id, KnownContext.geo_lat.isnot(None))
            .order_by(KnownContext.last_seen.desc())
            .first()
        )
        if last_known is None or last_known.geo_lat is None:
            checks.append({"name": "Location plausibility", "score": 100.0, "detail": "No prior location on record"})
        else:
            distance_km = _haversine_km(last_known.geo_lat, last_known.geo_lon, lat, lon)
            elapsed_hours = max(
                (datetime.utcnow() - last_known.last_seen).total_seconds() / 3600.0, 0.01
            )
            implied_speed = distance_km / elapsed_hours
            if implied_speed > IMPOSSIBLE_TRAVEL_KMH and distance_km > 100:
                score -= cfg["location_weight"]
                detail = (
                    f"Impossible travel: {distance_km:.0f}km in {elapsed_hours:.1f}h "
                    f"(~{implied_speed:.0f} km/h) since last seen in {last_known.geo_city}, {last_known.geo_country} "
                    f"(weighted {cfg['location_weight']:.0f} for '{operation}')"
                )
                reasons.append(detail)
                checks.append({"name": "Location plausibility", "score": max(0.0, 100.0 - cfg["location_weight"]), "detail": detail})
            else:
                checks.append(
                    {
                        "name": "Location plausibility",
                        "score": 100.0,
                        "detail": f"{distance_km:.0f}km since last seen -- plausible",
                    }
                )

    return max(0.0, score), reasons, checks


def transition_penalty(db: DBSession, user_id: str, last_operation: Optional[str], operation: str) -> Tuple[float, Optional[str]]:
    """Section 5 lists session-navigation flow as a collected signal; this is
    where it's actually used. A user's typical path (e.g. view -> edit) is
    learned as a frequency table; a rare jump (e.g. straight to admin) is
    penalized in proportion to how rare it's been for this specific user."""
    if not last_operation or last_operation == operation:
        return 0.0, None

    total = (
        db.query(func.sum(OperationTransition.count))
        .filter(OperationTransition.user_id == user_id, OperationTransition.from_operation == last_operation)
        .scalar()
        or 0
    )
    if total < TRANSITION_MIN_HISTORY:
        return 0.0, None  # not enough navigation history yet to call anything "unusual"

    this_row = (
        db.query(OperationTransition)
        .filter(
            OperationTransition.user_id == user_id,
            OperationTransition.from_operation == last_operation,
            OperationTransition.to_operation == operation,
        )
        .first()
    )
    this_count = this_row.count if this_row else 0
    freq = this_count / total

    if freq < TRANSITION_RARE_FREQUENCY:
        penalty = TRANSITION_MAX_PENALTY * (1.0 - freq / TRANSITION_RARE_FREQUENCY)
        reason = (
            f"Unusual navigation: '{last_operation}' -> '{operation}' seen in only "
            f"{freq * 100:.0f}% of your past transitions from '{last_operation}'"
        )
        return round(penalty, 1), reason

    return 0.0, None


def _record_transition(db: DBSession, user_id: str, last_operation: Optional[str], operation: str) -> None:
    if not last_operation:
        return  # first operation of the session -- nothing to record a transition from
    row = (
        db.query(OperationTransition)
        .filter(
            OperationTransition.user_id == user_id,
            OperationTransition.from_operation == last_operation,
            OperationTransition.to_operation == operation,
        )
        .first()
    )
    if row is None:
        row = OperationTransition(user_id=user_id, from_operation=last_operation, to_operation=operation, count=0)
        db.add(row)
    row.count += 1


def update_trust_vector(db: DBSession, session: AuthSession, operation: str, evidence: float) -> float:
    """T_r(t) = T_r(t-1)*e^(-lambda_r*dt) + (1-e^(-lambda_r*dt))*evidence.
    Decay is applied lazily: dt is the real elapsed time since this specific
    operation's component was last touched, so operations you haven't
    performed in a while don't silently drift -- they only update (and only
    decay toward fresh evidence) the next time you actually perform them."""
    lam = OPERATION_CONFIG[operation]["decay_rate"]
    row = db.query(OperationTrust).filter_by(session_id=session.id, operation=operation).first()
    now = datetime.utcnow()

    if row is None:
        # first time this operation is evaluated this session: start from evidence,
        # matching the original scalar model's "session starts at 100" semantics
        # would be wrong here -- a session's first admin action still has to earn
        # its own trust rather than inheriting a global 100.
        new_value = evidence
        row = OperationTrust(session_id=session.id, operation=operation, trust_score=new_value, updated_at=now)
        db.add(row)
    else:
        dt = max((now - row.updated_at).total_seconds(), 0.0)
        decay = math.exp(-lam * dt)
        new_value = row.trust_score * decay + (1.0 - decay) * evidence
        row.trust_score = new_value
        row.updated_at = now

    # the DB session has autoflush disabled, and trust_vector() (called right
    # after this in evaluate()) reads OperationTrust back via a fresh query --
    # without flushing here, that query misses this pending change and
    # reports the stale value.
    db.flush()
    return float(max(0.0, min(100.0, new_value)))


def trust_vector(db: DBSession, session: AuthSession) -> List[dict]:
    """The full vector T(t): every operation class's current component,
    defaulting unevaluated operations to 100 (a session starts fully
    trusted for anything it hasn't tried yet, same as the original model)."""
    rows = {r.operation: r.trust_score for r in db.query(OperationTrust).filter_by(session_id=session.id).all()}
    result = []
    for op, cfg in OPERATION_CONFIG.items():
        score = rows.get(op, 100.0)
        if score >= cfg["allow_threshold"]:
            decision = "allow"
        elif score >= cfg["stepup_threshold"]:
            decision = "stepup"
        else:
            decision = "terminate"
        result.append(
            {
                "operation": op,
                "trust_score": round(score, 2),
                "decision": decision,
                "allow_threshold": cfg["allow_threshold"],
                "stepup_threshold": cfg["stepup_threshold"],
            }
        )
    return result


def evaluate(
    db: DBSession,
    session: AuthSession,
    operation: str,
    keystroke: KeystrokeSample,
    mouse: MouseSample,
    context: ContextSample,
    ip_address: str,
    geo: Tuple[float, float, str, str] | None,
) -> dict:
    if operation not in OPERATION_CONFIG:
        operation = "view"

    user_id = session.user_id

    if keystroke.key_count == 0 and mouse.point_count == 0:
        # No keyboard/mouse activity happened since the last heartbeat --
        # this is "no data", not "abnormal data". A zero-filled feature
        # vector compared against a non-zero baseline reads as a huge
        # deviation, which would otherwise punish a user for the simple act
        # of not touching the keyboard/mouse for 12s. Leave the vector
        # completely untouched and report its current state instead of
        # scoring this heartbeat at all.
        current_vector = trust_vector(db, session)
        current = next((v for v in current_vector if v["operation"] == operation), None)
        idle_score = current["trust_score"] if current else 100.0
        idle_decision = current["decision"] if current else "allow"
        return {
            "operation": operation,
            "behavior_score": idle_score,
            "context_score": idle_score,
            "evidence_score": None,
            "trust_score": idle_score,
            "decision": idle_decision,
            "reasons": [],
            "features": {},
            "feature_scores": [],
            "context_checks": [],
            "bootstrapped": False,
            "trust_vector": current_vector,
            "idle": True,
        }

    features = featurize(keystroke, mouse)
    b_score, feature_scores, bootstrapped = operation_behavior_score(db, user_id, operation, features)
    c_score, reasons, context_checks = operation_context_score(db, user_id, operation, context, geo)
    t_penalty, t_reason = transition_penalty(db, user_id, session.last_operation, operation)

    if t_reason:
        reasons.append(t_reason)
        context_checks.append({"name": "Navigation pattern", "score": max(0.0, 100.0 - t_penalty), "detail": t_reason})
    else:
        detail = "Consistent with your usual navigation" if session.last_operation else "First operation this session"
        context_checks.append({"name": "Navigation pattern", "score": 100.0, "detail": detail})

    evidence = max(0.0, min(100.0, 0.6 * b_score + 0.4 * c_score - t_penalty))
    updated_trust = update_trust_vector(db, session, operation, evidence)

    _record_transition(db, user_id, session.last_operation, operation)
    session.last_operation = operation

    cfg = OPERATION_CONFIG[operation]
    if updated_trust >= cfg["allow_threshold"]:
        decision = "allow"
    elif updated_trust >= cfg["stepup_threshold"]:
        decision = "stepup"
    else:
        decision = "terminate"

    return {
        "operation": operation,
        "behavior_score": b_score,
        "context_score": c_score,
        "evidence_score": evidence,
        "trust_score": updated_trust,
        "decision": decision,
        "reasons": reasons,
        "features": features,
        "feature_scores": feature_scores,
        "context_checks": context_checks,
        "bootstrapped": bootstrapped,
        "trust_vector": trust_vector(db, session),
        "idle": False,
    }


def suggest_threshold_calibration(db: DBSession) -> dict:
    """Starter method for calibrating theta_r / w_i,r from the audit log
    instead of hand-picking them, answering the "no concrete calibration
    method" gap. This is a simple frequency-based heuristic over RiskEvent
    (friction proxy: step-ups the user then verified correctly, i.e. almost
    certainly false positives), NOT a full expected-loss optimizer -- there's
    no labeled breach/attack data in an audit log to estimate a real breach
    likelihood from, so a true
    `argmin_theta friction_cost*P(false step-up) + breach_cost*P(missed attack)`
    optimization needs either labeled incident data or a simulated attacker
    model, neither of which exists here. This gives a defensible starting
    point (and the shape the real optimizer would plug into), not a finished
    calibration.
    """
    from app.models import RiskEvent

    suggestions = {}
    for operation, cfg in OPERATION_CONFIG.items():
        events = db.query(RiskEvent).filter(RiskEvent.operation == operation).all()
        stepups = [e for e in events if e.decision == "stepup"]
        if len(events) < 20:
            suggestions[operation] = {
                "status": "insufficient_data",
                "events_seen": len(events),
                "note": "Need more audit-log volume for this operation before suggesting a threshold change.",
            }
            continue
        stepup_rate = len(stepups) / len(events)
        suggestion = dict(cfg)
        if stepup_rate > 0.25:
            # step-ups firing on >25% of events for a sensitive operation suggests
            # too much friction -- nudge the threshold down slightly
            suggestion["stepup_threshold"] = round(cfg["stepup_threshold"] * 0.95, 1)
        suggestions[operation] = {
            "status": "ok",
            "events_seen": len(events),
            "observed_stepup_rate": round(stepup_rate, 3),
            "current": cfg,
            "suggested": suggestion,
        }
    return suggestions
