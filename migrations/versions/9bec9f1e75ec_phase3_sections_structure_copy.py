"""phase3_sections_structure_copy

Revision ID: 9bec9f1e75ec
Revises: 
Create Date: 2026-04-26 15:23:58.534339

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9bec9f1e75ec"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sections",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("standard_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["standard_id"], ["standards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("school_id", "standard_id", "academic_year_id", "name", name="uq_section_school_standard_year_name"),
    )
    op.create_index("idx_sections_standard_year", "sections", ["standard_id", "academic_year_id"], unique=False)

    op.create_table(
        "academic_structure_copies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("source_year_id", sa.UUID(), nullable=True),
        sa.Column("target_year_id", sa.UUID(), nullable=False),
        sa.Column("performed_by_id", sa.UUID(), nullable=True),
        sa.Column("standards_copied", sa.Integer(), server_default="0", nullable=False),
        sa.Column("subjects_copied", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sections_copied", sa.Integer(), server_default="0", nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("performed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_year_id"], ["academic_years.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["performed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # One-time JSONB -> sections data migration should run separately.


def downgrade() -> None:
    op.drop_table("academic_structure_copies")
    op.drop_index("idx_sections_standard_year", table_name="sections")
    op.drop_table("sections")
