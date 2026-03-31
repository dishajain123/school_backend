import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class AssignmentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    standard_id: uuid.UUID
    subject_id: uuid.UUID
    due_date: date
    academic_year_id: uuid.UUID

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty")
        return v


class AssignmentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[date] = None
    is_active: Optional[bool] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Title cannot be empty")
        return v


class AssignmentResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: Optional[str] = None
    teacher_id: uuid.UUID
    standard_id: uuid.UUID
    subject_id: uuid.UUID
    due_date: date
    file_key: Optional[str] = None
    file_url: Optional[str] = None
    is_active: bool
    academic_year_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssignmentListResponse(BaseModel):
    items: list[AssignmentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int