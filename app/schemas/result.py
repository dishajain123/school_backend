import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.utils.enums import ExamType


class ExamCreate(BaseModel):
    name: str
    exam_type: ExamType
    standard_id: uuid.UUID
    academic_year_id: Optional[uuid.UUID] = None
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class ExamResponse(BaseModel):
    id: uuid.UUID
    name: str
    exam_type: ExamType
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    start_date: date
    end_date: date
    created_by: Optional[uuid.UUID] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResultEntryCreate(BaseModel):
    student_id: uuid.UUID
    subject_id: uuid.UUID
    marks_obtained: float
    max_marks: float

    @field_validator("marks_obtained")
    @classmethod
    def marks_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Marks cannot be negative")
        return v

    @field_validator("max_marks")
    @classmethod
    def max_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Max marks must be positive")
        return v


class ResultBulkCreate(BaseModel):
    exam_id: uuid.UUID
    entries: list[ResultEntryCreate]


class ResultEntryResponse(BaseModel):
    id: uuid.UUID
    exam_id: uuid.UUID
    student_id: uuid.UUID
    subject_id: uuid.UUID
    marks_obtained: float
    max_marks: float
    percentage: float
    grade_id: Optional[uuid.UUID] = None
    is_published: bool
    entered_by: Optional[uuid.UUID] = None
    entered_at: datetime
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResultListResponse(BaseModel):
    items: list[ResultEntryResponse]
    total: int


class ReportCardResponse(BaseModel):
    url: str
