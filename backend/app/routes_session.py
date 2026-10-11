from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.config import DEMO_LOCATIONS, OPERATION_CONFIG, settings
from app.database import get_db
from app.deps import get_current_session, get_current_user
from app.geolocation import lookup as geo_lookup
from app.metrics import emit_decision
from app.models import AuthSession, BehaviorSample, OperationTrust, RiskEvent, User
from app.net_utils import client_ip
from app.risk_engine import evaluate, suggest_threshold_calibration, trust_vector, update_trust_vector
from app.routes_auth import _record_context
from app.schemas import (
    MfaVerifyRequest,
    MfaVerifyResponse,
    SessionStatusResponse,
    TelemetryRequest,
)

router = APIRouter(prefix="/session", tags=["session"])


@router.post("/telemetry", response_model=SessionStatusResponse)
def submit_telemetry(
    payload: TelemetryRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
    user: User = Depends(get_current_user),
):
    ip = client_ip(request)
    # Demo-only override: swap in a known public IP for a picked city so the
    # impossible-travel check is demonstrable from a browser. Off unless
    # explicitly enabled, and only ever resolves to the fixed allow-list.
    if settings.demo_location_enabled and payload.simulated_location in DEMO_LOCATIONS:
        ip = DEMO_LOCATIONS[payload.simulated_location]
    geo = geo_lookup(ip)
    operation = payload.operation if payload.operation in OPERATION_CONFIG else "view"

    result = evaluate(
        db=db,
        session=auth_session,
        operation=operation,
        keystroke=payload.keystroke,
        mouse=payload.mouse,
        context=payload.context,
        ip_address=ip,
        geo=geo,
    )

    if result["idle"]:
        # No keyboard/mouse activity since the last heartbeat -- nothing was
        # scored, so nothing about the session changes. Report current state
        # as-is rather than writing an audit row for a heartbeat that did
        # nothing.
        return SessionStatusResponse(
            session_id=auth_session.id,
            operation=operation,
            trust_score=result["trust_score"],
            behavior_score=result["behavior_score"],
            context_score=result["context_score"],
            decision=result["decision"],
            mfa_pending=auth_session.mfa_pending,
            reasons=result["reasons"],
            trust_vector=result["trust_vector"],
            idle=True,
        )

    # Only reinforce the behavior model with samples the risk engine trusted,
    # so an attacker's own telemetry can't poison the legitimate user's
    # baseline -- and it's tagged with the operation so it only ever
    # reinforces that operation's own baseline, not the others.
    #
    # Gated on the BEHAVIOR score, not just the final decision: the decision
    # also reflects context and carried-over trust, so a sample whose typing
    # was plainly anomalous could still land on "allow" and be learned as
    # normal -- which is exactly how a run of bad samples was observed
    # dragging a baseline toward itself until the anomaly disappeared.
    behavior_trusted = result["behavior_score"] >= settings.learn_min_behavior_score
    if result["decision"] == "allow" and behavior_trusted:
        db.add(
            BehaviorSample(
                user_id=user.id, sample_type="session", operation=operation, features=result["features"]
            )
        )
        _record_context(db, user.id, payload.context.device_fingerprint, ip, geo)

    auth_session.last_trust_score = result["trust_score"]
    if result["decision"] == "terminate":
        auth_session.status = "terminated"
        auth_session.ended_at = datetime.utcnow()
        auth_session.mfa_pending = False
        auth_session.mfa_pending_operation = None
    elif result["decision"] == "stepup":
        auth_session.mfa_pending = True
        auth_session.mfa_pending_operation = operation

    db.add(
        RiskEvent(
            user_id=user.id,
            session_id=auth_session.id,
            operation=operation,
            behavior_score=result["behavior_score"],
            context_score=result["context_score"],
            trust_score=result["trust_score"],
            decision=result["decision"],
            reasons=result["reasons"],
        )
    )
    db.commit()
    emit_decision(result["decision"])

    return SessionStatusResponse(
        session_id=auth_session.id,
        operation=operation,
        trust_score=result["trust_score"],
        behavior_score=result["behavior_score"],
        context_score=result["context_score"],
        decision=result["decision"],
        mfa_pending=auth_session.mfa_pending,
        reasons=result["reasons"],
        feature_scores=result["feature_scores"],
        context_checks=result["context_checks"],
        trust_vector=result["trust_vector"],
        bootstrapped=result["bootstrapped"],
    )


@router.get("/status", response_model=SessionStatusResponse)
def get_status(
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
):
    latest_event = (
        db.query(RiskEvent)
        .filter(RiskEvent.session_id == auth_session.id)
        .order_by(RiskEvent.created_at.desc())
        .first()
    )
    decision = latest_event.decision if latest_event else "allow"
    return SessionStatusResponse(
        session_id=auth_session.id,
        operation=latest_event.operation if latest_event else "view",
        trust_score=auth_session.last_trust_score,
        behavior_score=latest_event.behavior_score if latest_event else 100.0,
        context_score=latest_event.context_score if latest_event else 100.0,
        decision=decision,
        mfa_pending=auth_session.mfa_pending,
        reasons=latest_event.reasons if latest_event else [],
        trust_vector=trust_vector(db, auth_session),
    )


@router.post("/mfa/verify", response_model=MfaVerifyResponse)
def verify_mfa(
    payload: MfaVerifyRequest,
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
):
    if not auth_session.mfa_pending or not auth_session.mfa_pending_operation:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No step-up challenge pending")

    operation = auth_session.mfa_pending_operation

    if payload.otp != settings.demo_otp:
        current = db.query(OperationTrust).filter_by(session_id=auth_session.id, operation=operation).first()
        return MfaVerifyResponse(
            verified=False, trust_score=current.trust_score if current else 0.0, operation=operation
        )

    # Verifying re-earns trust for THIS operation only -- it does not bump the
    # other components of the vector, which is exactly the point of the model:
    # trust never transfers from a low-sensitivity action to a high-sensitivity one.
    allow_threshold = OPERATION_CONFIG[operation]["allow_threshold"]
    new_score = update_trust_vector(db, auth_session, operation, evidence=max(allow_threshold, 80.0))

    auth_session.mfa_pending = False
    auth_session.mfa_pending_operation = None
    auth_session.last_trust_score = new_score
    db.commit()

    return MfaVerifyResponse(verified=True, trust_score=new_score, operation=operation)


@router.get("/calibration")
def get_calibration(
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
):
    """Audit-log-driven threshold suggestions per operation. See
    risk_engine.suggest_threshold_calibration for what this does and does
    not claim to be."""
    return suggest_threshold_calibration(db)


@router.post("/logout")
def logout(
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
):
    auth_session.status = "logged_out"
    auth_session.ended_at = datetime.utcnow()
    db.commit()
    return {"ok": True}
