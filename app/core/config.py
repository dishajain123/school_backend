from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


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
    DEBUG: bool = False
    ALLOWED_ORIGINS: str = "*"

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        if "postgresql://" in v and "postgresql+asyncpg://" not in v:
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()