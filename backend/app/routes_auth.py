from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession

from app.database import get_db
from app.geolocation import lookup as geo_lookup
from app.models import AuthSession, KnownContext, PhraseSample, User
from app.net_utils import client_ip
from app.phrase_auth import valid_attempt
from app.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password
from app.signals import invariants
from app.signals.impossible import record_network

router = APIRouter(prefix="/auth", tags=["auth"])


def _record_context(db: DBSession, user_id: str, device_fingerprint: str, ip: str, geo) -> None:
    known = (
        db.query(KnownContext)
        .filter(
            KnownContext.user_id == user_id,
            KnownContext.device_fingerprint == device_fingerprint,
        )
        .first()
    )
    now = datetime.utcnow()
    if known:
        known.last_seen = now
        known.ip_address = ip
        if geo:
            known.geo_lat, known.geo_lon, known.geo_city, known.geo_country = geo
    else:
        lat, lon, city, country = geo if geo else (None, None, None, None)
        db.add(
            KnownContext(
                user_id=user_id, device_fingerprint=device_fingerprint, ip_address=ip,
                geo_lat=lat, geo_lon=lon, geo_city=city, geo_country=country,
                first_seen=now, last_seen=now,
            )
        )
    db.commit()


def _start_session(db: DBSession, user: User, environment, request: Request) -> AuthSession:
    """Issue a token and bind the session to the machine it was issued to.
    The sealed context is what every later heartbeat is compared against."""
    ip = client_ip(request)
    geo = geo_lookup(ip)
    env = environment.model_dump()
    _record_context(db, user.id, environment.device_fingerprint, ip, geo)

    token, jti = create_access_token(user.id)
    session = AuthSession(
        user_id=user.id, jti=jti, last_trust_score=100.0,
        sealed_context=invariants.seal(env),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    record_network(db, session.id, ip, datetime.utcnow())
    db.commit()
    return token, session


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest, request: Request, db: DBSession = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Username already taken")

    user = User(username=payload.username, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    # Fixed-phrase biometric enrollment for the step-up challenge. Only
    # complete, typo-free attempts are stored, since scoring aligns timings
    # position-by-position.
    for enrollment in payload.phrase_enrollments:
        attempt = enrollment.model_dump()
        if valid_attempt(attempt, enrollment.phrase):
            db.add(PhraseSample(user_id=user.id, phrase=enrollment.phrase, timings=attempt))
    db.commit()

    token, session = _start_session(db, user, payload.environment, request)
    return TokenResponse(access_token=token, session_id=session.id, trust_score=100.0)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DBSession = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    token, session = _start_session(db, user, payload.environment, request)
    return TokenResponse(access_token=token, session_id=session.id, trust_score=100.0)
