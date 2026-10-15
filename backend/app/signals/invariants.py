"""Session-invariant drift: did the machine change under a live session?

The properties below are sealed when a session is created and re-checked on
every heartbeat. None of them can legitimately change while one person keeps
using one browser on one machine. A changed CPU core count or GPU renderer
is not "unusual behavior" to be weighed statistically -- it means the token
is being presented from a different machine than the one it was issued to.

That is why this family replaced keystroke dynamics as the primary signal:
it answers a sharp question with few false positives, where the biometric
answered a fuzzy question with many.
"""

from typing import Dict, List, Tuple

# weight = points deducted when the property differs from the sealed value.
# Graded by how physically possible a legitimate change is:
#   hardware/GPU   -- effectively impossible without a different machine
#   screen/canvas  -- impossible mid-session short of hardware changes
#   timezone/lang  -- possible (travel, settings change) but noteworthy
INVARIANTS: Dict[str, Tuple[str, float]] = {
    "hardware_concurrency": ("CPU core count", 45.0),
    "device_memory": ("Device memory", 30.0),
    "webgl_hash": ("GPU renderer", 45.0),
    "canvas_hash": ("Canvas rendering", 40.0),
    "platform": ("OS platform", 40.0),
    "screen_width": ("Screen width", 30.0),
    "screen_height": ("Screen height", 30.0),
    "color_depth": ("Colour depth", 20.0),
    "device_fingerprint": ("Device fingerprint", 35.0),
    "user_agent": ("Browser version", 15.0),
    "timezone": ("Timezone", 15.0),
    "languages": ("Languages", 10.0),
}


def seal(environment: dict) -> dict:
    """Capture the values a session is bound to at login."""
    return {k: environment.get(k) for k in INVARIANTS}


def evaluate(sealed: dict, environment: dict) -> Tuple[float, List[str], List[dict]]:
    """Returns (0-100 score, reasons, per-check detail)."""
    if not sealed:
        return 100.0, [], [{"name": "Session binding", "score": 100.0,
                            "detail": "No sealed context yet (first beat of this session)"}]

    score = 100.0
    reasons: List[str] = []
    checks: List[dict] = []
    changed = []

    for key, (label, weight) in INVARIANTS.items():
        expected = sealed.get(key)
        actual = environment.get(key)
        if expected is None or actual is None:
            continue
        if expected != actual:
            score -= weight
            changed.append(label)
            checks.append({
                "name": label,
                "score": max(0.0, 100.0 - weight),
                "detail": f"Changed mid-session: {expected!r} -> {actual!r}",
            })

    if changed:
        reasons.append(
            "Session-bound properties changed mid-session: " + ", ".join(changed)
        )
    else:
        checks.append({"name": "Session binding", "score": 100.0,
                       "detail": f"All {len(INVARIANTS)} bound properties unchanged"})

    return max(0.0, score), reasons, checks
