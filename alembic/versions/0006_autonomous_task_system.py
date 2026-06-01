"""add autonomous task system tables

Revision ID: 0006_autonomous_tasks
Revises: 0005_learner_profiles
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_autonomous_tasks"
down_revision = "0005_learner_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learner_goals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("target_outcome", sa.Text(), nullable=False),
        sa.Column("baseline_note", sa.Text(), nullable=True),
        sa.Column("deadline_date", sa.Date(), nullable=False),
        sa.Column("weekly_study_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_learner_goals_profile_id", "learner_goals", ["learner_profile_id"])

    op.create_table(
        "study_plans",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_source", sa.String(length=64), nullable=False),
        sa.Column("plan_summary", sa.Text(), nullable=False),
        sa.Column("blueprint_payload", sa.JSON(), nullable=False),
        sa.Column("materialized_until_date", sa.Date(), nullable=True),
        sa.Column("supersedes_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_study_plans_goal_version", "study_plans", ["learner_goal_id", "version"])

    op.create_table(
        "plan_stages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("study_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("focus_topics", sa.JSON(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
    )
    op.create_index("ix_plan_stages_plan_position", "plan_stages", ["study_plan_id", "position"])

    op.create_table(
        "daily_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=False),
        sa.Column("study_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=False),
        sa.Column("plan_stage_id", sa.String(length=36), sa.ForeignKey("plan_stages.id"), nullable=True),
        sa.Column("task_origin", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("execution_mode", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("topic_focus", sa.String(length=255), nullable=False),
        sa.Column("difficulty", sa.String(length=64), nullable=True),
        sa.Column("question_count", sa.Integer(), nullable=True),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_task_id", sa.String(length=36), sa.ForeignKey("daily_tasks.id"), nullable=True),
        sa.Column("execution_session_id", sa.String(length=36), nullable=True),
        sa.Column("last_workflow_run_id", sa.String(length=36), nullable=True),
        sa.Column("result_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_daily_tasks_goal_schedule", "daily_tasks", ["learner_goal_id", "scheduled_for"])
    op.create_index("ix_daily_tasks_source_task_id", "daily_tasks", ["source_task_id"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workflow_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trigger_source", sa.String(length=64), nullable=False),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("study_plan_id", sa.String(length=36), sa.ForeignKey("study_plans.id"), nullable=True),
        sa.Column("daily_task_id", sa.String(length=36), sa.ForeignKey("daily_tasks.id"), nullable=True),
        sa.Column("result_resource_type", sa.String(length=64), nullable=True),
        sa.Column("result_resource_ids", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_runs_goal_created", "workflow_runs", ["learner_goal_id", "created_at"])

    op.add_column("learning_sessions", sa.Column("learner_goal_id", sa.String(length=36), nullable=True))
    op.add_column("learning_sessions", sa.Column("daily_task_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_learning_sessions_learner_goal_id",
        "learning_sessions",
        "learner_goals",
        ["learner_goal_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_learning_sessions_daily_task_id",
        "learning_sessions",
        "daily_tasks",
        ["daily_task_id"],
        ["id"],
    )
    op.create_index("ix_learning_sessions_learner_goal_id", "learning_sessions", ["learner_goal_id"])
    op.create_index("ix_learning_sessions_daily_task_id", "learning_sessions", ["daily_task_id"])


def downgrade() -> None:
    op.drop_index("ix_learning_sessions_daily_task_id", table_name="learning_sessions")
    op.drop_index("ix_learning_sessions_learner_goal_id", table_name="learning_sessions")
    op.drop_constraint("fk_learning_sessions_daily_task_id", "learning_sessions", type_="foreignkey")
    op.drop_constraint("fk_learning_sessions_learner_goal_id", "learning_sessions", type_="foreignkey")
    op.drop_column("learning_sessions", "daily_task_id")
    op.drop_column("learning_sessions", "learner_goal_id")

    op.drop_index("ix_workflow_runs_goal_created", table_name="workflow_runs")
    op.drop_table("workflow_runs")

    op.drop_index("ix_daily_tasks_source_task_id", table_name="daily_tasks")
    op.drop_index("ix_daily_tasks_goal_schedule", table_name="daily_tasks")
    op.drop_table("daily_tasks")

    op.drop_index("ix_plan_stages_plan_position", table_name="plan_stages")
    op.drop_table("plan_stages")

    op.drop_index("ix_study_plans_goal_version", table_name="study_plans")
    op.drop_table("study_plans")

    op.drop_index("ix_learner_goals_profile_id", table_name="learner_goals")
    op.drop_table("learner_goals")
