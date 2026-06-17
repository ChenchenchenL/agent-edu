"""add skill curator recommendations

Revision ID: 0020_skill_curator_recommendations
Revises: 0019_skill_suppression_metadata
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_skill_curator_recommendations"
down_revision = "0019_skill_suppression_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_curator_recommendations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=True),
        sa.Column("skill_name", sa.String(length=128), nullable=False),
        sa.Column("skill_version", sa.String(length=64), nullable=True),
        sa.Column("artifact_status", sa.String(length=32), nullable=True),
        sa.Column("lineage_id", sa.String(length=36), nullable=True),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("surface", sa.String(length=64), nullable=False),
        sa.Column("recommendation_type", sa.String(length=64), nullable=False),
        sa.Column("recommended_action", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=128), nullable=False),
        sa.Column("reason_note", sa.Text(), nullable=True),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("related_artifact_ids", sa.JSON(), nullable=False),
        sa.Column("source_job_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("accepted_by", sa.String(length=128), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", sa.String(length=128), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason_code", sa.String(length=128), nullable=True),
        sa.Column("decision_reason_note", sa.Text(), nullable=True),
        sa.Column("action_result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["artifact_id"], ["skill_artifacts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_skill_curator_recs_status_type_created",
        "skill_curator_recommendations",
        ["status", "recommendation_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_skill_curator_recs_artifact_status_created",
        "skill_curator_recommendations",
        ["artifact_id", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_skill_curator_recs_skill_scope_surface_status",
        "skill_curator_recommendations",
        ["skill_name", "scope", "surface", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_skill_curator_recs_skill_scope_surface_status", table_name="skill_curator_recommendations")
    op.drop_index("ix_skill_curator_recs_artifact_status_created", table_name="skill_curator_recommendations")
    op.drop_index("ix_skill_curator_recs_status_type_created", table_name="skill_curator_recommendations")
    op.drop_table("skill_curator_recommendations")
