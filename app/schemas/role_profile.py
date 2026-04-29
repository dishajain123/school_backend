# app/schemas/role_profile.py

import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


class StudentProfileCreate(BaseModel):
    user_id: uuid.UUID
    parent_id: uuid.UUID
    custom_admission_number: Optional[str] = None
    date_of_birth: Optional[date] = None
    admission_date: Optional[date] = None
    standard_id: Optional[uuid.UUID] = None
    section: Optional[str] = Field(None, max_length=10)

    model_config = {"str_strip_whitespace": True}


class TeacherProfileCreate(BaseModel):
    user_id: uuid.UUID
    custom_employee_id: Optional[str] = None
    join_date: Optional[date] = None
    specialization: Optional[str] = Field(None, max_length=100)

    model_config = {"str_strip_whitespace": True}


class ParentProfileCreate(BaseModel):
    user_id: uuid.UUID
    custom_parent_code: Optional[str] = None
    occupation: Optional[str] = Field(None, max_length=100)
    relation: str = Field(default="GUARDIAN", max_length=20)

    model_config = {"str_strip_whitespace": True}


class StudentProfileResponse(BaseModel):
    student_id: uuid.UUID
    user_id: uuid.UUID
    admission_number: str
    is_identifier_custom: bool
    identifier_issued_at: Optional[datetime]
    date_of_birth: Optional[date]
    admission_date: Optional[date]
    standard_id: Optional[uuid.UUID]
    section: Optional[str]
    profile_status: str = "ACTIVE"

    model_config = {"from_attributes": True}


class TeacherProfileResponse(BaseModel):
    teacher_id: uuid.UUID
    user_id: uuid.UUID
    employee_id: str
    is_identifier_custom: bool
    identifier_issued_at: Optional[datetime]
    join_date: Optional[date]
    specialization: Optional[str]
    profile_status: str = "ACTIVE"

    model_config = {"from_attributes": True}


class ParentProfileResponse(BaseModel):
    parent_id: uuid.UUID
    user_id: uuid.UUID
    parent_code: str
    is_identifier_custom: bool
    identifier_issued_at: Optional[datetime]
    occupation: Optional[str]
    relation: str
    profile_status: str = "ACTIVE"

    model_config = {"from_attributes": True}


class RoleProfileListResponse(BaseModel):
    items: list[dict]
    total: int
    page: int
    page_size: int
    total_pages: int


class IdentifierConfigResponse(BaseModel):
    identifier_type: str
    format_template: str
    sequence_padding: int
    reset_yearly: bool
    is_locked: bool
    prefix: Optional[str] = None
    preview_next: Optional[str] = None
    warning: Optional[str] = None


class IdentifierConfigUpsertRequest(BaseModel):
    identifier_type: str
    format_template: str = Field(..., min_length=1, max_length=100)
    sequence_padding: int = Field(..., ge=1, le=12)
    reset_yearly: bool
    prefix: Optional[str] = Field(None, max_length=20)
