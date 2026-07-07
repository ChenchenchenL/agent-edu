"""add plan_templates to skill_artifacts

Revision ID: 0024_add_plan_templates
Revises: 0023_add_preferred_language
Create Date: 2026-07-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_add_plan_templates"
down_revision = "0023_add_preferred_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_artifacts",
        sa.Column("plan_templates", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("skill_artifacts", "plan_templates")
