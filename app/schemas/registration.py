import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field

from app.utils.enums import RegistrationSource, RoleEnum, UserStatus


class RegistrationCreateRequest(BaseModel):
    full_name: Optional[str] = Field(None, max_length=255)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=20)
    password: str = Field(..., min_length=8)
    role: RoleEnum
    school_id: Optional[uuid.UUID] = None
    submitted_data: Optional[dict[str, Any]] = None

    model_config = {"str_strip_whitespace": True}


class RegistrationResponse(BaseModel):
    user_id: uuid.UUID
    full_name: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    role: RoleEnum
    school_id: Optional[uuid.UUID]
    status: UserStatus
    registration_source: RegistrationSource
    created_at: datetime


class RegistrationValidationSummary(BaseModel):
    issues: list[dict[str, Any]]
    duplicates: list[dict[str, Any]]
