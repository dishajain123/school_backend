# app/models/academic_structure_copy.py
"""
Audit record for every structure copy operation (year-to-year).
Immutable — one row per copy action.
"""
import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, DateTime, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import BaseModel


class AcademicStructureCopy(BaseModel):
    __tablename__ = "academic_structure_copies"

    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("schools.id", ondelete="CASCADE"), nullable=False
    )
    source_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="SET NULL"), nullable=True
    )
    target_year_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("academic_years.id", ondelete="CASCADE"), nullable=False
    )
    performed_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    standards_copied: Mapped[int] = mapped_column(__import__('sqlalchemy').Integer, nullable=False, default=0)
    subjects_copied: Mapped[int] = mapped_column(__import__('sqlalchemy').Integer, nullable=False, default=0)
    sections_copied: Mapped[int] = mapped_column(__import__('sqlalchemy').Integer, nullable=False, default=0)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )