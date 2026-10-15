"""Learned access habits: when this user works, and what they normally do.

The one statistical family left, but on quantities far more stable than
keystroke timing. Which hours someone works, and whether they touch admin
functions at all, barely varies week to week -- whereas their typing speed
varied by a factor of four within a single session.

Everything here is a frequency count, so it is meaningful from the first
few sessions instead of needing dozens of samples, and it degrades to
"unknown, no penalty" rather than to a false alarm.
"""

from datetime import datetime
from typing import List, Tuple

from app.models import UserAccessProfile

# Below this much history nothing is called unusual -- a new user has no
# habits to deviate from yet.
MIN_EVENTS_FOR_JUDGEMENT = 20

# An hour seen in under this share of a user's activity is "off-hours".
UNUSUAL_HOUR_FREQUENCY = 0.02
# Likewise for how often they perform an operation class at all.
UNUSUAL_OPERATION_FREQUENCY = 0.03

MAX_HOUR_PENALTY = 30.0
MAX_OPERATION_PENALTY = 35.0
# Working far faster than this user ever has.
BURST_MULTIPLIER = 4.0
MAX_RATE_PENALTY = 25.0


def _profile(db, user_id: str) -> UserAccessProfile:
    row = db.query(UserAccessProfile).filter_by(user_id=user_id).first()
    if row is None:
        row = UserAccessProfile(
            user_id=user_id, hour_counts={}, operation_counts={},
            total_events=0, max_actions_per_minute=0.0,
        )
        db.add(row)
        db.flush()
    return row


def evaluate(
    db, user_id: str, operation: str, when: datetime, actions_this_beat: int
) -> Tuple[float, List[str], List[dict]]:
    row = _profile(db, user_id)
    score = 100.0
    reasons: List[str] = []
    checks: List[dict] = []

    if row.total_events < MIN_EVENTS_FOR_JUDGEMENT:
        checks.append({
            "name": "Access habits", "score": 100.0,
            "detail": f"Still learning ({row.total_events}/{MIN_EVENTS_FOR_JUDGEMENT} events)",
        })
        return score, reasons, checks

    hours = row.hour_counts or {}
    hour_key = str(when.hour)
    hour_freq = hours.get(hour_key, 0) / max(row.total_events, 1)
    if hour_freq < UNUSUAL_HOUR_FREQUENCY:
        penalty = MAX_HOUR_PENALTY * (1.0 - hour_freq / UNUSUAL_HOUR_FREQUENCY)
        score -= penalty
        detail = f"Active at {when.hour:02d}:00, an hour this account rarely uses"
        reasons.append(detail)
        checks.append({"name": "Time of day", "score": max(0.0, 100.0 - penalty), "detail": detail})
    else:
        checks.append({"name": "Time of day", "score": 100.0,
                       "detail": f"{when.hour:02d}:00 is within normal hours for this account"})

    ops = row.operation_counts or {}
    op_freq = ops.get(operation, 0) / max(row.total_events, 1)
    if op_freq < UNUSUAL_OPERATION_FREQUENCY:
        penalty = MAX_OPERATION_PENALTY * (1.0 - op_freq / UNUSUAL_OPERATION_FREQUENCY)
        score -= penalty
        detail = f"'{operation}' is rare for this account ({op_freq * 100:.1f}% of activity)"
        reasons.append(detail)
        checks.append({"name": "Operation mix", "score": max(0.0, 100.0 - penalty), "detail": detail})
    else:
        checks.append({"name": "Operation mix", "score": 100.0,
                       "detail": f"'{operation}' is routine for this account"})

    ceiling = row.max_actions_per_minute or 0.0
    if ceiling > 0 and actions_this_beat > ceiling * BURST_MULTIPLIER:
        score -= MAX_RATE_PENALTY
        detail = (f"{actions_this_beat} actions in this interval, far above this "
                  f"account's usual peak of {ceiling:.0f}")
        reasons.append(detail)
        checks.append({"name": "Activity rate", "score": 100.0 - MAX_RATE_PENALTY, "detail": detail})
    else:
        checks.append({"name": "Activity rate", "score": 100.0, "detail": "Normal pace"})

    return max(0.0, score), reasons, checks


def record(db, user_id: str, operation: str, when: datetime, actions_this_beat: int) -> None:
    """Fold a trusted interaction into the user's habits. Only ever called
    for interactions the engine allowed, so a hijacker's 3am admin burst
    cannot teach the profile that 3am admin bursts are normal."""
    row = _profile(db, user_id)
    hours = dict(row.hour_counts or {})
    ops = dict(row.operation_counts or {})
    hours[str(when.hour)] = hours.get(str(when.hour), 0) + 1
    ops[operation] = ops.get(operation, 0) + 1
    row.hour_counts = hours
    row.operation_counts = ops
    row.total_events = (row.total_events or 0) + 1
    row.max_actions_per_minute = max(row.max_actions_per_minute or 0.0, float(actions_this_beat))
