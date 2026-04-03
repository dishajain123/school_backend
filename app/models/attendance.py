from __future__ import annotations

import uuid
from datetime import date
from sqlalchemy import Date, ForeignKey, UniqueConstraint, Enum as SAEnum, String, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel
from app.utils.enums import AttendanceStatus


class Attendance(BaseModel):
    __tablename__ = "attendance"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "subject_id", "date", "lecture_number",
            name="uq_attendance_student_subject_date_lecture",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teachers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    section: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    lecture_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        index=True,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    status: Mapped[AttendanceStatus] = mapped_column(
        SAEnum(AttendanceStatus, name="attendancestatus", create_type=False),
        nullable=False,
    )

    student: Mapped["Student"] = relationship("Student", foreign_keys=[student_id], lazy="select")
    teacher: Mapped["Teacher"] = relationship("Teacher", foreign_keys=[teacher_id], lazy="select")
    standard: Mapped["Standard"] = relationship("Standard", foreign_keys=[standard_id], lazy="select")
    subject: Mapped["Subject"] = relationship("Subject", foreign_keys=[subject_id], lazy="select")
    academic_year: Mapped["AcademicYear"] = relationship("AcademicYear", foreign_keys=[academic_year_id], lazy="select")
