"""add next_year_mapping_id to student_year_mappings

Revision ID: 4f2c8d9a1b7e
Revises: c3f7d1a9b2e1
Create Date: 2026-04-30 20:15:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "4f2c8d9a1b7e"
down_revision = "c3f7d1a9b2e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "student_year_mappings",
        sa.Column("next_year_mapping_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_student_year_mappings_next_year_mapping_id",
        "student_year_mappings",
        "student_year_mappings",
        ["next_year_mapping_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_student_year_mappings_next_year_mapping_id",
        "student_year_mappings",
        type_="foreignkey",
    )
    op.drop_column("student_year_mappings", "next_year_mapping_id")
