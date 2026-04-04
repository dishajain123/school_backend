import uuid
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field
from app.utils.enums import AttendanceStatus


# ── Mark Attendance ───────────────────────────────────────────────────────────

class AttendanceRecord(BaseModel):
    student_id: uuid.UUID
    status: AttendanceStatus


class MarkAttendanceRequest(BaseModel):
    standard_id: uuid.UUID
    section: str = Field(..., max_length=10)
    subject_id: uuid.UUID
    academic_year_id: uuid.UUID
    date: date
    records: list[AttendanceRecord] = Field(..., min_length=1)

    model_config = {"str_strip_whitespace": True}


# ── Response ──────────────────────────────────────────────────────────────────

class AttendanceResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    teacher_id: uuid.UUID
    standard_id: uuid.UUID
    section: str
    subject_id: uuid.UUID
    academic_year_id: uuid.UUID
    date: date
    status: AttendanceStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MarkAttendanceResponse(BaseModel):
    inserted: int
    updated: int
    total: int
    date: date


class AttendanceListResponse(BaseModel):
    items: list[AttendanceResponse]
    total: int


# ── Analytics ─────────────────────────────────────────────────────────────────

class SubjectAttendanceStat(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    subject_code: str
    total_classes: int
    present: int
    absent: int
    late: int
    percentage: float


class StudentAttendanceAnalytics(BaseModel):
    student_id: uuid.UUID
    month: Optional[int]
    year: Optional[int]
    overall_percentage: float
    subjects: list[SubjectAttendanceStat]


class ClassSnapshotRecord(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    roll_number: Optional[str]
    section: str
    status: Optional[AttendanceStatus]


class ClassAttendanceSnapshot(BaseModel):
    standard_id: uuid.UUID
    date: date
    total_students: int
    present: int
    absent: int
    late: int
    not_marked: int
    records: list[ClassSnapshotRecord]


class BelowThresholdStudent(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    section: str
    overall_percentage: float


class BelowThresholdResponse(BaseModel):
    standard_id: uuid.UUID
    threshold: float
    academic_year_id: uuid.UUID
    students: list[BelowThresholdStudent]
    total: int
