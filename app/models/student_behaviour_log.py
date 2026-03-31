import uuid
from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import Text, Date, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel
from app.utils.enums import IncidentType, IncidentSeverity

if TYPE_CHECKING:
    from app.models.student import Student
    from app.models.teacher import Teacher
    from app.models.academic_year import AcademicYear
    from app.models.school import School


class StudentBehaviourLog(BaseModel):
    __tablename__ = "student_behaviour_log"

    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    incident_type: Mapped[IncidentType] = mapped_column(
        Enum(IncidentType, name="incident_type_enum"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[IncidentSeverity] = mapped_column(
        Enum(IncidentSeverity, name="incident_severity_enum"),
        nullable=False,
    )
    incident_date: Mapped[date] = mapped_column(Date, nullable=False)
    academic_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    student: Mapped["Student"] = relationship(
        "Student", foreign_keys=[student_id], lazy="select"
    )
    teacher: Mapped["Teacher"] = relationship(
        "Teacher", foreign_keys=[teacher_id], lazy="select"
    )
    academic_year: Mapped["AcademicYear"] = relationship(
        "AcademicYear", foreign_keys=[academic_year_id], lazy="select"
    )
    school: Mapped["School"] = relationship(
        "School", foreign_keys=[school_id], lazy="select"
    )
