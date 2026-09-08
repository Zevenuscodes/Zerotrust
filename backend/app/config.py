from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://ztauth:ztauth@localhost:5432/ztauth"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30

    # trust score policy thresholds
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

    class Config:
        env_file = ".env"
        protected_namespaces = ("settings_",)


settings = Settings()
