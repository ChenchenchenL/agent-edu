"""add long-term memory v1 tables

Revision ID: 0008_long_term_memory_v1
Revises: 0007_autonomy_runtime
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_long_term_memory_v1"
down_revision = "0007_autonomy_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_memories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("knowledge_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("knowledge_level", sa.String(length=32), nullable=False),
        sa.Column("time_horizon", sa.String(length=32), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("prerequisite_keys", sa.JSON(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("source_memory_ids", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("compressed_into_id", sa.String(length=36), sa.ForeignKey("knowledge_memories.id"), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_knowledge_memories_profile_status", "knowledge_memories", ["learner_profile_id", "status"])
    op.create_index("ix_knowledge_memories_profile_key", "knowledge_memories", ["learner_profile_id", "knowledge_key"])

    op.create_table(
        "knowledge_memory_embeddings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_id", sa.String(length=36), sa.ForeignKey("knowledge_memories.id"), nullable=False, unique=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("knowledge_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("knowledge_level", sa.String(length=32), nullable=False),
        sa.Column("time_horizon", sa.String(length=32), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_knowledge_memory_embeddings_profile_status",
        "knowledge_memory_embeddings",
        ["learner_profile_id", "status"],
    )
    op.create_index(
        "ix_knowledge_memory_embeddings_profile_created",
        "knowledge_memory_embeddings",
        ["learner_profile_id", "created_at"],
    )

    op.create_table(
        "behavior_memories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("behavior_key", sa.String(length=255), nullable=False),
        sa.Column("behavior_category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("behavior_level", sa.String(length=32), nullable=False),
        sa.Column("time_horizon", sa.String(length=32), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("source_event_ids", sa.JSON(), nullable=False),
        sa.Column("source_memory_ids", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("intervention_effect", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("compressed_into_id", sa.String(length=36), sa.ForeignKey("behavior_memories.id"), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_behavior_memories_profile_status", "behavior_memories", ["learner_profile_id", "status"])
    op.create_index("ix_behavior_memories_profile_key", "behavior_memories", ["learner_profile_id", "behavior_key"])

    op.create_table(
        "behavior_memory_embeddings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_id", sa.String(length=36), sa.ForeignKey("behavior_memories.id"), nullable=False, unique=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("behavior_key", sa.String(length=255), nullable=False),
        sa.Column("behavior_category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("behavior_level", sa.String(length=32), nullable=False),
        sa.Column("time_horizon", sa.String(length=32), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_behavior_memory_embeddings_profile_status",
        "behavior_memory_embeddings",
        ["learner_profile_id", "status"],
    )
    op.create_index(
        "ix_behavior_memory_embeddings_profile_created",
        "behavior_memory_embeddings",
        ["learner_profile_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_behavior_memory_embeddings_profile_created", table_name="behavior_memory_embeddings")
    op.drop_index("ix_behavior_memory_embeddings_profile_status", table_name="behavior_memory_embeddings")
    op.drop_table("behavior_memory_embeddings")

    op.drop_index("ix_behavior_memories_profile_key", table_name="behavior_memories")
    op.drop_index("ix_behavior_memories_profile_status", table_name="behavior_memories")
    op.drop_table("behavior_memories")

    op.drop_index("ix_knowledge_memory_embeddings_profile_created", table_name="knowledge_memory_embeddings")
    op.drop_index("ix_knowledge_memory_embeddings_profile_status", table_name="knowledge_memory_embeddings")
    op.drop_table("knowledge_memory_embeddings")

    op.drop_index("ix_knowledge_memories_profile_key", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_profile_status", table_name="knowledge_memories")
    op.drop_table("knowledge_memories")
