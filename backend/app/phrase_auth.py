"""Fixed-phrase keystroke verification.

The continuous free-text engine (risk_engine) answers "has this session's
behavior drifted?". It cannot answer "is this the enrolled person?" with
much confidence, because its features are averages over whatever text
happened to be typed, so they track content as much as identity.

This module answers the identity question the way the keystroke-dynamics
literature does: everyone types the SAME phrase, so timings line up
position by position and can be compared like-for-like -- your hold time on
character 7 against your own distribution of hold times on character 7.

Scoring: for each position, how many robust standard deviations is this
attempt from the enrolled median? Positions are combined with a trimmed
mean so one mistyped-but-corrected key or one hesitation cannot by itself
fail an otherwise genuine attempt, while a consistently different rhythm
across many positions does.
"""

from typing import List, Optional, Tuple

import numpy as np

from app.models import PhraseSample

# Same MAD scaling as the risk engine, for the same reason: human timing
# data has outliers (a pause, a stumble) and a plain std lets a couple of
# them widen the profile until nothing looks unusual.
MAD_TO_STD = 1.4826

# Floors so a user with near-identical enrollment attempts doesn't end up
# with a zero-width distribution that rejects every later attempt.
RELATIVE_SPREAD_FLOOR = 0.20
ABSOLUTE_SPREAD_FLOOR_MS = 8.0

# Fraction of worst-matching positions to discard before averaging.
TRIM_FRACTION = 0.15

# Deviation (in robust sigmas) that maps to a score of 0.
MAX_SIGMA = 4.0

MIN_ENROLLMENTS = 3


def _spread(values: np.ndarray, centre: float) -> float:
    mad = float(np.median(np.abs(values - centre))) * MAD_TO_STD
    return max(mad, abs(centre) * RELATIVE_SPREAD_FLOOR, ABSOLUTE_SPREAD_FLOOR_MS)


def _column(samples: List[dict], key: str, i: int) -> np.ndarray:
    """Timing at position i across enrollment attempts, skipping missing."""
    vals = []
    for s in samples:
        seq = s.get(key) or []
        if i < len(seq) and seq[i] is not None:
            vals.append(float(seq[i]))
    return np.array(vals, dtype=float)


def score_attempt(attempt: dict, enrolled: List[dict]) -> Tuple[float, dict]:
    """Returns (0-100 score, detail). Higher means a closer match to the
    enrolled typing rhythm for this phrase."""
    if len(enrolled) < MIN_ENROLLMENTS:
        return 100.0, {"status": "not_enrolled", "enrollments": len(enrolled)}

    deviations: List[float] = []
    per_position: List[dict] = []

    for key in ("dwell_ms", "flight_ms"):
        seq = attempt.get(key) or []
        for i, raw in enumerate(seq):
            if raw is None:
                continue
            column = _column(enrolled, key, i)
            if column.size < MIN_ENROLLMENTS:
                continue
            centre = float(np.median(column))
            sigma = _spread(column, centre)
            dev = abs(float(raw) - centre) / sigma
            deviations.append(dev)
            per_position.append(
                {"feature": key, "position": i, "value": round(float(raw), 1),
                 "baseline": round(centre, 1), "sigma": round(dev, 2)}
            )

    if not deviations:
        return 100.0, {"status": "no_overlap"}

    # Trim the worst positions: a genuine typist will stumble on a key or
    # two, and those shouldn't dominate an otherwise matching rhythm.
    arr = np.sort(np.array(deviations, dtype=float))
    keep = max(1, int(len(arr) * (1.0 - TRIM_FRACTION)))
    trimmed = arr[:keep]

    mean_sigma = float(trimmed.mean())
    score = max(0.0, min(100.0, 100.0 * (1.0 - mean_sigma / MAX_SIGMA)))

    per_position.sort(key=lambda p: -p["sigma"])
    return score, {
        "status": "scored",
        "enrollments": len(enrolled),
        "positions_compared": len(deviations),
        "mean_sigma": round(mean_sigma, 2),
        "worst_positions": per_position[:5],
    }


def enrolled_samples(db, user_id: str, phrase: str) -> List[dict]:
    rows = (
        db.query(PhraseSample)
        .filter(PhraseSample.user_id == user_id, PhraseSample.phrase == phrase)
        .order_by(PhraseSample.created_at.asc())
        .all()
    )
    return [r.timings for r in rows]


def valid_attempt(attempt: Optional[dict], phrase: str) -> bool:
    """A usable attempt covers the whole phrase in order, with no typos --
    the frontend only emits a sample when that holds, but the API must not
    trust the client to have enforced it."""
    if not isinstance(attempt, dict):
        return False
    if attempt.get("phrase") != phrase:
        return False
    dwell = attempt.get("dwell_ms")
    if not isinstance(dwell, list) or len(dwell) != len(phrase):
        return False
    return any(v is not None for v in dwell)
