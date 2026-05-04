"""Settings validation for ENVIRONMENT / DEBUG / OTP hint safety."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

_MINIMAL = dict(
    DATABASE_URL="postgresql+asyncpg://u:p@localhost:5432/db",
    SECRET_KEY="x" * 32,
    MINIO_ENDPOINT="localhost:9000",
    MINIO_ACCESS_KEY="a",
    MINIO_SECRET_KEY="b",
)


def test_debug_true_rejected_when_environment_production():
    with pytest.raises(ValidationError, match="DEBUG=true"):
        Settings(**_MINIMAL, ENVIRONMENT="production", DEBUG=True)


def test_debug_true_rejected_when_environment_staging():
    with pytest.raises(ValidationError, match="DEBUG=true"):
        Settings(**_MINIMAL, ENVIRONMENT="staging", DEBUG=True)


def test_debug_true_allowed_for_local():
    s = Settings(**_MINIMAL, ENVIRONMENT="local", DEBUG=True)
    assert s.DEBUG is True
    assert s.is_development_environment is True


def test_forgot_password_otp_hint_requires_dev_environment_and_explicit_flag():
    s = Settings(**_MINIMAL, ENVIRONMENT="production", EXPOSE_OTP_HINT_IN_FORGOT_PASSWORD=True)
    assert s.include_forgot_password_otp_hint is False

    s2 = Settings(**_MINIMAL, ENVIRONMENT="local", EXPOSE_OTP_HINT_IN_FORGOT_PASSWORD=False)
    assert s2.include_forgot_password_otp_hint is False

    s3 = Settings(**_MINIMAL, ENVIRONMENT="local", EXPOSE_OTP_HINT_IN_FORGOT_PASSWORD=True)
    assert s3.include_forgot_password_otp_hint is True
