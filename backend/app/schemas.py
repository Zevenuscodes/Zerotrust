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


class SessionStatusResponse(BaseModel):
    session_id: str
    trust_score: float
    behavior_score: float
    context_score: float
    decision: str  # allow | stepup | terminate
    mfa_pending: bool
    reasons: List[str] = []


class MfaVerifyRequest(BaseModel):
    otp: str


class MfaVerifyResponse(BaseModel):
    verified: bool
    trust_score: float
