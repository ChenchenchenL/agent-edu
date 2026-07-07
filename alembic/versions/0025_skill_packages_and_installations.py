"""add skill_packages and tenant_skill_package_installations tables

Revision ID: 0025_skill_packages
Revises: 0024_add_plan_templates
Create Date: 2026-07-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_skill_packages"
down_revision = "0024_add_plan_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_packages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("provenance_url", sa.Text(), nullable=True),
        sa.Column("signature_hash", sa.String(256), nullable=False),
        sa.Column("signature_algorithm", sa.String(16), nullable=False, server_default="sha256"),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("sandbox_eval_bundle", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("kill_switch", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("imported_by", sa.String(128), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_reason_code", sa.String(128), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("uq_skill_packages_name_version_provider", "skill_packages", ["name", "version", "provider"], unique=True)
    op.create_index("ix_skill_packages_status", "skill_packages", ["status"])

    op.create_table(
        "tenant_skill_package_installations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("learner_profile_id", sa.String(36), sa.ForeignKey("learner_profiles.id"), nullable=False),
        sa.Column("package_id", sa.String(36), sa.ForeignKey("skill_packages.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("installed_by", sa.String(128), nullable=False),
        sa.Column("installed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppressed_reason_code", sa.String(128), nullable=True),
        sa.Column("suppressed_by", sa.String(128), nullable=True),
        sa.Column("uninstalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uninstalled_by", sa.String(128), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_by", sa.String(128), nullable=True),
        sa.Column("rollback_source_installation_id", sa.String(36), nullable=True),
        sa.Column("created_artifact_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_tenant_installations_profile_status", "tenant_skill_package_installations", ["learner_profile_id", "status"])
    op.create_index("ix_tenant_installations_package", "tenant_skill_package_installations", ["package_id"])


def downgrade() -> None:
    op.drop_table("tenant_skill_package_installations")
    op.drop_table("skill_packages")
