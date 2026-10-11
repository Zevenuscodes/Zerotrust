from typing import Optional, List
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


class PhraseTimings(BaseModel):
    """Per-character timings for one attempt at the enrollment phrase.
    Index i of each list corresponds to phrase[i]; flight_ms[0] is null
    since there is no preceding key."""

    phrase: str
    dwell_ms: List[Optional[float]]
    flight_ms: List[Optional[float]] = []


class RegisterRequest(BaseModel):
    username: str
    password: str
    keystroke: KeystrokeSample
    mouse: MouseSample
    context: ContextSample
    # Repeated attempts at the fixed phrase, used to build the biometric
    # profile that the step-up challenge later verifies against.
    phrase_enrollments: List[PhraseTimings] = []


class PhraseVerifyRequest(BaseModel):
    timings: PhraseTimings


class PhraseVerifyResponse(BaseModel):
    verified: bool
    phrase_score: float
    threshold: float
    operation: Optional[str] = None
    trust_score: Optional[float] = None
    detail: dict = {}


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
    value: Optional[float] = None
    baseline_mean: Optional[float] = None
    z_score: float
    score: Optional[float] = None
    # False when this sample observed no events for the feature's modality
    # (e.g. mouse features while the user only typed). Such features are
    # excluded from scoring rather than compared as if a zero was measured.
    observed: bool = True


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
    # Which operation raised the pending challenge. A challenge raised on
    # one operation stays pending while the user works on another, so the
    # UI needs to know what to name -- and that a challenge exists at all.
    mfa_pending_operation: Optional[str] = None
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
