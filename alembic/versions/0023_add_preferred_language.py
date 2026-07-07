"""add preferred_language to learner_goals

Revision ID: 0023_add_preferred_language
Revises: 0022_missing_reflection_skill_tables
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_add_preferred_language"
down_revision = "0022_missing_reflection_skill_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learner_goals",
        sa.Column("preferred_language", sa.String(16), nullable=False, server_default="zh"),
    )


def downgrade() -> None:
    op.drop_column("learner_goals", "preferred_language")
