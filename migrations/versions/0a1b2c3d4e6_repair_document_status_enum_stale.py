"""Repair documents.status when f1 was stamped but conversion never ran.

Revision ID: 0a1b2c3d4e6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-04

If ``documents.status`` is still PostgreSQL ``document_status_enum`` while
``alembic_version`` already includes ``f1a2b3c4d5e6``, this migration applies
the same varchar conversion as ``f1a2b3c4d5e6``. No-op when ``status`` is
already ``character varying``, or when only ``status_v2`` remains (partial run).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0a1b2c3d4e6"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    inspector = sa.inspect(bind)
    if not inspector.has_table("documents"):
        return

    col_rows = bind.execute(
        sa.text(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'documents'
            """
        )
    ).fetchall()
    col_info = {r[0]: r[1] for r in col_rows}

    if col_info.get("status") == "character varying":
        return

    if "status" not in col_info and "status_v2" in col_info:
        op.execute(sa.text("ALTER TABLE documents RENAME COLUMN status_v2 TO status"))
        op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status SET NOT NULL"))
        op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'NOT_UPLOADED'"))
        return

    if "status" not in col_info:
        return

    cols = {c["name"] for c in inspector.get_columns("documents")}
    if "admin_comment" not in cols:
        op.add_column(
            "documents",
            sa.Column("admin_comment", sa.String(length=2000), nullable=True),
        )

    if "status_v2" not in cols:
        op.add_column(
            "documents",
            sa.Column("status_v2", sa.String(length=32), nullable=True),
        )

    op.execute(
        sa.text(
            """
            UPDATE documents SET status_v2 = CASE
                WHEN status::text IN ('READY', 'VERIFIED') THEN 'APPROVED'
                WHEN status::text IN ('FAILED', 'REJECTED') THEN 'REJECTED'
                WHEN status::text = 'PROCESSING' THEN 'PENDING'
                WHEN status::text = 'PENDING'
                     AND (file_key IS NULL OR btrim(file_key) = '') THEN 'REQUESTED'
                WHEN status::text = 'PENDING' THEN 'PENDING'
                ELSE 'NOT_UPLOADED'
            END
            """
        )
    )
    op.execute(sa.text("UPDATE documents SET status_v2 = 'NOT_UPLOADED' WHERE status_v2 IS NULL"))

    op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status DROP DEFAULT"))
    op.execute(sa.text("ALTER TABLE documents DROP COLUMN status"))
    op.execute(sa.text("DROP TYPE IF EXISTS document_status_enum"))
    op.execute(sa.text("ALTER TABLE documents RENAME COLUMN status_v2 TO status"))
    op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status SET NOT NULL"))
    op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'NOT_UPLOADED'"))


def downgrade() -> None:
    pass
