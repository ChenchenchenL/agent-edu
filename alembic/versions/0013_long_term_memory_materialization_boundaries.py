"""add long-term memory materialization boundary metadata

Revision ID: 0013_long_term_memory_materialization_boundaries
Revises: 0012_learner_profile_access_key
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_long_term_memory_materialization_boundaries"
down_revision = "0012_learner_profile_access_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_memories",
        sa.Column("semantic_category", sa.String(length=64), nullable=False, server_default="concept"),
    )
    op.add_column(
        "knowledge_memories",
        sa.Column("validation_status", sa.String(length=64), nullable=False, server_default="unverified"),
    )
    op.add_column(
        "knowledge_memories",
        sa.Column("provenance_type", sa.String(length=64), nullable=False, server_default="system_inference"),
    )
    op.add_column("knowledge_memories", sa.Column("provenance_source_id", sa.String(length=36), nullable=True))
    op.add_column(
        "knowledge_memories",
        sa.Column("scope_ref", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("knowledge_memories", sa.Column("promotion_rationale", sa.Text(), nullable=True))

    op.add_column(
        "behavior_memories",
        sa.Column("semantic_category", sa.String(length=64), nullable=False, server_default="strategy"),
    )
    op.add_column(
        "behavior_memories",
        sa.Column("validation_status", sa.String(length=64), nullable=False, server_default="unverified"),
    )
    op.add_column(
        "behavior_memories",
        sa.Column("provenance_type", sa.String(length=64), nullable=False, server_default="system_inference"),
    )
    op.add_column("behavior_memories", sa.Column("provenance_source_id", sa.String(length=36), nullable=True))
    op.add_column(
        "behavior_memories",
        sa.Column("scope_ref", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("behavior_memories", sa.Column("promotion_rationale", sa.Text(), nullable=True))

    op.create_table(
        "memory_conflict_sets",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("topic_key", sa.String(length=255), nullable=False),
        sa.Column("conflict_type", sa.String(length=64), nullable=False),
        sa.Column("severity_score", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_conflict_sets_profile_status_topic",
        "memory_conflict_sets",
        ["learner_profile_id", "status", "topic_key"],
    )
    op.create_index(
        "ix_memory_conflict_sets_profile_goal_status",
        "memory_conflict_sets",
        ["learner_profile_id", "learner_goal_id", "status"],
    )

    op.create_table(
        "memory_conflict_members",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("conflict_set_id", sa.String(length=36), sa.ForeignKey("memory_conflict_sets.id"), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("memory_key", sa.String(length=255), nullable=False),
        sa.Column("stance", sa.String(length=32), nullable=False),
        sa.Column("support_score", sa.Float(), nullable=False),
        sa.Column("contradiction_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_conflict_members_set",
        "memory_conflict_members",
        ["conflict_set_id", "created_at"],
    )
    op.create_index(
        "ix_memory_conflict_members_memory",
        "memory_conflict_members",
        ["memory_type", "memory_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_conflict_members_memory", table_name="memory_conflict_members")
    op.drop_index("ix_memory_conflict_members_set", table_name="memory_conflict_members")
    op.drop_table("memory_conflict_members")

    op.drop_index("ix_memory_conflict_sets_profile_goal_status", table_name="memory_conflict_sets")
    op.drop_index("ix_memory_conflict_sets_profile_status_topic", table_name="memory_conflict_sets")
    op.drop_table("memory_conflict_sets")

    op.drop_column("behavior_memories", "promotion_rationale")
    op.drop_column("behavior_memories", "scope_ref")
    op.drop_column("behavior_memories", "provenance_source_id")
    op.drop_column("behavior_memories", "provenance_type")
    op.drop_column("behavior_memories", "validation_status")
    op.drop_column("behavior_memories", "semantic_category")

    op.drop_column("knowledge_memories", "promotion_rationale")
    op.drop_column("knowledge_memories", "scope_ref")
    op.drop_column("knowledge_memories", "provenance_source_id")
    op.drop_column("knowledge_memories", "provenance_type")
    op.drop_column("knowledge_memories", "validation_status")
    op.drop_column("knowledge_memories", "semantic_category")
