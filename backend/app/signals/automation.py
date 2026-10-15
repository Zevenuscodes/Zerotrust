"""Is a human driving this session, or a script?

Once a session token is stolen, the realistic abuse is automated: a script
replaying the token far faster and far more regularly than a person can
work. That is a much sharper question than "which person is typing", and it
is the one this family answers.

Nothing here tries to identify the user. It only asks whether the
interaction carries the irregularity and latency that human input always
has and synthetic input usually lacks.
"""

from typing import List, Tuple

# A browser under automation control advertises it, or is missing things a
# real browser always has. Weighted by how hard each is to fake away.
HINT_WEIGHTS = {
    "webdriver": 60.0,        # navigator.webdriver -- explicit automation flag
    "headless_ua": 50.0,      # the user agent says HeadlessChrome/PhantomJS
    "no_chrome_object": 25.0,
    "no_plugins": 15.0,
    "no_languages": 20.0,
    "zero_screen": 30.0,
}

# Humans do not act on a metronome. Below this coefficient of variation the
# gaps between actions are more regular than human motor timing produces.
MIN_HUMAN_INTERVAL_CV = 0.25
# Nor do they react to a freshly loaded page instantly.
MIN_HUMAN_REACTION_MS = 150
# Enough actions to judge regularity at all.
MIN_ACTIONS_FOR_RHYTHM = 6


def evaluate(automation: dict) -> Tuple[float, List[str], List[dict]]:
    """Returns (0-100 score where 100 is clearly human, reasons, checks)."""
    score = 100.0
    reasons: List[str] = []
    checks: List[dict] = []

    hints = automation.get("headless_hints") or []
    hint_penalty = sum(HINT_WEIGHTS.get(h, 10.0) for h in hints)
    if hint_penalty:
        score -= hint_penalty
        reasons.append("Browser reports automation indicators: " + ", ".join(hints))
        checks.append({"name": "Browser authenticity", "score": max(0.0, 100.0 - hint_penalty),
                       "detail": "Automation indicators: " + ", ".join(hints)})
    else:
        checks.append({"name": "Browser authenticity", "score": 100.0,
                       "detail": "No automation indicators"})

    actions = automation.get("action_count") or 0
    cv = automation.get("interval_cv")
    if actions >= MIN_ACTIONS_FOR_RHYTHM and cv is not None:
        if cv < MIN_HUMAN_INTERVAL_CV:
            # Scale the penalty by how far below human irregularity it sits.
            penalty = 50.0 * (1.0 - cv / MIN_HUMAN_INTERVAL_CV)
            score -= penalty
            detail = (f"Actions spaced too regularly for human input "
                      f"(variation {cv:.2f}, humans exceed {MIN_HUMAN_INTERVAL_CV})")
            reasons.append(detail)
            checks.append({"name": "Interaction rhythm", "score": max(0.0, 100.0 - penalty),
                           "detail": detail})
        else:
            checks.append({"name": "Interaction rhythm", "score": 100.0,
                           "detail": f"Natural irregularity (variation {cv:.2f})"})
    else:
        checks.append({"name": "Interaction rhythm", "score": 100.0,
                       "detail": "Too few actions to judge rhythm"})

    reaction = automation.get("time_to_first_action_ms")
    if reaction is not None and reaction < MIN_HUMAN_REACTION_MS:
        penalty = 30.0
        score -= penalty
        detail = f"Acted {reaction}ms after load -- faster than human reaction time"
        reasons.append(detail)
        checks.append({"name": "Reaction latency", "score": 100.0 - penalty, "detail": detail})

    orphan_clicks = automation.get("clicks_without_precursor") or 0
    if orphan_clicks > 0:
        penalty = min(40.0, orphan_clicks * 15.0)
        score -= penalty
        detail = f"{orphan_clicks} click(s) with no preceding pointer movement or scroll"
        reasons.append(detail)
        checks.append({"name": "Pointer precursor", "score": max(0.0, 100.0 - penalty),
                       "detail": detail})

    pastes = automation.get("pastes_into_sensitive") or 0
    if pastes > 0:
        penalty = min(25.0, pastes * 12.0)
        score -= penalty
        detail = f"{pastes} paste(s) into a sensitive field rather than typed entry"
        reasons.append(detail)
        checks.append({"name": "Credential entry", "score": max(0.0, 100.0 - penalty),
                       "detail": detail})

    return max(0.0, score), reasons, checks
