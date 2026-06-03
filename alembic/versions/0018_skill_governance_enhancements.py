"""add skill governance resolver fields

Revision ID: 0018_skill_governance
Revises: 0017_skill_artifacts_usage_events
Create Date: 2026-06-01
"""

from uuid import NAMESPACE_URL, uuid5

from alembic import op
import sqlalchemy as sa


revision = "0018_skill_governance"
down_revision = "0017_skill_artifacts_usage_events"
branch_labels = None
depends_on = None


def _lineage_id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"agent-edu/skill-lineage/{name}"))


def upgrade() -> None:
    op.add_column("skill_artifacts", sa.Column("lineage_id", sa.String(length=36), nullable=True))
    op.add_column("skill_artifacts", sa.Column("parent_artifact_id", sa.String(length=36), nullable=True))
    op.add_column("skill_artifacts", sa.Column("supersedes_artifact_id", sa.String(length=36), nullable=True))
    op.add_column("skill_artifacts", sa.Column("compatibility_contract", sa.JSON(), nullable=True))
    op.create_foreign_key(
        "fk_skill_artifacts_parent_artifact_id",
        "skill_artifacts",
        "skill_artifacts",
        ["parent_artifact_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_skill_artifacts_supersedes_artifact_id",
        "skill_artifacts",
        "skill_artifacts",
        ["supersedes_artifact_id"],
        ["id"],
    )

    op.add_column("skill_usage_events", sa.Column("skill_status_at_use", sa.String(length=32), nullable=True))
    op.add_column("skill_usage_events", sa.Column("input_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("skill_usage_events", sa.Column("output_fingerprint", sa.String(length=64), nullable=True))
    op.add_column("skill_usage_events", sa.Column("resolver_status", sa.String(length=32), nullable=True))
    op.add_column("skill_usage_events", sa.Column("selection_reason", sa.String(length=64), nullable=True))
    op.add_column("skill_usage_events", sa.Column("outcome_signals", sa.JSON(), nullable=True))

    # env.py runs migrations through AsyncConnection.run_sync, so Alembic exposes
    # a synchronous migration connection here even when the app uses an async engine.
    bind = op.get_bind()
    artifacts = sa.table(
        "skill_artifacts",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("scope", sa.String),
        sa.column("lineage_id", sa.String),
        sa.column("compatibility_contract", sa.JSON),
    )
    rows = bind.execute(sa.select(artifacts.c.id, artifacts.c.name, artifacts.c.scope)).mappings().all()
    for row in rows:
        bind.execute(
            artifacts.update()
            .where(artifacts.c.id == row["id"])
            .values(
                lineage_id=_lineage_id(str(row["name"])),
                compatibility_contract={
                    "surfaces": [str(row["scope"])],
                    "implementation_binding": str(row["name"]),
                    "input_schema_version": "1.0",
                    "output_schema_version": "1.0",
                    "dynamic_execution": False,
                },
            )
        )

    usage_events = sa.table(
        "skill_usage_events",
        sa.column("resolver_status", sa.String),
        sa.column("selection_reason", sa.String),
        sa.column("outcome_signals", sa.JSON),
        sa.column("skill_status_at_use", sa.String),
        sa.column("skill_artifact_id", sa.String),
    )
    bind.execute(
        usage_events.update().values(
            resolver_status=sa.case(
                (usage_events.c.skill_artifact_id.is_(None), "missing_artifact"),
                else_="resolved",
            ),
            selection_reason=sa.case(
                (usage_events.c.skill_artifact_id.is_(None), "artifact_missing_static_fallback"),
                else_="production_default",
            ),
            outcome_signals={},
            skill_status_at_use=sa.case(
                (usage_events.c.skill_artifact_id.is_(None), None),
                else_="active",
            ),
        )
    )

    op.alter_column("skill_artifacts", "lineage_id", nullable=False)
    op.alter_column("skill_artifacts", "compatibility_contract", nullable=False)
    op.alter_column("skill_usage_events", "resolver_status", nullable=False)
    op.alter_column("skill_usage_events", "selection_reason", nullable=False)
    op.alter_column("skill_usage_events", "outcome_signals", nullable=False)

    op.drop_index("uq_skill_artifacts_active_name", table_name="skill_artifacts")
    op.create_index("ix_skill_artifacts_lineage_updated", "skill_artifacts", ["lineage_id", "updated_at"])
    op.create_index(
        "uq_skill_artifacts_selectable_name_scope",
        "skill_artifacts",
        ["name", "scope"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'stable')"),
        sqlite_where=sa.text("status IN ('active', 'stable')"),
    )


def downgrade() -> None:
    op.drop_index("uq_skill_artifacts_selectable_name_scope", table_name="skill_artifacts")
    op.drop_index("ix_skill_artifacts_lineage_updated", table_name="skill_artifacts")
    op.create_index(
        "uq_skill_artifacts_active_name",
        "skill_artifacts",
        ["name"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.drop_column("skill_usage_events", "outcome_signals")
    op.drop_column("skill_usage_events", "selection_reason")
    op.drop_column("skill_usage_events", "resolver_status")
    op.drop_column("skill_usage_events", "output_fingerprint")
    op.drop_column("skill_usage_events", "input_fingerprint")
    op.drop_column("skill_usage_events", "skill_status_at_use")

    op.drop_constraint("fk_skill_artifacts_supersedes_artifact_id", "skill_artifacts", type_="foreignkey")
    op.drop_constraint("fk_skill_artifacts_parent_artifact_id", "skill_artifacts", type_="foreignkey")
    op.drop_column("skill_artifacts", "compatibility_contract")
    op.drop_column("skill_artifacts", "supersedes_artifact_id")
    op.drop_column("skill_artifacts", "parent_artifact_id")
    op.drop_column("skill_artifacts", "lineage_id")
