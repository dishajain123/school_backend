import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class SubmissionCreate(BaseModel):
    assignment_id: uuid.UUID
    student_id: uuid.UUID
    text_response: Optional[str] = None


class SubmissionGrade(BaseModel):
    grade: str
    feedback: Optional[str] = None

    @field_validator("grade")
    @classmethod
    def grade_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Grade cannot be empty")
        return v


class SubmissionResponse(BaseModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    student_id: uuid.UUID
    performed_by: uuid.UUID
    submitted_at: datetime
    file_key: Optional[str] = None
    file_url: Optional[str] = None
    text_response: Optional[str] = None
    grade: Optional[str] = None
    feedback: Optional[str] = None
    is_graded: bool
    is_late: bool
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SubmissionListResponse(BaseModel):
    items: list[SubmissionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int