# app/models/student_year_mapping.py
"""
THE source of truth for a student's academic placement in a given year.

One row per (student, academic_year) — enforced by unique constraint.
The Student table keeps denormalized flat fields (standard_id, section,
roll_number, academic_year_id) as a cache of the ACTIVE mapping only.

Phase 6 Status lifecycle:
  ACTIVE      → COMPLETED      (year ended, promotion decision pending)
  ACTIVE      → LEFT           (mid-year departure by choice)
  ACTIVE      → TRANSFERRED    (mid-year transfer to another school)
  ACTIVE      → HOLD           (temporary suspension / processing hold)
  HOLD        → ACTIVE         (hold lifted, re-activated)

Phase 7 Terminal states (set when new-year mapping is created):
  COMPLETED   → PROMOTED       (admin ran promotion; student moved to next class)
  COMPLETED   → REPEATED       (admin decided student repeats same class)
  COMPLETED   → GRADUATED      (no next class; student has finished schooling)
"""
import uuid
from datetime import date, datetime
from typing import Optional
from sqlalchemy import String, ForeignKey, Date, DateTime, UniqueConstraint, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel
from app.utils.enums import EnrollmentStatus, AdmissionType


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
    # Denormalized section name for query speed
    section_name: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    roll_number: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    status: Mapped[EnrollmentStatus] = mapped_column(
        String(20), nullable=False, default=EnrollmentStatus.ACTIVE, index=True
    )

    # Phase 6: how the student joined this year
    admission_type: Mapped[Optional[AdmissionType]] = mapped_column(
        String(30), nullable=True, default=AdmissionType.NEW_ADMISSION
    )

    # Enrollment window
    joined_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    left_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Phase 7: tracks who created / last modified this mapping
    created_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    last_modified_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # Phase 7: when a mapping is PROMOTED/REPEATED, link to next year's mapping
    next_year_mapping_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_year_mappings.id", ondelete="SET NULL"),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    student: Mapped[Optional["Student"]] = relationship(
        "Student", foreign_keys=[student_id], lazy="select"
    )
    standard: Mapped[Optional["Standard"]] = relationship(
        "Standard", foreign_keys=[standard_id], lazy="select"
    )
    section: Mapped[Optional["Section"]] = relationship(
        "Section", foreign_keys=[section_id], lazy="select"
    )
    academic_year: Mapped[Optional["AcademicYear"]] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )