"""add identifier columns for role profiles

Revision ID: c3f7d1a9b2e1
Revises: 9bec9f1e75ec
Create Date: 2026-04-28 22:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3f7d1a9b2e1"
down_revision = "9bec9f1e75ec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # students
    op.add_column(
        "students",
        sa.Column("identifier_issued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "students",
        sa.Column(
            "is_identifier_custom",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # teachers
    op.add_column(
        "teachers",
        sa.Column("identifier_issued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "teachers",
        sa.Column(
            "is_identifier_custom",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # parents
    op.add_column(
        "parents",
        sa.Column("identifier_issued_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "parents",
        sa.Column(
            "is_identifier_custom",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("parents", "is_identifier_custom")
    op.drop_column("parents", "identifier_issued_at")

    op.drop_column("teachers", "is_identifier_custom")
    op.drop_column("teachers", "identifier_issued_at")

    op.drop_column("students", "is_identifier_custom")
    op.drop_column("students", "identifier_issued_at")
