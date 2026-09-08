from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.config import settings
from app.database import get_db
from app.deps import get_current_session, get_current_user
from app.geolocation import lookup as geo_lookup
from app.metrics import emit_decision
from app.models import AuthSession, BehaviorSample, RiskEvent, User
from app.net_utils import client_ip
from app.risk_engine import evaluate
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
    geo = geo_lookup(ip)

    result = evaluate(
        db=db,
        user_id=user.id,
        keystroke=payload.keystroke,
        mouse=payload.mouse,
        context=payload.context,
        ip_address=ip,
        geo=geo,
    )

    # Only reinforce the behavior model with samples the risk engine trusted,
    # so an attacker's own telemetry can't poison the legitimate user's baseline.
    if result["decision"] == "allow":
        db.add(
            BehaviorSample(user_id=user.id, sample_type="session", features=result["features"])
        )
        _record_context(db, user.id, payload.context.device_fingerprint, ip, geo)

    auth_session.last_trust_score = result["trust_score"]
    if result["decision"] == "terminate":
        auth_session.status = "terminated"
        auth_session.ended_at = datetime.utcnow()
        auth_session.mfa_pending = False
    elif result["decision"] == "stepup":
        auth_session.mfa_pending = True

    db.add(
        RiskEvent(
            user_id=user.id,
            session_id=auth_session.id,
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
        trust_score=result["trust_score"],
        behavior_score=result["behavior_score"],
        context_score=result["context_score"],
        decision=result["decision"],
        mfa_pending=auth_session.mfa_pending,
        reasons=result["reasons"],
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
        trust_score=auth_session.last_trust_score,
        behavior_score=latest_event.behavior_score if latest_event else 100.0,
        context_score=latest_event.context_score if latest_event else 100.0,
        decision=decision,
        mfa_pending=auth_session.mfa_pending,
        reasons=latest_event.reasons if latest_event else [],
    )


@router.post("/mfa/verify", response_model=MfaVerifyResponse)
def verify_mfa(
    payload: MfaVerifyRequest,
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
):
    if not auth_session.mfa_pending:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No step-up challenge pending")

    if payload.otp != settings.demo_otp:
        return MfaVerifyResponse(verified=False, trust_score=auth_session.last_trust_score)

    auth_session.mfa_pending = False
    auth_session.last_trust_score = max(auth_session.last_trust_score, settings.trust_allow_threshold)
    db.commit()

    return MfaVerifyResponse(verified=True, trust_score=auth_session.last_trust_score)


@router.post("/logout")
def logout(
    db: DBSession = Depends(get_db),
    auth_session: AuthSession = Depends(get_current_session),
):
    auth_session.status = "logged_out"
    auth_session.ended_at = datetime.utcnow()
    db.commit()
    return {"ok": True}
