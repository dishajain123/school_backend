import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

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

    @model_validator(mode="after")
    def validate_parent_registration(self):
        if self.role == RoleEnum.PARENT:
            data = self.submitted_data or {}
            admission = (
                data.get("student_admission_number")
                or data.get("admission_number")
                or data.get("child_admission_number")
            )
            if not isinstance(admission, str) or not admission.strip():
                raise ValueError(
                    "For parent registration, submitted_data.student_admission_number is required"
                )
        if self.role != RoleEnum.SUPERADMIN:
            data = self.submitted_data or {}
            academic_year_id = data.get("academic_year_id")
            if not isinstance(academic_year_id, str) or not academic_year_id.strip():
                raise ValueError(
                    "submitted_data.academic_year_id is required for registration"
                )
        return self


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
