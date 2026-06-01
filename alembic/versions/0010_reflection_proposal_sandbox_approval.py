"""add reflection proposal sandbox and approval governance

Revision ID: 0010_reflection_proposal_sandbox_approval
Revises: 0009_long_term_memory_governance
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_reflection_proposal_sandbox_approval"
down_revision = "0009_long_term_memory_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)")

    op.create_table(
        "reflection_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("daily_task_id", sa.String(length=36), sa.ForeignKey("daily_tasks.id"), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("study_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("trigger_source", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reflection_depth", sa.Integer(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("aggregation_key", sa.String(length=255), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_duplicate_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("primary_root_cause", sa.String(length=64), nullable=False),
        sa.Column("secondary_root_causes", sa.JSON(), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("evidence_summary", sa.Text(), nullable=False),
        sa.Column("recommended_next_step", sa.Text(), nullable=False),
        sa.Column("evidence_payload", sa.JSON(), nullable=False),
        sa.Column("llm_provider", sa.String(length=64), nullable=True),
        sa.Column("llm_model", sa.String(length=128), nullable=True),
        sa.Column("llm_latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reflection_records_goal_status", "reflection_records", ["learner_goal_id", "status"])
    op.create_index("ix_reflection_records_aggregation", "reflection_records", ["aggregation_key", "created_at"])

    op.create_table(
        "reflection_actions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("reflection_record_id", sa.String(length=36), sa.ForeignKey("reflection_records.id"), nullable=False),
        sa.Column("action_type", sa.String(length=64), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("execution_result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_reflection_actions_record", "reflection_actions", ["reflection_record_id", "created_at"])

    op.create_table(
        "reflection_proposals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("reflection_record_id", sa.String(length=36), sa.ForeignKey("reflection_records.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("proposal_type", sa.String(length=64), nullable=False),
        sa.Column("target_scope", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("structured_patch_payload", sa.JSON(), nullable=False),
        sa.Column("expected_improvement", sa.Text(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evaluation_status", sa.String(length=32), nullable=False),
        sa.Column("evaluation_summary", sa.Text(), nullable=True),
        sa.Column("proposal_bundle_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reflection_proposals_goal_status", "reflection_proposals", ["learner_goal_id", "status"])
    op.create_index("ix_reflection_proposals_record", "reflection_proposals", ["reflection_record_id", "created_at"])

    op.create_table(
        "reflection_proposal_evaluations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("proposal_id", sa.String(length=36), sa.ForeignKey("reflection_proposals.id"), nullable=False, unique=True),
        sa.Column("evaluation_status", sa.String(length=32), nullable=False),
        sa.Column("comparison_window_size", sa.Integer(), nullable=False),
        sa.Column("baseline_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("candidate_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("simulated_outcome_summary", sa.JSON(), nullable=False),
        sa.Column("score_delta", sa.Float(), nullable=False),
        sa.Column("evaluator_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column("reflection_proposals", sa.Column("latest_sandbox_run_id", sa.String(length=36), nullable=True))
    op.add_column("reflection_proposals", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reflection_proposals", sa.Column("approved_by", sa.String(length=128), nullable=True))
    op.add_column("reflection_proposals", sa.Column("approval_reason_code", sa.String(length=128), nullable=True))
    op.add_column("reflection_proposals", sa.Column("approval_note", sa.Text(), nullable=True))

    op.add_column("reflection_proposal_evaluations", sa.Column("sandbox_run_id", sa.String(length=36), nullable=True))

    op.create_table(
        "reflection_proposal_sandbox_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("proposal_id", sa.String(length=36), sa.ForeignKey("reflection_proposals.id"), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("sample_source_type", sa.String(length=64), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("evaluator_type", sa.String(length=64), nullable=False),
        sa.Column("baseline_snapshot", sa.JSON(), nullable=False),
        sa.Column("candidate_snapshot", sa.JSON(), nullable=False),
        sa.Column("result_summary", sa.JSON(), nullable=False),
        sa.Column("score_delta", sa.Float(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_reflection_proposal_sandbox_runs_proposal",
        "reflection_proposal_sandbox_runs",
        ["proposal_id", "created_at"],
    )

    op.create_table(
        "reflection_proposal_approval_decisions",
        sa.Column("id", sa.String(length=36), primary_key=True),
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
        "ix_reflection_proposal_approval_decisions_proposal",
        "reflection_proposal_approval_decisions",
        ["proposal_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reflection_proposal_approval_decisions_proposal",
        table_name="reflection_proposal_approval_decisions",
    )
    op.drop_table("reflection_proposal_approval_decisions")

    op.drop_index(
        "ix_reflection_proposal_sandbox_runs_proposal",
        table_name="reflection_proposal_sandbox_runs",
    )
    op.drop_table("reflection_proposal_sandbox_runs")

    op.drop_column("reflection_proposal_evaluations", "sandbox_run_id")

    op.drop_column("reflection_proposals", "approval_note")
    op.drop_column("reflection_proposals", "approval_reason_code")
    op.drop_column("reflection_proposals", "approved_by")
    op.drop_column("reflection_proposals", "approved_at")
    op.drop_column("reflection_proposals", "latest_sandbox_run_id")

    op.drop_table("reflection_proposal_evaluations")

    op.drop_index("ix_reflection_proposals_record", table_name="reflection_proposals")
    op.drop_index("ix_reflection_proposals_goal_status", table_name="reflection_proposals")
    op.drop_table("reflection_proposals")

    op.drop_index("ix_reflection_actions_record", table_name="reflection_actions")
    op.drop_table("reflection_actions")

    op.drop_index("ix_reflection_records_aggregation", table_name="reflection_records")
    op.drop_index("ix_reflection_records_goal_status", table_name="reflection_records")
    op.drop_table("reflection_records")
