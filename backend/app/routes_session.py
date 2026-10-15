from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.config import DEMO_LOCATIONS, OPERATION_CONFIG, settings
from app.database import get_db
from app.deps import get_current_session, get_current_user
from app.geolocation import lookup as geo_lookup
from app.metrics import emit_decision
from app.models import AuthSession, OperationTrust, RiskEvent, User
from app.net_utils import client_ip
from app.risk_engine import evaluate, suggest_threshold_calibration, trust_vector, update_trust_vector
from app.signals import access_patterns
from app.signals.impossible import record_network
from app.routes_auth import _record_context
from app.phrase_auth import enrolled_samples, score_attempt, valid_attempt
from app.schemas import (
    MfaVerifyRequest,
    MfaVerifyResponse,
    PhraseVerifyRequest,
    PhraseVerifyResponse,
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
    environment = payload.environment.model_dump()

    result = evaluate(
        db=db,
        session=auth_session,
        operation=operation,
        environment=environment,
        automation_signals=payload.automation.model_dump(),
        ip_address=ip,
        geo=geo,
    )

    if result["idle"]:
        # No interaction at all in this interval, so there is no evidence to
        # score. Report the session unchanged rather than writing an audit
        # row for a beat that observed nothing.
        return SessionStatusResponse(
            session_id=auth_session.id,
            operation=operation,
            trust_score=result["trust_score"],
            decision=result["decision"],
            mfa_pending=auth_session.mfa_pending,
            mfa_pending_operation=auth_session.mfa_pending_operation,
            reasons=result["reasons"],
            trust_vector=result["trust_vector"],
            idle=True,
        )

    record_network(db, auth_session.id, ip, datetime.utcnow())

    # Only interactions the engine trusted teach the access profile, so a
    # hijacker's 3am admin burst cannot establish 3am admin bursts as normal.
    if result["decision"] == "allow":
        access_patterns.record(db, user.id, operation, datetime.utcnow(), result["actions"])
        _record_context(db, user.id, payload.environment.device_fingerprint, ip, geo)

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
            family_scores=result["family_scores"],
            trust_score=result["trust_score"],
            decision=result["decision"],
            reasons=result["reasons"],
        )
    )
    db.commit()
    emit_decision(result["decision"])

    weights = result["family_weights"]
    return SessionStatusResponse(
        session_id=auth_session.id,
        operation=operation,
        trust_score=result["trust_score"],
        decision=result["decision"],
        mfa_pending=auth_session.mfa_pending,
        mfa_pending_operation=auth_session.mfa_pending_operation,
        reasons=result["reasons"],
        family_scores=[
            {"name": name, "score": score, "weight": weights[name]}
            for name, score in result["family_scores"].items()
        ],
        context_checks=result["context_checks"],
        trust_vector=result["trust_vector"],
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
        decision=decision,
        mfa_pending=auth_session.mfa_pending,
        mfa_pending_operation=auth_session.mfa_pending_operation,
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


@router.post("/phrase/verify", response_model=PhraseVerifyResponse)
def verify_phrase(
    payload: PhraseVerifyRequest,
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
    user: User = Depends(get_current_user),
):
    """Step-up by re-typing the enrollment phrase, verified biometrically.

    This is the real identity check: a static OTP only proves possession of
    a code, whereas scoring the phrase's per-character rhythm against the
    user's enrolled profile tests whether the person at the keyboard types
    like the enrolled person. Passing re-earns trust for the challenged
    operation only, exactly as the OTP path does."""
    if not auth_session.mfa_pending or not auth_session.mfa_pending_operation:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No step-up challenge pending")

    attempt = payload.timings.model_dump()
    phrase = payload.timings.phrase

    if not valid_attempt(attempt, phrase):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Phrase attempt incomplete -- type the whole phrase without corrections",
        )

    enrolled = enrolled_samples(db, user.id, phrase)
    score, detail = score_attempt(attempt, enrolled)
    threshold = settings.phrase_verify_threshold
    operation = auth_session.mfa_pending_operation

    if score < threshold:
        current = db.query(OperationTrust).filter_by(
            session_id=auth_session.id, operation=operation
        ).first()
        return PhraseVerifyResponse(
            verified=False, phrase_score=round(score, 1), threshold=threshold,
            operation=operation,
            trust_score=current.trust_score if current else None, detail=detail,
        )

    new_score = update_trust_vector(
        db, auth_session, operation,
        evidence=max(OPERATION_CONFIG[operation]["allow_threshold"], 80.0),
    )
    auth_session.mfa_pending = False
    auth_session.mfa_pending_operation = None
    auth_session.last_trust_score = new_score
    db.commit()

    return PhraseVerifyResponse(
        verified=True, phrase_score=round(score, 1), threshold=threshold,
        operation=operation, trust_score=new_score, detail=detail,
    )


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
