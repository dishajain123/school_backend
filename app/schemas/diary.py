import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class DiaryCreate(BaseModel):
    standard_id: uuid.UUID
    subject_id: uuid.UUID
    topic_covered: str
    homework_note: Optional[str] = None
    date: Optional[date] = None
    academic_year_id: Optional[uuid.UUID] = None

    @field_validator("topic_covered")
    @classmethod
    def topic_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Topic covered cannot be empty")
        return v

    @field_validator("academic_year_id", mode="before")
    @classmethod
    def empty_year_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("date", mode="before")
    @classmethod
    def empty_date_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and not v.strip():
            return None
        return v


class DiaryResponse(BaseModel):
    id: uuid.UUID
    topic_covered: str
    homework_note: Optional[str] = None
    date: date
    teacher_id: uuid.UUID
    standard_id: uuid.UUID
    subject_id: uuid.UUID
    academic_year_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiaryListResponse(BaseModel):
    items: list[DiaryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
