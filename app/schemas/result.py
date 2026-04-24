import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator


class ExamCreate(BaseModel):
    name: str
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
    standard_id: uuid.UUID
    academic_year_id: uuid.UUID
    start_date: date
    end_date: date
    created_by: Optional[uuid.UUID] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ExamBulkCreate(BaseModel):
    name: str
    standard_ids: Optional[list[uuid.UUID]] = None
    apply_to_all_standards: bool = False
    academic_year_id: Optional[uuid.UUID] = None
    start_date: date
    end_date: date

    @field_validator("name")
    @classmethod
    def bulk_name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        return v


class ExamBulkCreateResponse(BaseModel):
    created: list[ExamResponse]
    created_count: int
    skipped_standard_ids: list[uuid.UUID]
    skipped_count: int


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

    @model_validator(mode="after")
    def marks_not_above_max(self):
        if self.marks_obtained > self.max_marks:
            raise ValueError("marks_obtained cannot be greater than max_marks")
        return self


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
    report_card_url: Optional[str] = None
    has_report_card: bool = False


class ResultDistributionSubjectItem(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    marks_obtained: float
    max_marks: float
    percentage: float
    grade_letter: Optional[str] = None
    is_published: bool


class ResultDistributionStudentItem(BaseModel):
    student_id: uuid.UUID
    student_name: str
    admission_number: str
    section: Optional[str] = None
    roll_number: Optional[str] = None
    total_obtained: float
    total_max: float
    overall_percentage: float
    report_card_url: Optional[str] = None
    has_report_card: bool = False
    subjects: list[ResultDistributionSubjectItem]


class ResultDistributionResponse(BaseModel):
    exam: ExamResponse
    total_students: int
    items: list[ResultDistributionStudentItem]


class ReportCardResponse(BaseModel):
    url: str


class ReportCardUploadResponse(BaseModel):
    url: str
    uploaded: bool = True
