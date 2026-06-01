"""extend long-term memory with governance metadata

Revision ID: 0009_long_term_memory_governance
Revises: 0008_long_term_memory_v1
Create Date: 2026-05-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_long_term_memory_governance"
down_revision = "0008_long_term_memory_v1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("knowledge_memories", "behavior_memories"):
        op.add_column(table_name, sa.Column("scope_type", sa.String(length=32), nullable=False, server_default="profile_global"))
        op.add_column(table_name, sa.Column("stability_score", sa.Float(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("goal_relevance_score", sa.Float(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("support_score", sa.Float(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("contradiction_score", sa.Float(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("contradiction_count", sa.Integer(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("last_supported_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table_name, sa.Column("last_contradicted_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(
            table_name,
            sa.Column("promotion_state_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.add_column(table_name, sa.Column("suppressed_reason_code", sa.String(length=128), nullable=True))
        op.add_column(table_name, sa.Column("suppressed_reason_note", sa.Text(), nullable=True))
        op.add_column(table_name, sa.Column("suppressed_by", sa.String(length=128), nullable=True))
        op.add_column(table_name, sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("knowledge_memories", sa.Column("prerequisite_weight", sa.Float(), nullable=False, server_default="0"))
    op.add_column("knowledge_memories", sa.Column("assessment_evidence_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("knowledge_memories", sa.Column("task_evidence_count", sa.Integer(), nullable=False, server_default="0"))

    op.add_column("behavior_memories", sa.Column("intervention_success_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("behavior_memories", sa.Column("intervention_failure_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("behavior_memories", sa.Column("cross_session_recurrence_count", sa.Integer(), nullable=False, server_default="0"))

    for table_name in ("knowledge_memory_embeddings", "behavior_memory_embeddings"):
        op.add_column(table_name, sa.Column("stability_score", sa.Float(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("goal_relevance_score", sa.Float(), nullable=False, server_default="0"))
        op.add_column(table_name, sa.Column("scope_type", sa.String(length=32), nullable=False, server_default="profile_global"))

    op.execute(
        """
        UPDATE knowledge_memories
        SET scope_type = CASE
            WHEN learner_goal_id IS NULL THEN 'profile_global'
            ELSE 'goal_scoped'
        END,
        goal_relevance_score = CASE
            WHEN learner_goal_id IS NULL THEN 0.5
            ELSE 1.0
        END,
        last_supported_at = updated_at,
        promotion_state_changed_at = updated_at
        """
    )
    op.execute(
        """
        UPDATE behavior_memories
        SET scope_type = CASE
            WHEN learner_goal_id IS NULL THEN 'profile_global'
            ELSE 'goal_scoped'
        END,
        goal_relevance_score = CASE
            WHEN learner_goal_id IS NULL THEN 0.5
            ELSE 1.0
        END,
        last_supported_at = updated_at,
        promotion_state_changed_at = updated_at
        """
    )
    op.execute(
        """
        UPDATE knowledge_memory_embeddings
        SET scope_type = CASE
            WHEN learner_goal_id IS NULL THEN 'profile_global'
            ELSE 'goal_scoped'
        END
        """
    )
    op.execute(
        """
        UPDATE behavior_memory_embeddings
        SET scope_type = CASE
            WHEN learner_goal_id IS NULL THEN 'profile_global'
            ELSE 'goal_scoped'
        END
        """
    )

    op.create_table(
        "memory_evidence_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("evidence_source_type", sa.String(length=64), nullable=False),
        sa.Column("evidence_source_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_role", sa.String(length=32), nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_evidence_links_memory",
        "memory_evidence_links",
        ["memory_type", "memory_id", "observed_at"],
    )
    op.create_index(
        "ix_memory_evidence_links_source",
        "memory_evidence_links",
        ["evidence_source_type", "evidence_source_id"],
    )

    op.create_table(
        "memory_governance_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("decision_type", sa.String(length=32), nullable=False),
        sa.Column("trigger_source", sa.String(length=64), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_governance_decisions_memory",
        "memory_governance_decisions",
        ["memory_type", "memory_id", "created_at"],
    )

    op.create_table(
        "memory_annotations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("memory_id", sa.String(length=36), nullable=False),
        sa.Column("annotation_code", sa.String(length=128), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_annotations_memory",
        "memory_annotations",
        ["memory_type", "memory_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_annotations_memory", table_name="memory_annotations")
    op.drop_table("memory_annotations")

    op.drop_index("ix_memory_governance_decisions_memory", table_name="memory_governance_decisions")
    op.drop_table("memory_governance_decisions")

    op.drop_index("ix_memory_evidence_links_source", table_name="memory_evidence_links")
    op.drop_index("ix_memory_evidence_links_memory", table_name="memory_evidence_links")
    op.drop_table("memory_evidence_links")

    for table_name in ("knowledge_memory_embeddings", "behavior_memory_embeddings"):
        op.drop_column(table_name, "scope_type")
        op.drop_column(table_name, "goal_relevance_score")
        op.drop_column(table_name, "stability_score")

    op.drop_column("behavior_memories", "cross_session_recurrence_count")
    op.drop_column("behavior_memories", "intervention_failure_count")
    op.drop_column("behavior_memories", "intervention_success_count")

    op.drop_column("knowledge_memories", "task_evidence_count")
    op.drop_column("knowledge_memories", "assessment_evidence_count")
    op.drop_column("knowledge_memories", "prerequisite_weight")

    for table_name in ("knowledge_memories", "behavior_memories"):
        op.drop_column(table_name, "suppressed_at")
        op.drop_column(table_name, "suppressed_by")
        op.drop_column(table_name, "suppressed_reason_note")
        op.drop_column(table_name, "suppressed_reason_code")
        op.drop_column(table_name, "promotion_state_changed_at")
        op.drop_column(table_name, "last_contradicted_at")
        op.drop_column(table_name, "last_supported_at")
        op.drop_column(table_name, "contradiction_count")
        op.drop_column(table_name, "evidence_count")
        op.drop_column(table_name, "contradiction_score")
        op.drop_column(table_name, "support_score")
        op.drop_column(table_name, "goal_relevance_score")
        op.drop_column(table_name, "stability_score")
        op.drop_column(table_name, "scope_type")
