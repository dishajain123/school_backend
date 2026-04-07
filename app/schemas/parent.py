import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field
from app.utils.enums import RelationType, RoleEnum


# ── User sub-schema embedded in parent creation ──────────────────────────────

class ParentUserCreate(BaseModel):
    email: EmailStr
    phone: str = Field(..., max_length=20)
    password: str = Field(..., min_length=8)

    model_config = {"str_strip_whitespace": True}


# ── Create ────────────────────────────────────────────────────────────────────

class ParentCreate(BaseModel):
    user: ParentUserCreate
    occupation: Optional[str] = Field(None, max_length=100)
    relation: RelationType

    model_config = {"str_strip_whitespace": True}


# ── Update ────────────────────────────────────────────────────────────────────

class ParentUpdate(BaseModel):
    occupation: Optional[str] = Field(None, max_length=100)
    relation: Optional[RelationType] = None

    model_config = {"str_strip_whitespace": True}


# ── Nested user info returned with parent ────────────────────────────────────

class ParentUserResponse(BaseModel):
    id: uuid.UUID
    email: Optional[str]
    phone: Optional[str]
    is_active: bool
    profile_photo_key: Optional[str]
    profile_photo_url: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Response ──────────────────────────────────────────────────────────────────

class ParentResponse(BaseModel):
    id: uuid.UUID
    school_id: uuid.UUID
    occupation: Optional[str]
    relation: RelationType
    user: ParentUserResponse
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ParentListResponse(BaseModel):
    items: list[ParentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ── Child (student) summary embedded in children list ────────────────────────

class ChildSummary(BaseModel):
    id: uuid.UUID
    admission_number: str
    section: Optional[str]
    roll_number: Optional[str]
    date_of_birth: Optional[datetime]
    admission_date: Optional[datetime]
    is_promoted: bool
    academic_year_id: Optional[uuid.UUID]
    standard_id: Optional[uuid.UUID]
    user_id: Optional[uuid.UUID]

    model_config = {"from_attributes": True}


class ParentChildrenResponse(BaseModel):
    parent_id: uuid.UUID
    children: list[ChildSummary]
    total: int


class ParentAssignChildrenRequest(BaseModel):
    student_ids: list[uuid.UUID] = Field(default_factory=list)


class ParentLinkChildRequest(BaseModel):
    student_id: Optional[uuid.UUID] = None
    admission_number: Optional[str] = Field(None, min_length=1, max_length=50)
    student_email: Optional[EmailStr] = None
    student_phone: Optional[str] = Field(None, max_length=20)
    student_password: Optional[str] = Field(None, min_length=8)
