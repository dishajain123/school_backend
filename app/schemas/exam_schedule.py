import uuid
from datetime import date, time, datetime
from typing import Optional

from pydantic import BaseModel, field_validator


class ExamSeriesCreate(BaseModel):
    name: str
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class ExamSeriesResponse(BaseModel):
    id: uuid.UUID
    name: str
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    is_published: bool
    created_by: Optional[uuid.UUID] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExamEntryCreate(BaseModel):
    subject_id: uuid.UUID
    exam_date: date
    start_time: time
    duration_minutes: int
    venue: Optional[str] = None

    @field_validator("duration_minutes")
    @classmethod
    def duration_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("Duration must be positive")
        return v


class ExamEntryResponse(BaseModel):
    id: uuid.UUID
    series_id: uuid.UUID
    subject_id: uuid.UUID
    exam_date: date
    start_time: time
    duration_minutes: int
    venue: Optional[str] = None
    is_cancelled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExamScheduleTable(BaseModel):
    series: ExamSeriesResponse
    entries: list[ExamEntryResponse]
