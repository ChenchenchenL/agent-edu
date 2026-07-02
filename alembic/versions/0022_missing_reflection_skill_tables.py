"""add missing reflection and skill tables

Revision ID: 0022_missing_reflection_skill_tables
Revises: 0021_memory_promotion_eligibility
Create Date: 2026-07-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_missing_reflection_skill_tables"
down_revision = "0021_memory_promotion_eligibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reflection_evidence_signals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("learning_sessions.id"), nullable=True),
        sa.Column("daily_task_id", sa.String(length=36), sa.ForeignKey("daily_tasks.id"), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("signal_code", sa.String(length=128), nullable=False),
        sa.Column("topic_key", sa.String(length=255), nullable=True),
        sa.Column("severity_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "reflection_outcome_evaluations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("reflection_record_id", sa.String(length=36), sa.ForeignKey("reflection_records.id"), nullable=False, unique=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("topic_key", sa.String(length=255), nullable=True),
        sa.Column("evaluation_status", sa.String(length=32), nullable=False),
        sa.Column("window_size", sa.Integer(), nullable=False),
        sa.Column("observed_attempt_count", sa.Integer(), nullable=False),
        sa.Column("baseline_snapshot", sa.JSON(), nullable=False),
        sa.Column("outcome_snapshot", sa.JSON(), nullable=False),
        sa.Column("improvement_score", sa.Float(), nullable=False),
        sa.Column("evaluation_note", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "reflection_review_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("reflection_record_id", sa.String(length=36), sa.ForeignKey("reflection_records.id"), nullable=False),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=True),
        sa.Column("new_status", sa.String(length=32), nullable=True),
        sa.Column("previous_root_cause", sa.String(length=64), nullable=True),
        sa.Column("new_root_cause", sa.String(length=64), nullable=True),
        sa.Column("previous_action_payload", sa.JSON(), nullable=True),
        sa.Column("new_action_payload", sa.JSON(), nullable=True),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column("operator_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "learner_goal_strategy_cards",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_reflection_ids", sa.JSON(), nullable=False),
        sa.Column("primary_instruction_mode", sa.String(length=32), nullable=False),
        sa.Column("difficulty_bias", sa.String(length=32), nullable=False),
        sa.Column("review_bias", sa.String(length=32), nullable=False),
        sa.Column("replan_bias", sa.String(length=32), nullable=False),
        sa.Column("assessment_bias", sa.String(length=32), nullable=False),
        sa.Column("intervention_policy", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "reflective_memories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("reflection_record_id", sa.String(length=36), sa.ForeignKey("reflection_records.id"), nullable=False),
        sa.Column("memory_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("memory_level", sa.String(length=32), nullable=False),
        sa.Column("importance_score", sa.Float(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("freshness_score", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_reflection_ids", sa.JSON(), nullable=False),
        sa.Column("source_action_ids", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "goal_skill_bindings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("proposal_id", sa.String(length=36), sa.ForeignKey("reflection_proposals.id"), nullable=False),
        sa.Column("rollout_id", sa.String(length=36), sa.ForeignKey("reflection_proposal_rollouts.id"), nullable=False, unique=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("surface", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("match_rules", sa.JSON(), nullable=False),
        sa.Column("runtime_directives", sa.JSON(), nullable=False),
        sa.Column("tool_plan", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("goal_skill_bindings")
    op.drop_table("reflective_memories")
    op.drop_table("learner_goal_strategy_cards")
    op.drop_table("reflection_review_decisions")
    op.drop_table("reflection_outcome_evaluations")
    op.drop_table("reflection_evidence_signals")
