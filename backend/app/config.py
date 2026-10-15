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

    # A sample is only folded back into the behavioral baseline if its own
    # behavior score clears this, independently of the final allow/stepup
    # decision (which also reflects context and accumulated trust).
    learn_min_behavior_score: float = 70.0

    # Fixed-phrase step-up challenge. The phrase is typed repeatedly at
    # registration to build a per-character timing profile; a later attempt
    # must score at least this to pass. Tune with
    # backend/tests/eval_accuracy.py, which reports FAR/FRR/EER for a given
    # threshold rather than leaving it guessed at.
    phrase_enrollment_count: int = 3
    # Placed midway through the observed separation rather than guessed.
    # Against simulated typists (backend/tests/test_phrase_separation.py)
    # genuine attempts score 84-87 and impostors 48-71 -- including one with
    # the same average typing speed but a different per-character signature,
    # which plain averaging would miss entirely. 78 sits in that 71-84 gap,
    # giving FRR 0% / FAR 0% there; at 70 the matching-speed impostor got
    # through 1 attempt in 4.
    # Real users vary more than a simulation, so recalibrate on real
    # genuine-vs-impostor data with backend/tests/eval_accuracy.py before
    # treating this as a validated number.
    phrase_verify_threshold: float = 78.0

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

#
# min_evidence_weight is the floor on how much a fresh reading counts, no
# matter how little time has passed. Without it the decay term alone decides:
# with dt near zero, e^(-lambda*dt) is ~1 and a new observation contributes
# essentially NOTHING, so trust freezes; even at a 12s heartbeat, "view"
# absorbed only ~7% of each reading and barely moved while behavior swung
# from 0 to 93. The floor keeps every observation meaningful while the decay
# rates still set how much history each operation carries between readings.
#
# family_weights is what makes each operation care about DIFFERENT evidence,
# not merely apply a different threshold to the same number. Reading a page
# can tolerate an odd hour or an unfamiliar rhythm; an admin action leans
# almost entirely on whether the session is still bound to the machine it
# was issued to and whether a human is driving it. Each row sums to 1.
OPERATION_CONFIG = {
    "view": {
        "decay_rate": 0.006,  # ~115s half-life -- slow to change
        "min_evidence_weight": 0.25,
        "allow_threshold": 55.0,
        "stepup_threshold": 35.0,
        "family_weights": {
            "integrity": 0.35,
            "impossible": 0.25,
            "automation": 0.20,
            "patterns": 0.20,
        },
    },
    "edit": {
        "decay_rate": 0.02,  # ~35s half-life
        "min_evidence_weight": 0.4,
        "allow_threshold": 65.0,
        "stepup_threshold": 45.0,
        "family_weights": {
            "integrity": 0.40,
            "impossible": 0.25,
            "automation": 0.25,
            "patterns": 0.10,
        },
    },
    "admin": {
        "decay_rate": 0.06,  # ~11.5s half-life -- must be re-earned almost every heartbeat
        "min_evidence_weight": 0.6,
        "allow_threshold": 75.0,
        "stepup_threshold": 55.0,
        "family_weights": {
            "integrity": 0.45,
            "impossible": 0.25,
            "automation": 0.25,
            "patterns": 0.05,
        },
    },
}

# operation-sequence anomaly (Section 5's "navigation flow" signal, actually
# used): a transition seen fewer than this fraction of the user's times
# leaving `from_operation` is treated as an unusual jump (e.g. straight to
# "admin" without the user's usual path through "view").
TRANSITION_MIN_HISTORY = 5
TRANSITION_RARE_FREQUENCY = 0.1
TRANSITION_MAX_PENALTY = 20.0
