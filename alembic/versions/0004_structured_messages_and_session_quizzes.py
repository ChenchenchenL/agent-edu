"""add structured assistant payloads and session quizzes

Revision ID: 0004_struct_msgs_quizzes
Revises: 0003_session_memory_embeddings
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_struct_msgs_quizzes"
down_revision = "0003_session_memory_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_messages",
        sa.Column("content_payload", sa.JSON(), nullable=True),
    )

    op.create_table(
        "session_quizzes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), sa.ForeignKey("learning_sessions.id"), nullable=False),
        sa.Column("topic", sa.String(length=255), nullable=False),
        sa.Column("difficulty", sa.String(length=64), nullable=False),
        sa.Column("question_count", sa.Integer(), nullable=False),
        sa.Column("skill_trace", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_session_quizzes_session_id", "session_quizzes", ["session_id"])

    op.create_table(
        "session_quiz_questions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("quiz_id", sa.String(length=36), sa.ForeignKey("session_quizzes.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
    )
    op.create_index("ix_session_quiz_questions_quiz_id", "session_quiz_questions", ["quiz_id"])


def downgrade() -> None:
    op.drop_index("ix_session_quiz_questions_quiz_id", table_name="session_quiz_questions")
    op.drop_table("session_quiz_questions")
    op.drop_index("ix_session_quizzes_session_id", table_name="session_quizzes")
    op.drop_table("session_quizzes")
    op.drop_column("session_messages", "content_payload")
