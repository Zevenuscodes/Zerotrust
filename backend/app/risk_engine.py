"""Risk analysis: four signal families combined into an operation-indexed
trust vector.

Previous versions scored keystroke and mouse dynamics. Measurement killed
that approach: within one real session a user's mean flight time ranged
from 170ms to 866ms, because the features tracked the TEXT being typed at
least as much as the person typing it. A baseline that wide makes every
subsequent sample look normal, and no threshold fixes a feature that
carries no signal.

What replaced it answers sharper questions:

  invariants      Did the machine change under a live session? A CPU core
                  count or GPU renderer cannot change mid-session, so a
                  change is near-proof the token moved machines. Near-zero
                  false positives, no training data needed.

  impossible      Conditions that are not unusual but physically impossible:
                  the same session used from two networks at once,
                  impossible travel, a client clock far from the server's.
                  Binary, so no thresholds to tune.

  automation      Is a human driving this, or a script? This is the realistic
                  abuse of a stolen token, and "is this human" is a far
                  easier question than "which human is this".

  patterns        Learned habits -- which hours this account works, which
                  operations it performs, its usual pace. Still statistical,
                  but on quantities that are stable week to week rather than
                  minute to minute.

The operation-conditioned trust vector is unchanged and is still the point:
trust is a vector T(t), one component per operation class, each decaying at
its own rate. What is new is that the four families are blended with
PER-OPERATION weights -- "admin" leans on session integrity and automation,
"view" tolerates far more -- so the operations differ in what evidence they
care about, not merely in where their thresholds sit.

  T_r(t) = T_r(t-1)*(1-alpha) + alpha*evidence_r(t)
  evidence_r = sum over families f of  w(f,r) * score(f)
"""

import math
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from app.config import (
    OPERATION_CONFIG,
    TRANSITION_MAX_PENALTY,
    TRANSITION_MIN_HISTORY,
    TRANSITION_RARE_FREQUENCY,
)
from app.models import AuthSession, OperationTransition, OperationTrust
from app.signals import access_patterns, automation, impossible, invariants

FAMILIES = ("integrity", "impossible", "automation", "patterns")

# Families whose collapse is near-proof of compromise rather than merely
# unusual: the machine changed, the session is in two places at once, or the
# browser is advertising automation. Trust is capped at the lowest of these,
# because a weighted mean alone lets a catastrophic failure in one family be
# averaged away by the others -- a session with a changed GPU AND a
# webdriver flag still cleared "view" purely because its travel and habits
# looked normal. "patterns" is excluded: it is the one statistical family
# here, and an odd working hour should colour the score, never cap it.
GATING_FAMILIES = ("integrity", "impossible", "automation")


def transition_penalty(
    db: DBSession, user_id: str, last_operation: Optional[str], operation: str
) -> Tuple[float, Optional[str]]:
    """Navigation-sequence check: is this jump rare for this user? Kept from
    the previous engine -- it was the one behavioral signal that did not
    depend on typing."""
    if not last_operation or last_operation == operation:
        return 0.0, None

    total = (
        db.query(func.sum(OperationTransition.count))
        .filter(
            OperationTransition.user_id == user_id,
            OperationTransition.from_operation == last_operation,
        )
        .scalar()
        or 0
    )
    if total < TRANSITION_MIN_HISTORY:
        return 0.0, None

    row = (
        db.query(OperationTransition)
        .filter(
            OperationTransition.user_id == user_id,
            OperationTransition.from_operation == last_operation,
            OperationTransition.to_operation == operation,
        )
        .first()
    )
    freq = (row.count if row else 0) / total
    if freq < TRANSITION_RARE_FREQUENCY:
        penalty = TRANSITION_MAX_PENALTY * (1.0 - freq / TRANSITION_RARE_FREQUENCY)
        return round(penalty, 1), (
            f"Unusual navigation: '{last_operation}' -> '{operation}' is "
            f"{freq * 100:.0f}% of this account's moves from '{last_operation}'"
        )
    return 0.0, None


def _record_transition(db: DBSession, user_id: str, last_operation: Optional[str], operation: str) -> None:
    if not last_operation:
        return
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
        row = OperationTransition(
            user_id=user_id, from_operation=last_operation, to_operation=operation, count=0
        )
        db.add(row)
    row.count += 1


def update_trust_vector(db: DBSession, session: AuthSession, operation: str, evidence: float) -> float:
    """T_r(t) = T_r(t-1)*(1-alpha) + alpha*evidence, with alpha driven by
    elapsed time but floored per operation so every reading counts."""
    cfg = OPERATION_CONFIG[operation]
    row = db.query(OperationTrust).filter_by(session_id=session.id, operation=operation).first()
    now = datetime.utcnow()

    if row is None:
        new_value = evidence
        row = OperationTrust(
            session_id=session.id, operation=operation, trust_score=new_value, updated_at=now
        )
        db.add(row)
    else:
        dt = max((now - row.updated_at).total_seconds(), 0.0)
        alpha = max(1.0 - math.exp(-cfg["decay_rate"] * dt), cfg["min_evidence_weight"])
        new_value = row.trust_score * (1.0 - alpha) + alpha * evidence
        row.trust_score = new_value
        row.updated_at = now

    db.flush()  # session has autoflush off; trust_vector() reads this back
    return float(max(0.0, min(100.0, new_value)))


def trust_vector(db: DBSession, session: AuthSession) -> List[dict]:
    rows = {
        r.operation: r.trust_score
        for r in db.query(OperationTrust).filter_by(session_id=session.id).all()
    }
    result = []
    for op, cfg in OPERATION_CONFIG.items():
        score = rows.get(op, 100.0)
        if score >= cfg["allow_threshold"]:
            decision = "allow"
        elif score >= cfg["stepup_threshold"]:
            decision = "stepup"
        else:
            decision = "terminate"
        result.append({
            "operation": op,
            "trust_score": round(score, 2),
            "decision": decision,
            "allow_threshold": cfg["allow_threshold"],
            "stepup_threshold": cfg["stepup_threshold"],
        })
    return result


def evaluate(
    db: DBSession,
    session: AuthSession,
    operation: str,
    environment: dict,
    automation_signals: dict,
    ip_address: str,
    geo: Optional[Tuple[float, float, str, str]],
) -> dict:
    if operation not in OPERATION_CONFIG:
        operation = "view"

    cfg = OPERATION_CONFIG[operation]
    user_id = session.user_id
    now = datetime.utcnow()
    actions = automation_signals.get("action_count") or 0

    # An interval with no interaction at all carries no evidence about who is
    # present. Scoring it would punish a user for reading the screen, so the
    # session's state is reported unchanged instead -- the same reasoning that
    # applies to any missing signal.
    if actions == 0:
        current = trust_vector(db, session)
        entry = next((v for v in current if v["operation"] == operation), None)
        return {
            "operation": operation,
            "trust_score": entry["trust_score"] if entry else 100.0,
            "decision": entry["decision"] if entry else "allow",
            "family_scores": {}, "reasons": [], "context_checks": [],
            "trust_vector": current, "idle": True,
        }

    integrity_score, integrity_reasons, integrity_checks = invariants.evaluate(
        session.sealed_context or {}, environment
    )
    impossible_score, impossible_reasons, impossible_checks = impossible.evaluate(
        db, user_id, session.id, ip_address, geo, environment, now
    )
    automation_score, automation_reasons, automation_checks = automation.evaluate(automation_signals)
    pattern_score, pattern_reasons, pattern_checks = access_patterns.evaluate(
        db, user_id, operation, now, actions
    )

    t_penalty, t_reason = transition_penalty(db, user_id, session.last_operation, operation)
    reasons = integrity_reasons + impossible_reasons + automation_reasons + pattern_reasons
    checks = integrity_checks + impossible_checks + automation_checks + pattern_checks

    if t_reason:
        reasons.append(t_reason)
        checks.append({"name": "Navigation pattern", "score": max(0.0, 100.0 - t_penalty),
                       "detail": t_reason})
    else:
        checks.append({"name": "Navigation pattern", "score": 100.0,
                       "detail": "Consistent with usual navigation" if session.last_operation
                                 else "First operation this session"})

    family_scores = {
        "integrity": round(integrity_score, 1),
        "impossible": round(impossible_score, 1),
        "automation": round(automation_score, 1),
        "patterns": round(pattern_score, 1),
    }

    # Per-operation weighting: what counts as evidence differs by how
    # sensitive the operation is, not just where its threshold sits.
    weights = cfg["family_weights"]
    weighted = sum(weights[f] * family_scores[f] for f in FAMILIES)
    # Trust cannot exceed the weakest decisive signal, however healthy the
    # rest look. See GATING_FAMILIES.
    gate = min(family_scores[f] for f in GATING_FAMILIES)
    evidence = max(0.0, min(100.0, min(weighted, gate) - t_penalty))

    updated_trust = update_trust_vector(db, session, operation, evidence)
    _record_transition(db, user_id, session.last_operation, operation)
    session.last_operation = operation

    if updated_trust >= cfg["allow_threshold"]:
        decision = "allow"
    elif updated_trust >= cfg["stepup_threshold"]:
        decision = "stepup"
    else:
        decision = "terminate"

    return {
        "operation": operation,
        "family_scores": family_scores,
        "family_weights": weights,
        "evidence_score": round(evidence, 1),
        "trust_score": updated_trust,
        "decision": decision,
        "reasons": reasons,
        "context_checks": checks,
        "actions": actions,
        "trust_vector": trust_vector(db, session),
        "idle": False,
    }


def suggest_threshold_calibration(db: DBSession) -> dict:
    """Starter calibration from the audit log. A frequency heuristic, not an
    expected-loss optimiser: an audit log records what this system chose to
    do, never whether it was right, so a true cost-optimal calibration needs
    labelled incidents that no deployment here has."""
    from app.models import RiskEvent

    suggestions = {}
    for operation, cfg in OPERATION_CONFIG.items():
        events = db.query(RiskEvent).filter(RiskEvent.operation == operation).all()
        if len(events) < 20:
            suggestions[operation] = {
                "status": "insufficient_data",
                "events_seen": len(events),
                "note": "Need more audit-log volume before suggesting a change.",
            }
            continue
        stepups = [e for e in events if e.decision == "stepup"]
        rate = len(stepups) / len(events)
        suggested = dict(cfg)
        if rate > 0.25:
            suggested["stepup_threshold"] = round(cfg["stepup_threshold"] * 0.95, 1)
        suggestions[operation] = {
            "status": "ok",
            "events_seen": len(events),
            "observed_stepup_rate": round(rate, 3),
            "current": cfg,
            "suggested": suggested,
        }
    return suggestions
