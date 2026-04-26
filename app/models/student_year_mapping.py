# app/models/student_year_mapping.py
"""
THE source of truth for where a student is enrolled in a given academic year.

One row per (student, academic_year).
Replaces the flat fields on Student for historical tracking.
Student.standard_id / academic_year_id / section / roll_number are kept
as a denormalized cache of the ACTIVE mapping for query convenience.

Status lifecycle:
  ACTIVE → COMPLETED (at year end, eligible for promotion)
  ACTIVE → LEFT      (mid-year departure)
  ACTIVE → TRANSFERRED (moved to another school)
  ACTIVE → HOLD      (temporary hold)
  HOLD   → ACTIVE    (hold lifted)
"""
import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, Date, DateTime, UniqueConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel
from app.utils.enums import EnrollmentStatus


class StudentYearMapping(BaseModel):
    __tablename__ = "student_year_mappings"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "academic_year_id",
            name="uq_student_year_mapping_student_year",
        ),
    )

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Denormalized for query speed (section name can change)
    section_name: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    roll_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    status: Mapped[EnrollmentStatus] = mapped_column(
        String(20), nullable=False, default=EnrollmentStatus.ACTIVE, index=True
    )

    # Enrollment window for this mapping
    joined_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    left_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Exit details (for LEFT or TRANSFERRED)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Who created/last-modified this mapping
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_modified_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    student: Mapped["Student"] = relationship("Student", foreign_keys=[student_id])
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id]
    )
    standard: Mapped["Standard"] = relationship(
        "Standard", foreign_keys=[standard_id]
    )
    section: Mapped[Optional["Section"]] = relationship(
        "Section", foreign_keys=[section_id]
    )
    school: Mapped["School"] = relationship("School", foreign_keys=[school_id])