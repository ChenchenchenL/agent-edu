"""add skill artifact suppression metadata

Revision ID: 0019_skill_suppression_metadata
Revises: 0018_skill_governance
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_skill_suppression_metadata"
down_revision = "0018_skill_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("skill_artifacts", sa.Column("deprecated_by", sa.String(length=128), nullable=True))
    op.add_column("skill_artifacts", sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("skill_artifacts", sa.Column("suppressed_reason_code", sa.String(length=128), nullable=True))
    op.add_column("skill_artifacts", sa.Column("suppressed_reason_note", sa.Text(), nullable=True))
    op.add_column("skill_artifacts", sa.Column("suppressed_by", sa.String(length=128), nullable=True))
    op.add_column("skill_artifacts", sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("skill_artifacts", sa.Column("suppressed_previous_status", sa.String(length=32), nullable=True))
    op.create_index(
        "uq_skill_artifacts_suppressed_name_scope",
        "skill_artifacts",
        ["name", "scope"],
        unique=True,
        postgresql_where=sa.text("status = 'suppressed'"),
        sqlite_where=sa.text("status = 'suppressed'"),
    )


def downgrade() -> None:
    op.drop_index("uq_skill_artifacts_suppressed_name_scope", table_name="skill_artifacts")
    op.drop_column("skill_artifacts", "suppressed_previous_status")
    op.drop_column("skill_artifacts", "suppressed_at")
    op.drop_column("skill_artifacts", "suppressed_by")
    op.drop_column("skill_artifacts", "suppressed_reason_note")
    op.drop_column("skill_artifacts", "suppressed_reason_code")
    op.drop_column("skill_artifacts", "deprecated_at")
    op.drop_column("skill_artifacts", "deprecated_by")
