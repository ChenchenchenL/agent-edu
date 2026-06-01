"""add autonomy runtime tables

Revision ID: 0007_autonomy_runtime
Revises: 0006_autonomous_tasks
Create Date: 2026-05-21
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_autonomy_runtime"
down_revision = "0006_autonomous_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "goal_autonomy_states",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False, unique=True),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("current_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=True),
        sa.Column("next_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("availability_snapshot", sa.JSON(), nullable=False),
        sa.Column("mastery_snapshot", sa.JSON(), nullable=False),
        sa.Column("last_transition_reason", sa.String(length=128), nullable=True),
        sa.Column("last_transition_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "autonomy_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_source", sa.String(length=64), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_autonomy_jobs_goal_due", "autonomy_jobs", ["learner_goal_id", "due_at"])
    op.create_index("ix_autonomy_jobs_status_due", "autonomy_jobs", ["status", "due_at"])

    op.create_table(
        "learner_availabilities",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False, unique=True),
        sa.Column("timezone", sa.String(length=64), nullable=True),
        sa.Column("available_days", sa.JSON(), nullable=False),
        sa.Column("time_windows", sa.JSON(), nullable=False),
        sa.Column("max_daily_minutes", sa.Integer(), nullable=True),
        sa.Column("preferred_session_length_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "learner_topic_masteries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("topic_key", sa.String(length=255), nullable=False),
        sa.Column("mastery_score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("last_attempt_status", sa.String(length=32), nullable=True),
        sa.Column("last_assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_learner_topic_masteries_goal_topic", "learner_topic_masteries", ["learner_goal_id", "topic_key"], unique=True)

    op.create_table(
        "task_attempts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("daily_task_id", sa.String(length=36), sa.ForeignKey("daily_tasks.id"), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("execution_session_id", sa.String(length=36), nullable=True),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("topic_focus", sa.String(length=255), nullable=False),
        sa.Column("outcome_status", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_task_attempts_goal_created", "task_attempts", ["learner_goal_id", "created_at"])
    op.create_index("ix_task_attempts_task_id", "task_attempts", ["daily_task_id"])

    op.add_column(
        "workflow_runs",
        sa.Column("scheduled_job_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_workflow_runs_scheduled_job_id",
        "workflow_runs",
        "autonomy_jobs",
        ["scheduled_job_id"],
        ["id"],
    )
    op.create_index("ix_workflow_runs_scheduled_job_id", "workflow_runs", ["scheduled_job_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_runs_scheduled_job_id", table_name="workflow_runs")
    op.drop_constraint("fk_workflow_runs_scheduled_job_id", "workflow_runs", type_="foreignkey")
    op.drop_column("workflow_runs", "scheduled_job_id")

    op.drop_index("ix_task_attempts_task_id", table_name="task_attempts")
    op.drop_index("ix_task_attempts_goal_created", table_name="task_attempts")
    op.drop_table("task_attempts")

    op.drop_index("ix_learner_topic_masteries_goal_topic", table_name="learner_topic_masteries")
    op.drop_table("learner_topic_masteries")

    op.drop_table("learner_availabilities")

    op.drop_index("ix_autonomy_jobs_status_due", table_name="autonomy_jobs")
    op.drop_index("ix_autonomy_jobs_goal_due", table_name="autonomy_jobs")
    op.drop_table("autonomy_jobs")

    op.drop_table("goal_autonomy_states")
