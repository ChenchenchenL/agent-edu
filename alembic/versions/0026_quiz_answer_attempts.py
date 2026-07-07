"""add session_quiz_answer_attempts table and extend session_quiz_questions

Revision ID: 0026_quiz_answer_attempts
Revises: 0025_skill_packages
Create Date: 2026-07-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_quiz_answer_attempts"
down_revision = "0025_skill_packages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "session_quiz_questions",
        sa.Column(
            "question_type",
            sa.String(32),
            nullable=False,
            server_default="open_ended",
        ),
    )
    op.add_column(
        "session_quiz_questions",
        sa.Column(
            "options",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )

    op.create_table(
        "session_quiz_answer_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("learning_sessions.id"),
            nullable=False,
        ),
        sa.Column(
            "quiz_id",
            sa.String(36),
            sa.ForeignKey("session_quizzes.id"),
            nullable=False,
        ),
        sa.Column(
            "question_id",
            sa.String(36),
            sa.ForeignKey("session_quiz_questions.id"),
            nullable=False,
        ),
        sa.Column(
            "learner_profile_id",
            sa.String(36),
            sa.ForeignKey("learner_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "learner_goal_id",
            sa.String(36),
            sa.ForeignKey("learner_goals.id"),
            nullable=True,
        ),
        sa.Column(
            "daily_task_id",
            sa.String(36),
            sa.ForeignKey("daily_tasks.id"),
            nullable=True,
        ),
        sa.Column("topic_key", sa.String(128), nullable=False),
        sa.Column(
            "subskill_keys", sa.JSON(), nullable=False, server_default="[]"
        ),
        sa.Column("question_prompt", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=False),
        sa.Column("learner_answer", sa.Text(), nullable=False),
        sa.Column("grading_status", sa.String(32), nullable=False),
        sa.Column("grading_source", sa.String(32), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rubric_feedback", sa.Text(), nullable=True),
        sa.Column(
            "misconception_codes",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "hint_used",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "hint_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column(
            "metadata", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_quiz_attempts_session_quiz",
        "session_quiz_answer_attempts",
        ["session_id", "quiz_id"],
    )
    op.create_index(
        "ix_quiz_attempts_goal_topic_created",
        "session_quiz_answer_attempts",
        ["learner_goal_id", "topic_key", "created_at"],
    )
    op.create_index(
        "uq_quiz_attempts_question_attempt",
        "session_quiz_answer_attempts",
        ["question_id", "attempt_number"],
        unique=True,
    )
    op.create_index(
        "ix_quiz_attempts_grading_created",
        "session_quiz_answer_attempts",
        ["grading_status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quiz_attempts_grading_created",
        table_name="session_quiz_answer_attempts",
    )
    op.drop_index(
        "uq_quiz_attempts_question_attempt",
        table_name="session_quiz_answer_attempts",
    )
    op.drop_index(
        "ix_quiz_attempts_goal_topic_created",
        table_name="session_quiz_answer_attempts",
    )
    op.drop_index(
        "ix_quiz_attempts_session_quiz",
        table_name="session_quiz_answer_attempts",
    )
    op.drop_table("session_quiz_answer_attempts")
    op.drop_column("session_quiz_questions", "options")
    op.drop_column("session_quiz_questions", "question_type")
