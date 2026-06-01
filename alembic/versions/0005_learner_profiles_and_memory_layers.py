"""add learner profiles and layered memory fields

Revision ID: 0005_learner_profiles
Revises: 0004_struct_msgs_quizzes
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_learner_profiles"
down_revision = "0004_struct_msgs_quizzes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "learner_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.add_column(
        "learning_sessions",
        sa.Column("learner_profile_id", sa.String(length=36), nullable=True),
    )
    op.execute(
        """
        INSERT INTO learner_profiles (id, created_at, updated_at)
        SELECT id, created_at, updated_at
        FROM learning_sessions
        """
    )
    op.execute(
        """
        UPDATE learning_sessions
        SET learner_profile_id = id
        """
    )
    op.alter_column("learning_sessions", "learner_profile_id", nullable=False)
    op.create_foreign_key(
        "fk_learning_sessions_learner_profile_id",
        "learning_sessions",
        "learner_profiles",
        ["learner_profile_id"],
        ["id"],
    )
    op.create_index("ix_learning_sessions_learner_profile_id", "learning_sessions", ["learner_profile_id"])

    op.add_column(
        "session_memory_events",
        sa.Column("learner_profile_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "session_memory_events",
        sa.Column("memory_scope", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "session_memory_events",
        sa.Column("memory_level", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "session_memory_events",
        sa.Column("progress_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "session_memory_events",
        sa.Column("struggle_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "session_memory_events",
        sa.Column("concept_focus", sa.String(length=255), nullable=True),
    )
    op.execute(
        """
        UPDATE session_memory_events sme
        SET learner_profile_id = ls.learner_profile_id,
            memory_scope = 'session',
            memory_level = 'episodic'
        FROM learning_sessions ls
        WHERE sme.session_id = ls.id
        """
    )
    op.alter_column("session_memory_events", "learner_profile_id", nullable=False)
    op.alter_column("session_memory_events", "memory_scope", nullable=False)
    op.alter_column("session_memory_events", "memory_level", nullable=False)
    op.create_foreign_key(
        "fk_session_memory_events_learner_profile_id",
        "session_memory_events",
        "learner_profiles",
        ["learner_profile_id"],
        ["id"],
    )
    op.create_index("ix_session_memory_events_learner_profile_id", "session_memory_events", ["learner_profile_id"])
    op.create_index("ix_session_memory_events_scope_level", "session_memory_events", ["memory_scope", "memory_level"])

    op.add_column(
        "session_memory_embeddings",
        sa.Column("learner_profile_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "session_memory_embeddings",
        sa.Column("memory_scope", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "session_memory_embeddings",
        sa.Column("memory_level", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE session_memory_embeddings sme
        SET learner_profile_id = ls.learner_profile_id,
            memory_scope = 'session',
            memory_level = 'episodic'
        FROM learning_sessions ls
        WHERE sme.session_id = ls.id
        """
    )
    op.alter_column("session_memory_embeddings", "learner_profile_id", nullable=False)
    op.alter_column("session_memory_embeddings", "memory_scope", nullable=False)
    op.alter_column("session_memory_embeddings", "memory_level", nullable=False)
    op.create_foreign_key(
        "fk_session_memory_embeddings_learner_profile_id",
        "session_memory_embeddings",
        "learner_profiles",
        ["learner_profile_id"],
        ["id"],
    )
    op.create_index(
        "ix_session_memory_embeddings_learner_profile_id",
        "session_memory_embeddings",
        ["learner_profile_id"],
    )
    op.create_index(
        "ix_session_memory_embeddings_scope_level",
        "session_memory_embeddings",
        ["memory_scope", "memory_level"],
    )


def downgrade() -> None:
    op.drop_index("ix_session_memory_embeddings_scope_level", table_name="session_memory_embeddings")
    op.drop_index("ix_session_memory_embeddings_learner_profile_id", table_name="session_memory_embeddings")
    op.drop_constraint("fk_session_memory_embeddings_learner_profile_id", "session_memory_embeddings", type_="foreignkey")
    op.drop_column("session_memory_embeddings", "memory_level")
    op.drop_column("session_memory_embeddings", "memory_scope")
    op.drop_column("session_memory_embeddings", "learner_profile_id")

    op.drop_index("ix_session_memory_events_scope_level", table_name="session_memory_events")
    op.drop_index("ix_session_memory_events_learner_profile_id", table_name="session_memory_events")
    op.drop_constraint("fk_session_memory_events_learner_profile_id", "session_memory_events", type_="foreignkey")
    op.drop_column("session_memory_events", "concept_focus")
    op.drop_column("session_memory_events", "struggle_note")
    op.drop_column("session_memory_events", "progress_note")
    op.drop_column("session_memory_events", "memory_level")
    op.drop_column("session_memory_events", "memory_scope")
    op.drop_column("session_memory_events", "learner_profile_id")

    op.drop_index("ix_learning_sessions_learner_profile_id", table_name="learning_sessions")
    op.drop_constraint("fk_learning_sessions_learner_profile_id", "learning_sessions", type_="foreignkey")
    op.drop_column("learning_sessions", "learner_profile_id")

    op.drop_table("learner_profiles")
