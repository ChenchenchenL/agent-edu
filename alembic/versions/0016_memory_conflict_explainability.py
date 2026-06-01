"""add memory conflict explainability fields

Revision ID: 0016_memory_conflict_explainability
Revises: 0015_memory_maintenance_jobs
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_memory_conflict_explainability"
down_revision = "0015_memory_maintenance_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_conflict_sets",
        sa.Column(
            "reason_code",
            sa.String(length=128),
            nullable=False,
            server_default="contradictory_evidence_threshold",
        ),
    )
    op.add_column("memory_conflict_sets", sa.Column("reason_note", sa.Text(), nullable=True))
    op.add_column(
        "memory_conflict_sets",
        sa.Column(
            "handling_result",
            sa.String(length=128),
            nullable=False,
            server_default="open_review_required",
        ),
    )
    op.add_column(
        "memory_conflict_sets",
        sa.Column("status_impact", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("memory_conflict_sets", "status_impact")
    op.drop_column("memory_conflict_sets", "handling_result")
    op.drop_column("memory_conflict_sets", "reason_note")
    op.drop_column("memory_conflict_sets", "reason_code")
