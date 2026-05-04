import uuid
from pathlib import Path
from typing import Literal, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str

    # JWT
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # MinIO
    MINIO_ENDPOINT: str
    MINIO_ACCESS_KEY: str
    MINIO_SECRET_KEY: str
    MINIO_BUCKET_ASSIGNMENTS: str = "assignments"
    MINIO_BUCKET_SUBMISSIONS: str = "submissions"
    MINIO_BUCKET_TIMETABLES: str = "timetables"
    MINIO_BUCKET_DOCUMENTS: str = "documents"
    MINIO_BUCKET_PROFILES: str = "profiles"
    MINIO_BUCKET_RECEIPTS: str = "receipts"
    MINIO_BUCKET_GALLERY: str = "gallery"
    MINIO_BUCKET_CHAT_FILES: str = "chat-files"

    # SMTP
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_TLS: bool = True

    # SMS
    SMS_API_KEY: Optional[str] = None
    SMS_SENDER_ID: Optional[str] = None
    SMS_BASE_URL: Optional[str] = None

    # App
    APP_NAME: str = "SMS Backend"
    BACKEND_BASE_URL: str = "http://localhost:8000"
    APP_TIMEZONE: str = "Asia/Kolkata"
    # production | staging | development | local — default is strict so undeployed
    # misconfigurations never behave like dev. Set ENVIRONMENT=local (or development)
    # on developer machines. See model_validator on DEBUG.
    ENVIRONMENT: Literal["production", "staging", "development", "local"] = "production"
    # Never enable DEBUG in production/staging: it relaxes startup checks, may expose
    # stack traces to clients, and historically paired with unsafe OTP-in-JSON behavior.
    # DEBUG=true is only accepted when ENVIRONMENT is "local" or "development".
    DEBUG: bool = False
    SQL_ECHO: bool = False
    ALLOWED_ORIGINS: str = "*"
    MINIO_ENABLED: bool = True
    # Only when ENVIRONMENT is local/development: if true, forgot-password may echo
    # the OTP in the JSON body for manual testing. Never enable in staging/production.
    EXPOSE_OTP_HINT_IN_FORGOT_PASSWORD: bool = False
    # If true, each request resolves permission codes from the DB (role → permissions) instead
    # of trusting the JWT list (avoids stale grants until token refresh). One extra query per auth.
    STRICT_RBAC_CHECK: bool = False

    # Single-school: UUID of the school row when token + user have no school_id.
    # Never infer from DB queries (avoids wrong-tenant style bugs if data is wrong).
    DEFAULT_SCHOOL_ID: Optional[str] = None

    @field_validator("DEFAULT_SCHOOL_ID", mode="before")
    @classmethod
    def validate_default_school_id(cls, v):
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return None
        s = str(v).strip()
        try:
            uuid.UUID(s)
        except ValueError as e:
            raise ValueError("DEFAULT_SCHOOL_ID must be a valid UUID") from e
        return s

    @field_validator("DEBUG", "SQL_ECHO", "MINIO_ENABLED", "STRICT_RBAC_CHECK", mode="before")
    @classmethod
    def validate_boolish(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"true", "1", "yes", "on", "debug", "development", "dev"}:
                return True
            if normalized in {"false", "0", "no", "off", "release", "production", "prod"}:
                return False
        return v

    @model_validator(mode="after")
    def validate_debug_allowed_for_environment(self):
        if self.DEBUG and self.ENVIRONMENT not in ("local", "development"):
            raise ValueError(
                "DEBUG=true is not allowed when ENVIRONMENT is "
                f"{self.ENVIRONMENT!r}. DEBUG is for local troubleshooting only "
                "(verbose errors, relaxed startup checks). In production or staging it "
                "must remain false to avoid leaking sensitive data (e.g. OTPs, secrets) "
                "and weakening security guarantees. Set ENVIRONMENT=local or "
                "ENVIRONMENT=development if you need DEBUG=true."
            )
        return self

    @property
    def is_development_environment(self) -> bool:
        return self.ENVIRONMENT in ("local", "development")

    @property
    def include_forgot_password_otp_hint(self) -> bool:
        """Plain OTP in API responses: only when explicitly opted in on a dev environment."""
        return self.is_development_environment and self.EXPOSE_OTP_HINT_IN_FORGOT_PASSWORD

    @property
    def minio_use_ssl(self) -> bool:
        """Local/dev MinIO is often plain HTTP; staging/production typically use TLS."""
        return self.ENVIRONMENT not in ("local", "development")

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        if "postgresql://" in v and "postgresql+asyncpg://" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    model_config = {"env_file": str(ENV_FILE), "case_sensitive": True}


settings = Settings()
