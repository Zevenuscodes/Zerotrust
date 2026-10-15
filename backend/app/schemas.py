from typing import Optional, List
from pydantic import BaseModel


class Environment(BaseModel):
    """Machine and browser properties a session is bound to. These are
    sealed at login and re-checked on every beat -- none of them can change
    legitimately while one person uses one browser on one machine."""

    device_fingerprint: str
    canvas_hash: Optional[str] = None
    webgl_hash: Optional[str] = None
    user_agent: Optional[str] = None
    platform: Optional[str] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    color_depth: Optional[int] = None
    hardware_concurrency: Optional[int] = None
    device_memory: Optional[float] = None
    timezone: Optional[str] = None
    timezone_offset_min: Optional[int] = None
    languages: Optional[str] = None
    client_time_ms: Optional[float] = None


class AutomationSignals(BaseModel):
    """Evidence about whether a human is driving the session. Carries only
    aggregate shape -- counts and a regularity ratio -- never keystroke
    content or reconstructable timings."""

    action_count: int = 0
    interval_cv: Optional[float] = None
    mean_interval_ms: Optional[int] = None
    time_to_first_action_ms: Optional[int] = None
    clicks_without_precursor: int = 0
    pastes_into_sensitive: int = 0
    saw_pointer_movement: bool = True
    headless_hints: List[str] = []


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
    environment: Environment
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
    environment: Environment


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    session_id: str
    trust_score: float


class TelemetryRequest(BaseModel):
    environment: Environment
    automation: AutomationSignals
    operation: str = "view"  # one of config.OPERATION_CLASSES
    # demo-only, ignored unless settings.demo_location_enabled (see config)
    simulated_location: Optional[str] = None


class FamilyScore(BaseModel):
    """One signal family's contribution to this evaluation."""

    name: str
    score: float
    weight: float


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
    decision: str  # allow | stepup | terminate
    mfa_pending: bool
    # Which operation raised the pending challenge. A challenge raised on
    # one operation stays pending while the user works on another, so the
    # UI needs to know what to name -- and that a challenge exists at all.
    mfa_pending_operation: Optional[str] = None
    reasons: List[str] = []
    family_scores: List[FamilyScore] = []
    context_checks: List[ContextCheck] = []
    trust_vector: List[OperationTrustEntry] = []
    idle: bool = False  # true if the interval had no interaction at all and was not scored


class MfaVerifyRequest(BaseModel):
    otp: str


class MfaVerifyResponse(BaseModel):
    verified: bool
    trust_score: float
    operation: Optional[str] = None
