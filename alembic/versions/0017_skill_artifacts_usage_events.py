"""add skill artifacts and usage events

Revision ID: 0017_skill_artifacts_usage_events
Revises: 0016_memory_conflict_explainability
Create Date: 2026-06-01
"""

from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL

from alembic import op
import sqlalchemy as sa


revision = "0017_skill_artifacts_usage_events"
down_revision = "0016_memory_conflict_explainability"
branch_labels = None
depends_on = None


BASELINE_SKILLS = [
    ("explain_concept", "Explain a concept in a structured teaching style.", "chat"),
    ("create_quiz", "Generate a short structured quiz for a learner topic.", "quiz"),
    ("adaptive_hint", "Provide a learner hint adjusted to the current context.", "hint"),
    ("plan_study_path", "Generate a structured study path from a learner goal.", "plan_generation"),
    ("schedule_review", "Create spaced review tasks from completed learning work.", "review_scheduling"),
]


def _baseline_id(name: str, version: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agent-edu/skill-artifact/{name}/{version}"))


def upgrade() -> None:
    op.create_table(
        "skill_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("skill_type", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("runtime_directives", sa.JSON(), nullable=False),
        sa.Column("tool_plan", sa.JSON(), nullable=False),
        sa.Column("source_reflection_ids", sa.JSON(), nullable=False),
        sa.Column("source_memory_ids", sa.JSON(), nullable=False),
        sa.Column("source_proposal_id", sa.String(length=36), sa.ForeignKey("reflection_proposals.id"), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_skill_artifacts_name_version", "skill_artifacts", ["name", "version"], unique=True)
    op.create_index("ix_skill_artifacts_status_name", "skill_artifacts", ["status", "name"])

    op.create_table(
        "skill_usage_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("skill_artifact_id", sa.String(length=36), sa.ForeignKey("skill_artifacts.id"), nullable=True),
        sa.Column("skill_name", sa.String(length=128), nullable=False),
        sa.Column("skill_version", sa.String(length=64), nullable=True),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=True),
        sa.Column("learner_goal_id", sa.String(length=36), sa.ForeignKey("learner_goals.id"), nullable=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("learning_sessions.id"), nullable=True),
        sa.Column("daily_task_id", sa.String(length=36), sa.ForeignKey("daily_tasks.id"), nullable=True),
        sa.Column("workflow_run_id", sa.String(length=36), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("surface", sa.String(length=64), nullable=False),
        sa.Column("topic_key", sa.String(length=255), nullable=True),
        sa.Column("trigger_source", sa.String(length=64), nullable=True),
        sa.Column("outcome_status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("cost_units", sa.Float(), nullable=True),
        sa.Column("input_summary", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_skill_usage_events_artifact_created",
        "skill_usage_events",
        ["skill_artifact_id", "created_at"],
    )
    op.create_index(
        "ix_skill_usage_events_goal_surface_created",
        "skill_usage_events",
        ["learner_goal_id", "surface", "created_at"],
    )
    op.create_index(
        "ix_skill_usage_events_session_created",
        "skill_usage_events",
        ["session_id", "created_at"],
    )

    now = datetime.now(timezone.utc)
    rows = [
        {
            "id": _baseline_id(name, "1.0.0"),
            "name": name,
            "version": "1.0.0",
            "skill_type": "baseline",
            "scope": scope,
            "status": "active",
            "description": description,
            "definition": {"registry_skill": name, "version": "1.0.0"},
            "runtime_directives": {},
            "tool_plan": [],
            "source_reflection_ids": [],
            "source_memory_ids": [],
            "source_proposal_id": None,
            "quality_score": 1.0,
            "created_by": "system_seed",
            "approved_by": "system_baseline",
            "approved_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for name, description, scope in BASELINE_SKILLS
    ]
    op.bulk_insert(sa.table(
        "skill_artifacts",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("version", sa.String),
        sa.column("skill_type", sa.String),
        sa.column("scope", sa.String),
        sa.column("status", sa.String),
        sa.column("description", sa.Text),
        sa.column("definition", sa.JSON),
        sa.column("runtime_directives", sa.JSON),
        sa.column("tool_plan", sa.JSON),
        sa.column("source_reflection_ids", sa.JSON),
        sa.column("source_memory_ids", sa.JSON),
        sa.column("source_proposal_id", sa.String),
        sa.column("quality_score", sa.Float),
        sa.column("created_by", sa.String),
        sa.column("approved_by", sa.String),
        sa.column("approved_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    ), rows)


def downgrade() -> None:
    op.drop_index("ix_skill_usage_events_session_created", table_name="skill_usage_events")
    op.drop_index("ix_skill_usage_events_goal_surface_created", table_name="skill_usage_events")
    op.drop_index("ix_skill_usage_events_artifact_created", table_name="skill_usage_events")
    op.drop_table("skill_usage_events")

    op.drop_index("ix_skill_artifacts_status_name", table_name="skill_artifacts")
    op.drop_index("uq_skill_artifacts_name_version", table_name="skill_artifacts")
    op.drop_table("skill_artifacts")
