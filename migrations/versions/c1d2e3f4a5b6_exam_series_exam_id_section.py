"""Link exam_series to exams; section scope; duplicate prevention per exam+section.

Revision ID: c1d2e3f4a5b6
Revises: 0a1b2c3d4e6
Create Date: 2026-05-04

- Adds exam_id (FK to exams) and section (class section scope; empty string = all sections).
- Replaces name-based uniqueness with a partial unique index on (exam_id, section)
  for rows that reference an exam.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "0a1b2c3d4e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_constraint(
        "uq_exam_series_name_standard_year_school",
        "exam_series",
        type_="unique",
    )

    op.add_column(
        "exam_series",
        sa.Column(
            "exam_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "exam_series",
        sa.Column(
            "section",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )

    op.create_foreign_key(
        "fk_exam_series_exam_id",
        "exam_series",
        "exams",
        ["exam_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_exam_series_exam_id", "exam_series", ["exam_id"])

    # Best-effort backfill: pair series with exams in the same class/year when names align
    # (matches demo seed: "<Class> … Series" ↔ exam name "<Class> …").
    op.execute(
        sa.text(
            """
            UPDATE exam_series es
            SET exam_id = e.id
            FROM exams e
            WHERE es.exam_id IS NULL
              AND e.school_id = es.school_id
              AND e.standard_id = es.standard_id
              AND e.academic_year_id = es.academic_year_id
              AND (
                    e.name = TRIM(REPLACE(es.name, ' Series', ''))
                 OR e.name = TRIM(REPLACE(es.name, 'UT2 Series', 'Unit Test 2'))
                 OR e.name = TRIM(REPLACE(es.name, 'Final Series', 'Finals'))
              )
            """
        )
    )

    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_exam_series_exam_section
            ON exam_series (exam_id, section)
            WHERE exam_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(sa.text("DROP INDEX IF EXISTS uq_exam_series_exam_section"))

    op.drop_index("ix_exam_series_exam_id", table_name="exam_series")
    op.drop_constraint("fk_exam_series_exam_id", "exam_series", type_="foreignkey")
    op.drop_column("exam_series", "section")
    op.drop_column("exam_series", "exam_id")

    op.create_unique_constraint(
        "uq_exam_series_name_standard_year_school",
        "exam_series",
        ["school_id", "standard_id", "academic_year_id", "name"],
    )
