"""AI-based risk analysis: turns a live behavior+context sample into a
0-100 trust score and a policy decision.

behavior_score: per-user IsolationForest trained on accumulated
  keystroke/mouse feature vectors (baseline + past sessions). With fewer
  than MIN_SAMPLES_FOR_MODEL samples, falls back to a normalized distance
  from the baseline centroid so the very first login still gets a
  meaningful score instead of a cold-start default.

context_score: rule-based checks against the user's known-device/location
  history — unseen device fingerprint, and an "impossible travel" check
  (implied speed between two geolocations in the elapsed time).
"""

import math
from datetime import datetime
from typing import List, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.model_store import model_store
from app.models import BehaviorSample, KnownContext
from app.schemas import KeystrokeSample, MouseSample, ContextSample

MIN_SAMPLES_FOR_MODEL = 5
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


def behavior_score(db: DBSession, user_id: str, features: dict) -> float:
    samples = (
        db.query(BehaviorSample)
        .filter(BehaviorSample.user_id == user_id)
        .order_by(BehaviorSample.created_at.asc())
        .all()
    )
    vector = _vector(features)

    if len(samples) < MIN_SAMPLES_FOR_MODEL:
        if not samples:
            return 100.0  # no history at all (shouldn't happen post-registration)
        history = _history_matrix(samples)
        centroid = history.mean(axis=0)
        std = history.std(axis=0)
        std[std == 0] = 1.0
        z = np.abs((vector[0] - centroid) / std)
        mean_z = float(np.mean(z))
        # squash the mean z-score into a 0-100 "normality" score
        return float(max(0.0, 100.0 - mean_z * 20.0))

    history = _history_matrix(samples)
    model = IsolationForest(n_estimators=100, contamination=0.15, random_state=42)
    model.fit(history)
    model_store.save(user_id, model)

    raw_score = model.decision_function(vector)[0]  # roughly in [-0.5, 0.5], higher = more normal
    normalized = (raw_score + 0.5) * 100.0
    return float(min(100.0, max(0.0, normalized)))


def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def context_score(
    db: DBSession,
    user_id: str,
    context: ContextSample,
    ip_address: str,
    geo: Tuple[float, float, str, str] | None,
) -> Tuple[float, List[str]]:
    score = 100.0
    reasons: List[str] = []

    known = (
        db.query(KnownContext)
        .filter(KnownContext.user_id == user_id, KnownContext.device_fingerprint == context.device_fingerprint)
        .first()
    )
    if known is None:
        score -= 30.0
        reasons.append("Unrecognized device fingerprint")

    if geo is not None:
        lat, lon, city, country = geo
        last_known = (
            db.query(KnownContext)
            .filter(KnownContext.user_id == user_id, KnownContext.geo_lat.isnot(None))
            .order_by(KnownContext.last_seen.desc())
            .first()
        )
        if last_known is not None and last_known.geo_lat is not None:
            distance_km = _haversine_km(last_known.geo_lat, last_known.geo_lon, lat, lon)
            elapsed_hours = max(
                (datetime.utcnow() - last_known.last_seen).total_seconds() / 3600.0, 0.01
            )
            implied_speed = distance_km / elapsed_hours
            if implied_speed > IMPOSSIBLE_TRAVEL_KMH and distance_km > 100:
                score -= 50.0
                reasons.append(
                    f"Impossible travel: {distance_km:.0f}km in {elapsed_hours:.1f}h "
                    f"(~{implied_speed:.0f} km/h) since last seen in {last_known.geo_city}, {last_known.geo_country}"
                )

    return max(0.0, score), reasons


def evaluate(
    db: DBSession,
    user_id: str,
    keystroke: KeystrokeSample,
    mouse: MouseSample,
    context: ContextSample,
    ip_address: str,
    geo: Tuple[float, float, str, str] | None,
) -> dict:
    features = featurize(keystroke, mouse)
    b_score = behavior_score(db, user_id, features)
    c_score, reasons = context_score(db, user_id, context, ip_address, geo)
    trust = 0.6 * b_score + 0.4 * c_score

    if trust >= settings.trust_allow_threshold:
        decision = "allow"
    elif trust >= settings.trust_stepup_threshold:
        decision = "stepup"
    else:
        decision = "terminate"

    return {
        "behavior_score": b_score,
        "context_score": c_score,
        "trust_score": trust,
        "decision": decision,
        "reasons": reasons,
        "features": features,
    }
