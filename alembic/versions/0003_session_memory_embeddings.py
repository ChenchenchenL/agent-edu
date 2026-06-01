"""add session memory embeddings

Revision ID: 0003_session_memory_embeddings
Revises: 0002_session_metadata_and_status
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_session_memory_embeddings"
down_revision = "0002_session_metadata_and_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_memory_embeddings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "memory_event_id",
            sa.String(length=36),
            sa.ForeignKey("session_memory_events.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("learning_sessions.id"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_session_memory_embeddings_session_id", "session_memory_embeddings", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_session_memory_embeddings_session_id", table_name="session_memory_embeddings")
    op.drop_table("session_memory_embeddings")
