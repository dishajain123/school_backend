import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Numeric, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.models.exam import Exam
    from app.models.student import Student
    from app.models.masters import Subject, GradeMaster
    from app.models.user import User
    from app.models.school import School


class Result(BaseModel):
    __tablename__ = "results"
    __table_args__ = (
        UniqueConstraint(
            "exam_id",
            "student_id",
            "subject_id",
            name="uq_result_exam_student_subject",
        ),
    )

    exam_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marks_obtained: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    max_marks: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    percentage: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    grade_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("grade_master.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    entered_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    entered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    exam: Mapped["Exam"] = relationship(
        "Exam", foreign_keys=[exam_id], back_populates="results", lazy="select"
    )
    student: Mapped["Student"] = relationship(
        "Student", foreign_keys=[student_id], lazy="select"
    )
    subject: Mapped["Subject"] = relationship(
        "Subject", foreign_keys=[subject_id], lazy="select"
    )
    grade: Mapped[Optional["GradeMaster"]] = relationship(
        "GradeMaster", foreign_keys=[grade_id], lazy="select"
    )
    enterer: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[entered_by], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
