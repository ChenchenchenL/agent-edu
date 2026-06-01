"""add reflection proposal rollout runtime governance

Revision ID: 0011_reflection_proposal_rollouts
Revises: 0010_reflection_proposal_sandbox_approval
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_reflection_proposal_rollouts"
down_revision = "0010_reflection_proposal_sandbox_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reflection_proposal_rollouts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("proposal_id", sa.String(length=36), sa.ForeignKey("reflection_proposals.id"), nullable=False, unique=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("baseline_snapshot", sa.JSON(), nullable=False),
        sa.Column("runtime_overlay_payload", sa.JSON(), nullable=False),
        sa.Column("latest_observation_id", sa.String(length=36), nullable=True),
        sa.Column("staged_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=True),
        sa.Column("rollback_restored_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=True),
        sa.Column("activated_by", sa.String(length=128), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_reflection_proposal_rollouts_goal_surface",
        "reflection_proposal_rollouts",
        ["learner_goal_id", "surface", "created_at"],
    )

    op.create_table(
        "reflection_proposal_rollout_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("rollout_id", sa.String(length=36), sa.ForeignKey("reflection_proposal_rollouts.id"), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), sa.ForeignKey("reflection_proposals.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("recommendation", sa.String(length=32), nullable=False),
        sa.Column("observed_sample_count", sa.Integer(), nullable=False),
        sa.Column("positive_score", sa.Float(), nullable=False),
        sa.Column("negative_score", sa.Float(), nullable=False),
        sa.Column("signal_summary", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_reflection_proposal_rollout_observations_rollout",
        "reflection_proposal_rollout_observations",
        ["rollout_id", "created_at"],
    )

    op.create_table(
        "reflection_proposal_rollout_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("rollout_id", sa.String(length=36), sa.ForeignKey("reflection_proposal_rollouts.id"), nullable=False),
        sa.Column("proposal_id", sa.String(length=36), sa.ForeignKey("reflection_proposals.id"), nullable=False),
        sa.Column("decision_type", sa.String(length=32), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=False),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_reflection_proposal_rollout_decisions_rollout",
        "reflection_proposal_rollout_decisions",
        ["rollout_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reflection_proposal_rollout_decisions_rollout",
        table_name="reflection_proposal_rollout_decisions",
    )
    op.drop_table("reflection_proposal_rollout_decisions")

    op.drop_index(
        "ix_reflection_proposal_rollout_observations_rollout",
        table_name="reflection_proposal_rollout_observations",
    )
    op.drop_table("reflection_proposal_rollout_observations")

    op.drop_index(
        "ix_reflection_proposal_rollouts_goal_surface",
        table_name="reflection_proposal_rollouts",
    )
    op.drop_table("reflection_proposal_rollouts")
