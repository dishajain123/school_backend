"""Per-exam examination schedule files (separate from class daily timetables).

Revision ID: d4e5f6a7b8c9
Revises: c1d2e3f4a5b6
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_timetable_standard_section_year_school",
        "timetables",
        type_="unique",
    )
    op.add_column(
        "timetables",
        sa.Column("exam_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_timetables_exam_id_exams",
        "timetables",
        "exams",
        ["exam_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_timetables_exam_id", "timetables", ["exam_id"])

    op.execute(
        """
        CREATE UNIQUE INDEX uq_timetable_class_scope ON timetables (
            school_id,
            standard_id,
            academic_year_id,
            COALESCE(section, '')
        )
        WHERE exam_id IS NULL;
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_timetable_exam_scope ON timetables (
            school_id,
            standard_id,
            academic_year_id,
            COALESCE(section, ''),
            exam_id
        )
        WHERE exam_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_timetable_exam_scope;")
    op.execute("DROP INDEX IF EXISTS uq_timetable_class_scope;")
    op.drop_index("ix_timetables_exam_id", table_name="timetables")
    op.drop_constraint("fk_timetables_exam_id_exams", "timetables", type_="foreignkey")
    op.drop_column("timetables", "exam_id")
    op.create_unique_constraint(
        "uq_timetable_standard_section_year_school",
        "timetables",
        ["school_id", "standard_id", "section", "academic_year_id"],
    )
