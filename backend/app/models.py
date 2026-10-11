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
    a live session, used to train/refresh the per-(user, operation) anomaly
    model. Tagged by `operation` so behavior is baselined separately per
    operation class instead of against one global distribution."""

    __tablename__ = "behavior_samples"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    sample_type = Column(String, nullable=False)  # "baseline" | "session"
    operation = Column(String, nullable=False, default="view")
    features = Column(JSON, nullable=False)  # flat dict of numeric features
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="behavior_samples")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    jti = Column(String, unique=True, nullable=False)
    status = Column(String, default="active")  # active | terminated | logged_out
    last_trust_score = Column(Float, default=100.0)  # mirrors the current operation's trust component
    last_operation = Column(String, nullable=True)  # for the navigation-sequence anomaly check
    mfa_pending = Column(Boolean, default=False)
    mfa_pending_operation = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="sessions")
    risk_events = relationship("RiskEvent", back_populates="session")
    operation_trusts = relationship("OperationTrust", back_populates="session")


class RiskEvent(Base):
    """Audit log row: one per telemetry evaluation, for the risk-event history
    and the "centralized monitoring" story in the report."""

    __tablename__ = "risk_events"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    session_id = Column(String, ForeignKey("auth_sessions.id"), nullable=False)
    operation = Column(String, nullable=False, default="view")
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


class PhraseSample(Base):
    """One attempt at typing the enrollment phrase, stored as per-character
    dwell times and per-digraph flight times. Because every attempt covers
    the same characters in the same order, these line up position-by-position
    and can be compared like-for-like -- which is what makes them carry
    identity, unlike averages over arbitrary free text."""

    __tablename__ = "phrase_samples"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    phrase = Column(String, nullable=False)
    timings = Column(JSON, nullable=False)  # {phrase, dwell_ms[], flight_ms[]}
    created_at = Column(DateTime, default=datetime.utcnow)


class OperationTrust(Base):
    """One component of the trust VECTOR: this session's current trust level
    for one specific operation class, decayed lazily (on each update) using
    that operation's decay rate. An operation with no row yet is treated as
    starting at 100, same as a fresh session's scalar trust used to."""

    __tablename__ = "operation_trust"

    id = Column(String, primary_key=True, default=gen_uuid)
    session_id = Column(String, ForeignKey("auth_sessions.id"), nullable=False)
    operation = Column(String, nullable=False)
    trust_score = Column(Float, nullable=False, default=100.0)
    updated_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("AuthSession", back_populates="operation_trusts")


class OperationTransition(Base):
    """Frequency table of (from_operation -> to_operation) per user, built up
    over the user's own history, so an unusually rare jump (e.g. straight to
    "admin" without the user's typical path through "view") can be scored as
    its own context penalty -- the navigation-sequence signal."""

    __tablename__ = "operation_transitions"

    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    from_operation = Column(String, nullable=False)
    to_operation = Column(String, nullable=False)
    count = Column(Integer, nullable=False, default=0)
