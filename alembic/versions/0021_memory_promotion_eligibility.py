"""add memory promotion eligibility records

Revision ID: 0021_memory_promotion_eligibility
Revises: 0020_skill_curator_recommendations
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_memory_promotion_eligibility"
down_revision = "0020_skill_curator_recommendations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_promotion_eligibility_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_id", sa.String(length=36), sa.ForeignKey("knowledge_memories.id"), nullable=False),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("independent_source_count", sa.Integer(), nullable=False),
        sa.Column("high_signal_source_count", sa.Integer(), nullable=False),
        sa.Column("evidence_span_hours", sa.Float(), nullable=False),
        sa.Column("conflict_blocked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("blocked_conflict_set_id", sa.String(length=36), sa.ForeignKey("memory_conflict_sets.id"), nullable=True),
        sa.Column("blocked_memory_id", sa.String(length=36), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_promotion_eligibility_current_memory",
        "memory_promotion_eligibility_records",
        ["memory_id"],
        unique=True,
        sqlite_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_memory_promotion_eligibility_profile_goal_status",
        "memory_promotion_eligibility_records",
        ["learner_profile_id", "learner_goal_id", "status", "evaluated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_promotion_eligibility_profile_goal_status", table_name="memory_promotion_eligibility_records")
    op.drop_index("ix_memory_promotion_eligibility_current_memory", table_name="memory_promotion_eligibility_records")
    op.drop_table("memory_promotion_eligibility_records")
