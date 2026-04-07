import uuid
from datetime import date

from pydantic import BaseModel
from typing import Optional, List


class PrincipalReportOverviewResponse(BaseModel):
    academic_year_id: uuid.UUID
    report_date: date

    # Student attendance (overall)
    student_attendance_percentage: float
    student_present_count: int
    student_total_records: int

    # Fees paid
    fees_paid_amount: float
    fees_paid_transactions: int

    # Results
    results_average_percentage: float
    students_with_results: int
    result_entries_count: int

    # Teacher attendance (derived from approved leaves for report_date)
    teacher_attendance_percentage: float
    total_teachers: int
    teachers_present_today: int
    teachers_on_leave_today: int


class ReportMetricSummary(BaseModel):
    value: float
    numerator: int
    denominator: int


class ReportAmountSummary(BaseModel):
    amount: float
    count: int


class AttendanceBySubjectItem(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    present: int
    total: int
    percentage: float


class FeesByStudentItem(BaseModel):
    student_id: uuid.UUID
    admission_number: str
    paid_amount: float
    transactions: int


class ResultsBySubjectItem(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    average_percentage: float
    entries: int


class TeacherAttendanceItem(BaseModel):
    teacher_id: uuid.UUID
    teacher_label: str
    is_present: bool
    on_leave: bool


class PrincipalReportDetailsResponse(BaseModel):
    academic_year_id: uuid.UUID
    report_date: date
    metric: Optional[str] = None
    filters: dict

    student_attendance: ReportMetricSummary
    fees_paid: ReportAmountSummary
    results: ReportMetricSummary
    teacher_attendance: ReportMetricSummary

    attendance_by_subject: List[AttendanceBySubjectItem]
    fees_by_student: List[FeesByStudentItem]
    results_by_subject: List[ResultsBySubjectItem]
    teacher_attendance_items: List[TeacherAttendanceItem]
