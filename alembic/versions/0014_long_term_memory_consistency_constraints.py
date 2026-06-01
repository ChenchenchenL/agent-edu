"""add long-term memory consistency constraints

Revision ID: 0014_long_term_memory_consistency_constraints
Revises: 0013_long_term_memory_materialization_boundaries
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_long_term_memory_consistency_constraints"
down_revision = "0013_long_term_memory_materialization_boundaries"
branch_labels = None
depends_on = None

CURRENT_MEMORY_STATUSES = ("candidate", "active", "stable", "suppressed")


def _duplicate_count(query: str) -> int:
    bind = op.get_bind()
    return int(bind.execute(sa.text(query)).scalar_one() or 0)


def _assert_no_duplicates(*, label: str, query: str, cleanup_hint: str) -> None:
    count = _duplicate_count(query)
    if count:
        raise RuntimeError(
            f"Cannot add long-term memory consistency constraint for {label}: "
            f"found {count} duplicate identity group(s). {cleanup_hint}"
        )


def _current_status_predicate() -> str:
    values = ", ".join(f"'{status}'" for status in CURRENT_MEMORY_STATUSES)
    return f"status IN ({values})"


def upgrade() -> None:
    current_statuses = _current_status_predicate()
    _assert_no_duplicates(
        label="knowledge memory current identity",
        query=f"""
            SELECT COUNT(*) FROM (
                SELECT learner_profile_id, COALESCE(learner_goal_id, '') AS learner_goal_key,
                       knowledge_key, semantic_category
                FROM knowledge_memories
                WHERE {current_statuses}
                GROUP BY learner_profile_id, COALESCE(learner_goal_id, ''), knowledge_key, semantic_category
                HAVING COUNT(*) > 1
            ) duplicates
        """,
        cleanup_hint=(
            "Resolve duplicates by leaving at most one candidate/active/stable/suppressed "
            "knowledge memory per profile, goal, key, and semantic category."
        ),
    )
    _assert_no_duplicates(
        label="behavior memory current identity",
        query=f"""
            SELECT COUNT(*) FROM (
                SELECT learner_profile_id, COALESCE(learner_goal_id, '') AS learner_goal_key,
                       behavior_key, behavior_category
                FROM behavior_memories
                WHERE {current_statuses}
                GROUP BY learner_profile_id, COALESCE(learner_goal_id, ''), behavior_key, behavior_category
                HAVING COUNT(*) > 1
            ) duplicates
        """,
        cleanup_hint=(
            "Resolve duplicates by leaving at most one candidate/active/stable/suppressed "
            "behavior memory per profile, goal, key, and behavior category."
        ),
    )
    _assert_no_duplicates(
        label="memory evidence link identity",
        query="""
            SELECT COUNT(*) FROM (
                SELECT memory_type, memory_id, evidence_source_type, evidence_source_id, evidence_role
                FROM memory_evidence_links
                GROUP BY memory_type, memory_id, evidence_source_type, evidence_source_id, evidence_role
                HAVING COUNT(*) > 1
            ) duplicates
        """,
        cleanup_hint=(
            "Resolve duplicates by leaving at most one evidence link per memory, source, and role."
        ),
    )
    _assert_no_duplicates(
        label="open memory conflict set identity",
        query="""
            SELECT COUNT(*) FROM (
                SELECT learner_profile_id, COALESCE(learner_goal_id, '') AS learner_goal_key,
                       topic_key, conflict_type
                FROM memory_conflict_sets
                WHERE status = 'open'
                GROUP BY learner_profile_id, COALESCE(learner_goal_id, ''), topic_key, conflict_type
                HAVING COUNT(*) > 1
            ) duplicates
        """,
        cleanup_hint=(
            "Resolve duplicates by leaving at most one open conflict set per profile, goal, topic, and type."
        ),
    )

    op.create_index(
        "uq_knowledge_memories_current_identity",
        "knowledge_memories",
        [
            "learner_profile_id",
            sa.text("COALESCE(learner_goal_id, '')"),
            "knowledge_key",
            "semantic_category",
        ],
        unique=True,
        postgresql_where=sa.text(current_statuses),
        sqlite_where=sa.text(current_statuses),
    )
    op.create_index(
        "uq_behavior_memories_current_identity",
        "behavior_memories",
        [
            "learner_profile_id",
            sa.text("COALESCE(learner_goal_id, '')"),
            "behavior_key",
            "behavior_category",
        ],
        unique=True,
        postgresql_where=sa.text(current_statuses),
        sqlite_where=sa.text(current_statuses),
    )
    op.create_index(
        "uq_memory_evidence_links_identity",
        "memory_evidence_links",
        ["memory_type", "memory_id", "evidence_source_type", "evidence_source_id", "evidence_role"],
        unique=True,
    )
    op.create_index(
        "uq_memory_conflict_sets_open_identity",
        "memory_conflict_sets",
        [
            "learner_profile_id",
            sa.text("COALESCE(learner_goal_id, '')"),
            "topic_key",
            "conflict_type",
        ],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        sqlite_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index("uq_memory_conflict_sets_open_identity", table_name="memory_conflict_sets")
    op.drop_index("uq_memory_evidence_links_identity", table_name="memory_evidence_links")
    op.drop_index("uq_behavior_memories_current_identity", table_name="behavior_memories")
    op.drop_index("uq_knowledge_memories_current_identity", table_name="knowledge_memories")
