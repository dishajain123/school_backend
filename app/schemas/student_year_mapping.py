# app/schemas/student_year_mapping.py

import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.enums import EnrollmentStatus


class StudentYearMappingCreate(BaseModel):
    student_id: uuid.UUID
    academic_year_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: Optional[uuid.UUID] = None
    roll_number: Optional[str] = Field(None, max_length=20)
    joined_on: Optional[date] = None

    model_config = {"str_strip_whitespace": True}


class StudentYearMappingUpdate(BaseModel):
    standard_id: Optional[uuid.UUID] = None
    section_id: Optional[uuid.UUID] = None
    roll_number: Optional[str] = Field(None, max_length=20)
    joined_on: Optional[date] = None


class StudentExitRequest(BaseModel):
    """Mark a student as LEFT or TRANSFERRED for the current year."""
    status: EnrollmentStatus  # must be LEFT or TRANSFERRED
    left_on: date
    exit_reason: str = Field(..., min_length=3, max_length=500)


class StudentYearMappingResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    school_id: uuid.UUID
    academic_year_id: uuid.UUID
    standard_id: uuid.UUID
    section_id: Optional[uuid.UUID]
    section_name: Optional[str]
    roll_number: Optional[str]
    status: EnrollmentStatus
    joined_on: Optional[date]
    left_on: Optional[date]
    exit_reason: Optional[str]

    # Nested detail
    student_name: Optional[str] = None
    admission_number: Optional[str] = None
    standard_name: Optional[str] = None
    academic_year_name: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClassRosterResponse(BaseModel):
    """Full roster for a class+section+year"""
    academic_year_id: uuid.UUID
    academic_year_name: str
    standard_id: uuid.UUID
    standard_name: str
    section_name: Optional[str]
    total_enrolled: int
    active_count: int
    left_count: int
    mappings: list[StudentYearMappingResponse]


class RollNumberAssignRequest(BaseModel):
    """Bulk roll number assignment for a section"""
    standard_id: uuid.UUID
    section_id: uuid.UUID
    academic_year_id: uuid.UUID
    policy: str = "AUTO_ALPHA"  # AUTO_SEQ | AUTO_ALPHA | MANUAL
    # For MANUAL: list of {student_id, roll_number}
    manual_assignments: Optional[list[dict]] = None


class ParentStudentLinkCreate(BaseModel):
    parent_id: uuid.UUID
    student_id: uuid.UUID
    relation: Optional[str] = "GUARDIAN"
    is_primary: bool = False


class ParentStudentLinkResponse(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID
    student_id: uuid.UUID
    relation: Optional[str]
    is_primary: bool
    student_name: Optional[str] = None
    admission_number: Optional[str] = None
    parent_name: Optional[str] = None
    parent_code: Optional[str] = None

    model_config = {"from_attributes": True}