import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class HomeworkCreate(BaseModel):
    standard_id: uuid.UUID
    subject_id: uuid.UUID
    description: Optional[str] = None
    date: Optional[date] = None
    academic_year_id: Optional[uuid.UUID] = None

    @field_validator("description", mode="before")
    @classmethod
    def normalize_description(cls, v):
        if v is None:
            return None
        text = str(v).strip()
        return text or None


class HomeworkResponse(BaseModel):
    id: uuid.UUID
    description: str
    file_key: Optional[str] = None
    file_url: Optional[str] = None
    is_submitted: Optional[bool] = None
    date: date
    teacher_id: uuid.UUID
    standard_id: uuid.UUID
    subject_id: uuid.UUID
    academic_year_id: uuid.UUID
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HomeworkListResponse(BaseModel):
    items: list[HomeworkResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class HomeworkSubmissionCreate(BaseModel):
    homework_id: uuid.UUID
    student_id: Optional[uuid.UUID] = None
    text_response: Optional[str] = None

    @field_validator("text_response", mode="before")
    @classmethod
    def normalize_response(cls, v):
        if v is None:
            return None
        text = str(v).strip()
        return text or None

    @model_validator(mode="after")
    def require_text_or_file_placeholder(self):
        # File-based submissions set text_response to empty placeholder in service.
        # Keep schema permissive so multipart/file-only payloads can pass.
        if self.text_response is None:
            self.text_response = ""
        return self


class HomeworkSubmissionReview(BaseModel):
    feedback: Optional[str] = None
    is_approved: Optional[bool] = None

    @field_validator("feedback", mode="before")
    @classmethod
    def normalize_feedback(cls, v):
        if v is None:
            return None
        text = str(v).strip()
        return text or None


class HomeworkSubmissionResponse(BaseModel):
    id: uuid.UUID
    homework_id: uuid.UUID
    student_id: uuid.UUID
    performed_by: uuid.UUID
    text_response: str
    file_key: Optional[str] = None
    file_url: Optional[str] = None
    feedback: Optional[str]
    is_reviewed: bool
    is_approved: bool
    reviewed_by: Optional[uuid.UUID]
    reviewed_at: Optional[datetime]
    school_id: uuid.UUID
    student_admission_number: Optional[str] = None
    student_name: Optional[str] = None
    performer_name: Optional[str] = None
    reviewer_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class HomeworkSubmissionListResponse(BaseModel):
    items: list[HomeworkSubmissionResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
