from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Text,
    ForeignKey,
    UniqueConstraint,
    Boolean,
    DateTime,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import BaseModel

if TYPE_CHECKING:
    from app.models.homework import Homework
    from app.models.student import Student
    from app.models.user import User
    from app.models.school import School


class HomeworkSubmission(BaseModel):
    __tablename__ = "homework_submissions"
    __table_args__ = (
        UniqueConstraint(
            "homework_id",
            "student_id",
            name="uq_homework_submission_homework_student",
        ),
    )

    homework_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("homework.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    performed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    text_response: Mapped[str] = mapped_column(Text, nullable=False)
    file_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_reviewed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_approved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    homework: Mapped["Homework"] = relationship(
        "Homework",
        foreign_keys=[homework_id],
        lazy="select",
    )
    student: Mapped["Student"] = relationship(
        "Student",
        foreign_keys=[student_id],
        lazy="select",
    )
    performer: Mapped["User"] = relationship(
        "User",
        foreign_keys=[performed_by],
        lazy="select",
    )
    reviewer: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[reviewed_by],
        lazy="select",
    )
    school: Mapped["School"] = relationship(
        "School",
        foreign_keys=[school_id],
        lazy="select",
    )
