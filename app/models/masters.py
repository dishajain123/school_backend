import uuid
from typing import Optional
from sqlalchemy import String, Integer, Numeric, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel


class Standard(BaseModel):
    __tablename__ = "standards"
    __table_args__ = (
        UniqueConstraint("school_id", "level", "academic_year_id", name="uq_standard_level_year_school"),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)

    school: Mapped["School"] = relationship("School", foreign_keys=[school_id], lazy="select")
    academic_year: Mapped[Optional["AcademicYear"]] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )
    subjects: Mapped[list["Subject"]] = relationship(
        "Subject",
        foreign_keys="Subject.standard_id",
        lazy="select",
        back_populates="standard",
    )


class Subject(BaseModel):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_subject_code_school"),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    standard_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("standards.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(String(20), nullable=False)

    school: Mapped["School"] = relationship("School", foreign_keys=[school_id], lazy="select")
    standard: Mapped["Standard"] = relationship(
        "Standard", foreign_keys=[standard_id], lazy="select", back_populates="subjects"
    )


class GradeMaster(BaseModel):
    __tablename__ = "grade_master"
    __table_args__ = (
        UniqueConstraint("school_id", "grade_letter", name="uq_grade_letter_school"),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    min_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    max_percent: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    grade_letter: Mapped[str] = mapped_column(String(5), nullable=False)
    grade_point: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)

    school: Mapped["School"] = relationship("School", foreign_keys=[school_id], lazy="select")