import uuid
from datetime import datetime

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    JSON,
    Boolean,
)
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_uuid)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    behavior_samples = relationship("BehaviorSample", back_populates="user")
    sessions = relationship("AuthSession", back_populates="user")
    risk_events = relationship("RiskEvent", back_populates="user")
    known_contexts = relationship("KnownContext", back_populates="user")


class BehaviorSample(Base):
    """One feature vector captured either at registration (baseline) or during
    a live session, used to train/refresh the per-user IsolationForest model."""

    __tablename__ = "behavior_samples"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sample_type = Column(String, nullable=False)  # "baseline" | "session"
    features = Column(JSON, nullable=False)  # flat dict of numeric features
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="behavior_samples")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    jti = Column(String, unique=True, nullable=False)
    status = Column(String, default="active")  # active | terminated | logged_out
    last_trust_score = Column(Float, default=100.0)
    mfa_pending = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")
    risk_events = relationship("RiskEvent", back_populates="session")


class RiskEvent(Base):
    """Audit log row: one per telemetry evaluation, for the risk-event history
    and the "centralized monitoring" story in the report."""

    __tablename__ = "risk_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_id = Column(String, ForeignKey("auth_sessions.id"), nullable=False)
    behavior_score = Column(Float, nullable=False)
    context_score = Column(Float, nullable=False)
    trust_score = Column(Float, nullable=False)
    decision = Column(String, nullable=False)  # allow | stepup | terminate
    reasons = Column(JSON, default=list)  # list of human-readable reason strings
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="risk_events")
    session = relationship("AuthSession", back_populates="risk_events")


class KnownContext(Base):
    """Per-user history of devices/locations seen, so new-device and
    impossible-travel checks have something to compare against."""

    __tablename__ = "known_contexts"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    device_fingerprint = Column(String, nullable=False)
    ip_address = Column(String, nullable=True)
    geo_lat = Column(Float, nullable=True)
    geo_lon = Column(Float, nullable=True)
    geo_city = Column(String, nullable=True)
    geo_country = Column(String, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="known_contexts")
