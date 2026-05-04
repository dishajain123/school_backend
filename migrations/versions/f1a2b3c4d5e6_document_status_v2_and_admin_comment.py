"""Document lifecycle: new status values + admin_comment.

Revision ID: f1a2b3c4d5e6
Revises: e8f4a2c91d00
Create Date: 2026-05-04

Migrates legacy document statuses to NOT_UPLOADED / PENDING / APPROVED / REJECTED / REQUESTED
and adds admin_comment. Replaces PostgreSQL document_status_enum with VARCHAR.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e8f4a2c91d00"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("documents"):
        return

    cols = {c["name"]: c for c in inspector.get_columns("documents")}
    if "admin_comment" not in cols:
        op.add_column(
            "documents",
            sa.Column("admin_comment", sa.String(length=2000), nullable=True),
        )

    status_info = cols.get("status")
    if status_info is None:
        return

    dialect = bind.dialect.name
    if dialect == "postgresql":
        row = bind.execute(
            sa.text(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = 'documents'
                  AND column_name = 'status'
                """
            )
        ).fetchone()
        already_varchar = bool(row and row[0] == "character varying")
    else:
        type_str = str(status_info.get("type", "")).upper()
        already_varchar = "VARCHAR" in type_str or "TEXT" in type_str or "STRING" in type_str

    if already_varchar:
        return

    if "status_v2" not in cols:
        op.add_column(
            "documents",
            sa.Column("status_v2", sa.String(length=32), nullable=True),
        )

    if dialect == "postgresql" and not already_varchar:
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
    else:
        op.execute(
            sa.text(
                """
                UPDATE documents SET status_v2 = CASE
                    WHEN status IN ('READY', 'VERIFIED') THEN 'APPROVED'
                    WHEN status IN ('FAILED', 'REJECTED') THEN 'REJECTED'
                    WHEN status = 'PROCESSING' THEN 'PENDING'
                    WHEN status = 'PENDING'
                         AND (file_key IS NULL OR trim(file_key) = '') THEN 'REQUESTED'
                    WHEN status = 'PENDING' THEN 'PENDING'
                    ELSE 'NOT_UPLOADED'
                END
                """
            )
        )

    op.execute(sa.text("UPDATE documents SET status_v2 = 'NOT_UPLOADED' WHERE status_v2 IS NULL"))

    if dialect == "postgresql" and not already_varchar:
        op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status DROP DEFAULT"))
        op.execute(sa.text("ALTER TABLE documents DROP COLUMN status"))
        op.execute(sa.text("DROP TYPE IF EXISTS document_status_enum"))
        op.execute(sa.text("ALTER TABLE documents RENAME COLUMN status_v2 TO status"))
        op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status SET NOT NULL"))
        op.execute(sa.text("ALTER TABLE documents ALTER COLUMN status SET DEFAULT 'NOT_UPLOADED'"))
    else:
        with op.batch_alter_table("documents") as batch:
            batch.drop_column("status")
        op.alter_column(
            "documents",
            "status_v2",
            new_column_name="status",
            existing_type=sa.String(32),
            nullable=False,
            server_default="NOT_UPLOADED",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("documents"):
        return
    cols = {c["name"] for c in inspector.get_columns("documents")}
    if "admin_comment" in cols:
        op.drop_column("documents", "admin_comment")
