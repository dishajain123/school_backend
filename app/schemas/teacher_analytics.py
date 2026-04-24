import uuid
from typing import Optional

from pydantic import BaseModel


class TeacherAssignmentAnalytics(BaseModel):
    standard_id: uuid.UUID
    standard_name: str
    section: str
    subject_id: uuid.UUID
    subject_name: str
    academic_year_id: uuid.UUID


class TeacherAssignmentSubmissionAnalytics(BaseModel):
    total_assignments: int
    overdue_assignments: int
    total_submissions: int
    on_time_submissions: int
    late_submissions: int
    pending_review_submissions: int


class TeacherAttendanceBySubjectAnalytics(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    total: int
    present: int
    absent: int
    late: int
    attendance_percentage: float


class TeacherAttendanceAnalytics(BaseModel):
    total_records: int
    present_count: int
    absent_count: int
    late_count: int
    attendance_percentage: float
    by_subject: list[TeacherAttendanceBySubjectAnalytics]


class TeacherMarksBySubjectAnalytics(BaseModel):
    subject_id: uuid.UUID
    subject_name: str
    entries: int
    average_percentage: float


class TeacherMarksAnalytics(BaseModel):
    total_entries: int
    average_percentage: float
    above_average_count: int
    moderate_count: int
    below_average_count: int
    by_subject: list[TeacherMarksBySubjectAnalytics]


class TeacherAnalyticsResponse(BaseModel):
    teacher_id: uuid.UUID
    filters: dict[str, Optional[str]]
    assignments: list[TeacherAssignmentAnalytics]
    assignment_submission: TeacherAssignmentSubmissionAnalytics
    attendance: TeacherAttendanceAnalytics
    marks: TeacherMarksAnalytics
