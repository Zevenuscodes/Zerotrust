from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://ztauth:ztauth@localhost:5432/ztauth"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30

    # trust score policy thresholds (legacy global fallback; superseded by
    # OPERATION_CONFIG's per-operation thresholds below)
    trust_allow_threshold: float = 70.0
    trust_stepup_threshold: float = 40.0

    # step-up MFA: static demo OTP so the flow is demoable without a real SMS/email provider
    demo_otp: str = "123456"

    # ModelStore backend: "local" (dev) or "s3" (prod/AWS)
    model_store: str = "local"
    model_store_local_dir: str = "./model_store_data"
    model_store_s3_bucket: str = ""
    model_store_s3_region: str = "us-east-1"

    # optional external IP geolocation lookup (no API key, best-effort, falls back to "unknown")
    geolocation_enabled: bool = True

    # Demo-only: lets the client pick a simulated location from DEMO_LOCATIONS
    # so the impossible-travel check can be shown live in a browser (a browser
    # cannot set X-Forwarded-For, and localhost has no geolocatable IP).
    # DEFAULTS TO FALSE and must stay false anywhere real: a client-controlled
    # location would let an attacker spoof away the travel check entirely.
    # Enabled explicitly in docker-compose.yml for local demos.
    demo_location_enabled: bool = False

    class Config:
        env_file = ".env"
        protected_namespaces = ("settings_",)


settings = Settings()


# Fixed set of demo locations, resolved server-side to a representative public
# IP that the normal geolocation path then looks up. Deliberately a closed
# allow-list rather than an arbitrary client-supplied IP, so even with the
# demo flag on, the blast radius is three known coordinates.
DEMO_LOCATIONS = {
    "mumbai": "49.36.0.1",
    "london": "81.2.69.142",
    "new_york": "8.8.8.8",
}


# --- Operation-conditioned trust model -------------------------------------
#
# Novelty pivot: instead of one scalar trust score with one global behavioral
# baseline per user, trust is tracked as a VECTOR -- one component per
# operation class -- each backed by its own behavioral baseline, decay rate,
# context weights, and decision thresholds. A device/location anomaly that's
# a minor ding on "view" is a much bigger ding on "admin"; typing behavior
# while composing a report is not the same distribution as typing behavior
# while deleting records, so scoring them against one shared baseline is
# exactly where false positives/negatives concentrate on the operations that
# matter most.
#
# decay_rate (lambda, per second) sets how "sticky" trust is for that
# operation class: T_r(t) = T_r(t-1)*e^(-lambda*dt) + (1-e^(-lambda*dt))*evidence
# A small lambda (view) means old trust persists for minutes; a large lambda
# (admin) means trust must be re-earned almost every heartbeat.
#
# device_weight / location_weight are the per-operation versions of the
# fixed -30 / -50 context penalties the original scalar model used for every
# operation alike.
#
# allow_threshold / stepup_threshold replace the single global
# trust_allow_threshold / trust_stepup_threshold with per-operation values --
# an unfamiliar device is tolerated on "view" but not on "admin".
#
# These numeric defaults are project design choices (same status as the
# original 0.6/0.4 behavior/context split), not values derived from a
# calibration run -- see risk_engine.suggest_threshold_calibration() for a
# starter, audit-log-driven method to tune them, per the "no concrete
# calibration method" gap this model is meant to close.
OPERATION_CLASSES = ["view", "edit", "admin"]

OPERATION_CONFIG = {
    "view": {
        "decay_rate": 0.006,  # ~115s half-life -- slow to change
        "device_weight": 10.0,
        "location_weight": 15.0,
        "allow_threshold": 55.0,
        "stepup_threshold": 35.0,
    },
    "edit": {
        "decay_rate": 0.02,  # ~35s half-life
        "device_weight": 25.0,
        "location_weight": 35.0,
        "allow_threshold": 65.0,
        "stepup_threshold": 45.0,
    },
    "admin": {
        "decay_rate": 0.06,  # ~11.5s half-life -- must be re-earned almost every heartbeat
        "device_weight": 45.0,
        "location_weight": 60.0,
        "allow_threshold": 75.0,
        "stepup_threshold": 55.0,
    },
}

# operation-sequence anomaly (Section 5's "navigation flow" signal, actually
# used): a transition seen fewer than this fraction of the user's times
# leaving `from_operation` is treated as an unusual jump (e.g. straight to
# "admin" without the user's usual path through "view").
TRANSITION_MIN_HISTORY = 5
TRANSITION_RARE_FREQUENCY = 0.1
TRANSITION_MAX_PENALTY = 20.0
