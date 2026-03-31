import uuid
from typing import Optional
from sqlalchemy import String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel


class TeacherClassSubject(BaseModel):
    __tablename__ = "teacher_class_subject"
    __table_args__ = (
        UniqueConstraint(
            "teacher_id",
            "standard_id",
            "section",
            "subject_id",
            "academic_year_id",
            name="uq_teacher_class_subject_year",
        ),
    )

    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    section: Mapped[str] = mapped_column(String(10), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    teacher: Mapped["Teacher"] = relationship(
        "Teacher", foreign_keys=[teacher_id], lazy="select"
    )
    standard: Mapped["Standard"] = relationship(
        "Standard", foreign_keys=[standard_id], lazy="select"
    )
    subject: Mapped["Subject"] = relationship(
        "Subject", foreign_keys=[subject_id], lazy="select"
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )