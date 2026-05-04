"""Backfill users.school_id from DEFAULT_SCHOOL_ID then set NOT NULL.

Revision ID: e8f4a2c91d00
Revises: 4f2c8d9a1b7e
Create Date: 2026-05-02

Requires ``DEFAULT_SCHOOL_ID`` in app settings (same as ``app.core.config`` / ``.env``).
That UUID must reference an existing ``schools.id`` row.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "e8f4a2c91d00"
down_revision = "4f2c8d9a1b7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.core.config import settings

    bind = op.get_bind()
    null_count = bind.execute(
        text("SELECT COUNT(*) FROM users WHERE school_id IS NULL")
    ).scalar_one()
    if int(null_count) > 0:
        if not settings.DEFAULT_SCHOOL_ID:
            raise RuntimeError(
                "Users with NULL school_id exist but DEFAULT_SCHOOL_ID is not set. "
                "Set DEFAULT_SCHOOL_ID in the environment (must match schools.id), then re-run."
            )
        sid = str(settings.DEFAULT_SCHOOL_ID).strip()
        bind.execute(
            text("UPDATE users SET school_id = CAST(:sid AS uuid) WHERE school_id IS NULL"),
            {"sid": sid},
        )
        remaining = bind.execute(
            text("SELECT COUNT(*) FROM users WHERE school_id IS NULL")
        ).scalar_one()
        if int(remaining) != 0:
            raise RuntimeError(
                f"After backfill, {remaining} user(s) still have NULL school_id; aborting before NOT NULL."
            )

    op.alter_column(
        "users",
        "school_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "school_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
