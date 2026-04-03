from __future__ import annotations

import uuid
from datetime import date, time
from typing import TYPE_CHECKING, Optional

from sqlalchemy import String, Boolean, Date, Time, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.models.masters import Standard, Subject
    from app.models.academic_year import AcademicYear
    from app.models.school import School
    from app.models.user import User


class ExamSeries(BaseModel):
    __tablename__ = "exam_series"
    __table_args__ = (
        UniqueConstraint(
            "school_id",
            "standard_id",
            "academic_year_id",
            "name",
            name="uq_exam_series_name_standard_year_school",
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    standard: Mapped["Standard"] = relationship(
        "Standard", foreign_keys=[standard_id], lazy="select"
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[created_by], lazy="select"
    )
    entries: Mapped[list["ExamScheduleEntry"]] = relationship(
        "ExamScheduleEntry", back_populates="series", lazy="select"
    )


class ExamScheduleEntry(BaseModel):
    __tablename__ = "exam_schedule_entries"

    series_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exam_series.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exam_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    venue: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_cancelled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    series: Mapped["ExamSeries"] = relationship(
        "ExamSeries", foreign_keys=[series_id], back_populates="entries", lazy="select"
    )
    subject: Mapped["Subject"] = relationship(
        "Subject", foreign_keys=[subject_id], lazy="select"
    )
