from typing import Optional, List, Dict
from pydantic import BaseModel


class KeystrokeSample(BaseModel):
    key_count: int
    mean_dwell_ms: float
    std_dwell_ms: float
    mean_flight_ms: float
    std_flight_ms: float


class MouseSample(BaseModel):
    point_count: int
    mean_velocity: float
    std_velocity: float
    mean_acceleration: float
    direction_changes: int


class ContextSample(BaseModel):
    device_fingerprint: str
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    timezone: Optional[str] = None


class RegisterRequest(BaseModel):
    username: str
    password: str
    keystroke: KeystrokeSample
    mouse: MouseSample
    context: ContextSample


class LoginRequest(BaseModel):
    username: str
    password: str
    keystroke: KeystrokeSample
    mouse: MouseSample
    context: ContextSample


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    session_id: str
    trust_score: float


class TelemetryRequest(BaseModel):
    keystroke: KeystrokeSample
    mouse: MouseSample
    context: ContextSample
    operation: str = "view"  # one of config.OPERATION_CLASSES
    # demo-only, ignored unless settings.demo_location_enabled (see config)
    simulated_location: Optional[str] = None


class FeatureScore(BaseModel):
    """Per-parameter breakdown of the behavior score: how far this one
    feature sits from the user's own historical baseline."""

    name: str
    value: float
    baseline_mean: Optional[float] = None
    z_score: float
    score: float


class ContextCheck(BaseModel):
    """Per-parameter breakdown of the context score."""

    name: str
    score: float
    detail: str


class OperationTrustEntry(BaseModel):
    """One component of the trust vector T(t) -- this operation's current
    trust level plus the thresholds it's judged against."""

    operation: str
    trust_score: float
    decision: str
    allow_threshold: float
    stepup_threshold: float


class SessionStatusResponse(BaseModel):
    session_id: str
    operation: str = "view"
    trust_score: float
    behavior_score: float
    context_score: float
    decision: str  # allow | stepup | terminate
    mfa_pending: bool
    reasons: List[str] = []
    feature_scores: List[FeatureScore] = []
    context_checks: List[ContextCheck] = []
    trust_vector: List[OperationTrustEntry] = []
    bootstrapped: bool = False  # true if this operation didn't have enough of its own history yet
    idle: bool = False  # true if this heartbeat had no keyboard/mouse activity and wasn't scored


class MfaVerifyRequest(BaseModel):
    otp: str


class MfaVerifyResponse(BaseModel):
    verified: bool
    trust_score: float
    operation: Optional[str] = None
