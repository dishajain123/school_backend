# app/models/parent_student_link.py
"""
Explicit many-to-many junction between parents and students.
Replaces the single parent_id FK on Student, which only allows one parent.

A student can have multiple parents (mother, father, guardian).
A parent can have multiple children.
The primary parent (main contact) is flagged with is_primary=True.
"""
import uuid
from typing import Optional
from sqlalchemy import String, ForeignKey, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.base import BaseModel


class ParentStudentLink(BaseModel):
    __tablename__ = "parent_student_links"
    __table_args__ = (
        UniqueConstraint(
            "parent_id", "student_id",
            name="uq_parent_student_link",
        ),
    )

    parent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("parents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
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
    relation: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )  # MOTHER, FATHER, GUARDIAN, etc.
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )  # Primary contact for notifications

    # Relationships
    parent: Mapped["Parent"] = relationship("Parent", foreign_keys=[parent_id])
    student: Mapped["Student"] = relationship("Student", foreign_keys=[student_id])