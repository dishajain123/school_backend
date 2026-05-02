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


# ── Lecture-wise Attendance ───────────────────────────────────────────────────

class LectureStudentEntry(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    student_name: Optional[str]
    roll_number: Optional[str]
    status: AttendanceStatus
    attendance_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class LectureAttendanceResponse(BaseModel):
    standard_id: uuid.UUID
    section: str
    subject_id: uuid.UUID
    academic_year_id: uuid.UUID
    date: date
    total_students: int
    present_count: int
    absent_count: int
    late_count: int
    entries: list[LectureStudentEntry]


# ── Student Detail Attendance ─────────────────────────────────────────────────

class MonthlyAttendanceSummary(BaseModel):
    month: int
    year: int
    total_classes: int
    present: int
    absent: int
    late: int
    percentage: float


class StudentDetailAttendanceResponse(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    student_name: Optional[str]
    overall_percentage: float
    lecture_records: list[AttendanceResponse]
    subject_stats: list["SubjectAttendanceStat"]
    monthly_summary: list[MonthlyAttendanceSummary]


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


# ── Dashboard Analytics (Principal / Trustee) ─────────────────────────────────

class ClassAttendanceStat(BaseModel):
    standard_id: uuid.UUID
    standard_name: str
    section: str
    total_records: int
    present: int
    absent: int
    late: int
    percentage: float


class SubjectSchoolAttendanceStat(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    subject_code: str
    total_records: int
    present: int
    absent: int
    late: int
    percentage: float


class AbsenteeEntry(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    student_name: Optional[str]
    standard_id: uuid.UUID
    standard_name: str
    section: str
    total_classes: int
    absences: int
    percentage: float


class AttendanceTrendItem(BaseModel):
    period_label: str          # e.g. "2024-W01" or "2024-01"
    period_year: int
    period_value: int          # week number or month number
    total_records: int
    present: int
    absent: int
    late: int
    percentage: float


class AttendanceDashboardResponse(BaseModel):
    school_id: uuid.UUID
    academic_year_id: uuid.UUID
    overall_percentage: float
    total_records: int
    present: int
    absent: int
    late: int
    class_stats: list[ClassAttendanceStat]
    subject_stats: list[SubjectSchoolAttendanceStat]
    top_absentees: list[AbsenteeEntry]
    weekly_trend: list[AttendanceTrendItem]
    monthly_trend: list[AttendanceTrendItem]