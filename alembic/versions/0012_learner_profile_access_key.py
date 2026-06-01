"""add learner profile access key

Revision ID: 0012_learner_profile_access_key
Revises: 0011_reflection_proposal_rollouts
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_learner_profile_access_key"
down_revision = "0011_reflection_proposal_rollouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learner_profiles", sa.Column("access_key_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "learner_profiles",
        sa.Column("access_key_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_learner_profiles_access_key_hash",
        "learner_profiles",
        ["access_key_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_learner_profiles_access_key_hash", table_name="learner_profiles")
    op.drop_column("learner_profiles", "access_key_created_at")
    op.drop_column("learner_profiles", "access_key_hash")
