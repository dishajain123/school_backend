import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field, model_validator


class AcademicYearCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=20, examples=["2024-25"])
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_dates(self) -> "AcademicYearCreate":
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class AcademicYearUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=20)
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    @model_validator(mode="after")
    def validate_dates(self) -> "AcademicYearUpdate":
        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                raise ValueError("end_date must be after start_date")
        return self


class AcademicYearResponse(BaseModel):
    id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    is_active: bool
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcademicYearListResponse(BaseModel):
    items: list[AcademicYearResponse]
    total: int


class AcademicStructureValidation(BaseModel):
    """Result of completeness check before activation."""

    is_valid: bool
    total_standards: int
    standards_with_subjects: int
    standards_without_subjects: list[str]
    total_sections: int
    standards_without_sections: list[str]
    warnings: list[str]
    errors: list[str]


class AcademicStructureCopyRequest(BaseModel):
    source_year_id: uuid.UUID
    target_year_id: uuid.UUID
    copy_standards: bool = True
    copy_subjects: bool = True
    copy_sections: bool = True
    copy_grade_master: bool = False


class AcademicStructureCopyResponse(BaseModel):
    source_year_name: str
    target_year_name: str
    standards_copied: int
    subjects_copied: int
    sections_copied: int
    skipped_duplicates: int
    warnings: list[str]


class BulkStandardCreate(BaseModel):
    academic_year_id: uuid.UUID
    standards: list[dict]


class BulkStandardResponse(BaseModel):
    created: int
    skipped: int
    items: list[dict]
