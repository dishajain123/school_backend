import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ── Nested user creation ──────────────────────────────────────────────────────

class TeacherUserCreate(BaseModel):
    email: EmailStr
    phone: str = Field(..., max_length=20)
    password: str = Field(..., min_length=8)

    model_config = {"str_strip_whitespace": True}


# ── Create ────────────────────────────────────────────────────────────────────

class TeacherCreate(BaseModel):
    user: TeacherUserCreate
    employee_code: str = Field(..., max_length=50)
    join_date: Optional[date] = None
    specialization: Optional[str] = Field(None, max_length=100)
    academic_year_id: Optional[uuid.UUID] = None

    model_config = {"str_strip_whitespace": True}


# ── Update ────────────────────────────────────────────────────────────────────

class TeacherUpdate(BaseModel):
    employee_code: Optional[str] = Field(None, max_length=50)
    join_date: Optional[date] = None
    specialization: Optional[str] = Field(None, max_length=100)
    academic_year_id: Optional[uuid.UUID] = None

    model_config = {"str_strip_whitespace": True}


# ── Nested user info returned with teacher ───────────────────────────────────

class TeacherUserResponse(BaseModel):
    id: uuid.UUID
    email: Optional[str]
    phone: Optional[str]
    is_active: bool
    profile_photo_key: Optional[str]
    profile_photo_url: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Response ──────────────────────────────────────────────────────────────────

class TeacherResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID]
    employee_code: str
    join_date: Optional[date]
    specialization: Optional[str]
    user: TeacherUserResponse
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TeacherListResponse(BaseModel):
    items: list[TeacherResponse]
    total: int
    page: int
    page_size: int
    total_pages: int