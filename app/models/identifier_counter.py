# app/models/identifier_counter.py
"""
Tracks the last-used sequential number per school per identifier type.
Used by the auto-generation engine to produce the NEXT identifier.
Row is locked with SELECT FOR UPDATE during generation to prevent race conditions.
"""
import uuid
import enum
from sqlalchemy import String, Integer, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import BaseModel


class IdentifierCounter(BaseModel):
    __tablename__ = "identifier_counters"
    __table_args__ = (
        UniqueConstraint(
            "school_id", "identifier_type", "year_tag",
            name="uq_identifier_counter_school_type_year",
        ),
    )

    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # ADMISSION_NUMBER | EMPLOYEE_ID | PARENT_CODE
    identifier_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # For student admission numbers we bucket by year (e.g. "2024").
    # For teacher/parent identifiers this is always "ALL" (global sequence).
    year_tag: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ALL"
    )

    last_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )