"""add session metadata and status management fields

Revision ID: 0002_session_metadata_and_status
Revises: 0001_phase1_bootstrap
Create Date: 2026-05-18
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_session_metadata_and_status"
down_revision = "0001_phase1_bootstrap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "learning_sessions",
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "learning_sessions",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "learning_sessions",
        sa.Column("summary", sa.Text(), nullable=True),
    )

    op.execute("UPDATE learning_sessions SET last_activity_at = created_at WHERE last_activity_at IS NULL;")
    op.alter_column("learning_sessions", "last_activity_at", nullable=False)
    op.alter_column("learning_sessions", "message_count", server_default=None)


def downgrade() -> None:
    op.drop_column("learning_sessions", "summary")
    op.drop_column("learning_sessions", "last_activity_at")
    op.drop_column("learning_sessions", "message_count")
