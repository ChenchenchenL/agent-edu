"""add memory maintenance jobs

Revision ID: 0015_memory_maintenance_jobs
Revises: 0014_long_term_memory_consistency_constraints
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_memory_maintenance_jobs"
down_revision = "0014_long_term_memory_consistency_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_maintenance_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("learner_profile_id", sa.String(length=36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("cursor", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False, unique=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_memory_maintenance_jobs_status_due",
        "memory_maintenance_jobs",
        ["status", "due_at"],
    )
    op.create_index(
        "ix_memory_maintenance_jobs_profile_type_status",
        "memory_maintenance_jobs",
        ["learner_profile_id", "job_type", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_maintenance_jobs_profile_type_status", table_name="memory_maintenance_jobs")
    op.drop_index("ix_memory_maintenance_jobs_status_due", table_name="memory_maintenance_jobs")
    op.drop_table("memory_maintenance_jobs")
