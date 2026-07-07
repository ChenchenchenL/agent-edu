from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError


SKILL_PACKAGE_STATUSES = {
    "imported",
    "verified",
    "rejected",
    "archived",
}

SKILL_PACKAGE_INSTALLATION_STATUSES = {
    "installed",
    "suppressed",
    "uninstalled",
    "rolled_back",
}

SKILL_PACKAGE_SIGNATURE_ALGORITHMS = {
    "sha256",
    "sha512",
}

SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS = frozenset({
    "surfaces",
    "topic_scope",
    "directives_contract",
    "input_schema",
    "output_schema",
    "tool_permission_profile",
    "compatibility_range",
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(kw_only=True)
class SkillPackage:
    id: str
    name: str
    provider: str
    version: str
    provenance_url: str | None
    signature_hash: str
    signature_algorithm: str
    manifest: dict[str, Any]
    status: str
    sandbox_eval_bundle: dict[str, Any]
    kill_switch: bool
    imported_by: str
    imported_at: datetime
    verified_at: datetime | None
    rejected_at: datetime | None
    rejected_reason_code: str | None
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        name: str,
        provider: str,
        version: str,
        signature_hash: str,
        manifest: dict[str, Any],
        imported_by: str,
        provenance_url: str | None = None,
        signature_algorithm: str = "sha256",
        sandbox_eval_bundle: dict[str, Any] | None = None,
        kill_switch: bool = False,
        status: str = "imported",
        verified_at: datetime | None = None,
        rejected_at: datetime | None = None,
        rejected_reason_code: str | None = None,
        archived_at: datetime | None = None,
    ) -> SkillPackage:
        if not name.strip():
            raise ValidationError("skill package name is required.")
        if not provider.strip():
            raise ValidationError("skill package provider is required.")
        if not version.strip():
            raise ValidationError("skill package version is required.")
        if not signature_hash.strip():
            raise ValidationError("skill package signature_hash is required.")
        if signature_algorithm not in SKILL_PACKAGE_SIGNATURE_ALGORITHMS:
            raise ValidationError("Unsupported signature algorithm.")
        if status not in SKILL_PACKAGE_STATUSES:
            raise ValidationError("Unsupported skill package status.")
        if not imported_by.strip():
            raise ValidationError("imported_by is required.")
        cls._validate_manifest(manifest)
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            name=name,
            provider=provider,
            version=version,
            provenance_url=provenance_url,
            signature_hash=signature_hash,
            signature_algorithm=signature_algorithm,
            manifest=dict(manifest),
            status=status,
            sandbox_eval_bundle=dict(sandbox_eval_bundle or {}),
            kill_switch=kill_switch,
            imported_by=imported_by,
            imported_at=now,
            verified_at=verified_at,
            rejected_at=rejected_at,
            rejected_reason_code=rejected_reason_code,
            archived_at=archived_at,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _validate_manifest(manifest: dict[str, Any]) -> None:
        if not isinstance(manifest, dict):
            raise ValidationError("manifest must be a dict.")
        missing = SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS - set(manifest.keys())
        if missing:
            raise ValidationError(f"manifest missing required keys: {sorted(missing)}")
        surfaces = manifest.get("surfaces")
        if not isinstance(surfaces, list) or not surfaces:
            raise ValidationError("manifest.surfaces must be a non-empty list.")
        for surface in surfaces:
            if not isinstance(surface, str) or not surface.strip():
                raise ValidationError("manifest.surfaces must contain non-empty strings.")
        tool_profile = manifest.get("tool_permission_profile")
        if not isinstance(tool_profile, dict):
            raise ValidationError("manifest.tool_permission_profile must be a dict.")

    def mark_verified(self) -> SkillPackage:
        if self.status not in {"imported", "rejected"}:
            raise ValidationError("Only imported or rejected packages can be verified.")
        now = _utcnow()
        return replace(self, status="verified", verified_at=now, rejected_at=None, rejected_reason_code=None, updated_at=now)

    def mark_rejected(self, *, reason_code: str) -> SkillPackage:
        if self.status not in {"imported", "verified"}:
            raise ValidationError("Only imported or verified packages can be rejected.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        now = _utcnow()
        return replace(self, status="rejected", rejected_at=now, rejected_reason_code=reason_code, updated_at=now)

    def mark_archived(self) -> SkillPackage:
        if self.status not in {"verified", "rejected"}:
            raise ValidationError("Only verified or rejected packages can be archived.")
        now = _utcnow()
        return replace(self, status="archived", archived_at=now, updated_at=now)

    def activate_kill_switch(self) -> SkillPackage:
        if self.status not in {"verified"}:
            raise ValidationError("Kill switch can only be activated on verified packages.")
        return replace(self, kill_switch=True, updated_at=_utcnow())


@dataclass(kw_only=True)
class TenantSkillPackageInstallation:
    id: str
    learner_profile_id: str
    package_id: str
    status: str
    installed_by: str
    installed_at: datetime
    suppressed_at: datetime | None
    suppressed_reason_code: str | None
    suppressed_by: str | None
    uninstalled_at: datetime | None
    uninstalled_by: str | None
    rolled_back_at: datetime | None
    rolled_back_by: str | None
    rollback_source_installation_id: str | None
    created_artifact_ids: list[str]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        learner_profile_id: str,
        package_id: str,
        installed_by: str,
        created_artifact_ids: list[str] | None = None,
        status: str = "installed",
        suppressed_at: datetime | None = None,
        suppressed_reason_code: str | None = None,
        suppressed_by: str | None = None,
        uninstalled_at: datetime | None = None,
        uninstalled_by: str | None = None,
        rolled_back_at: datetime | None = None,
        rolled_back_by: str | None = None,
        rollback_source_installation_id: str | None = None,
    ) -> TenantSkillPackageInstallation:
        if not learner_profile_id.strip():
            raise ValidationError("learner_profile_id is required.")
        if not package_id.strip():
            raise ValidationError("package_id is required.")
        if not installed_by.strip():
            raise ValidationError("installed_by is required.")
        if status not in SKILL_PACKAGE_INSTALLATION_STATUSES:
            raise ValidationError("Unsupported installation status.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            learner_profile_id=learner_profile_id,
            package_id=package_id,
            status=status,
            installed_by=installed_by,
            installed_at=now,
            suppressed_at=suppressed_at,
            suppressed_reason_code=suppressed_reason_code,
            suppressed_by=suppressed_by,
            uninstalled_at=uninstalled_at,
            uninstalled_by=uninstalled_by,
            rolled_back_at=rolled_back_at,
            rolled_back_by=rolled_back_by,
            rollback_source_installation_id=rollback_source_installation_id,
            created_artifact_ids=list(created_artifact_ids or []),
            created_at=now,
            updated_at=now,
        )

    def suppress(self, *, operator_id: str, reason_code: str) -> TenantSkillPackageInstallation:
        if self.status != "installed":
            raise ValidationError("Only installed packages can be suppressed.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not reason_code.strip():
            raise ValidationError("reason_code is required.")
        now = _utcnow()
        return replace(self, status="suppressed", suppressed_at=now, suppressed_reason_code=reason_code, suppressed_by=operator_id, updated_at=now)

    def restore(self, *, operator_id: str) -> TenantSkillPackageInstallation:
        if self.status != "suppressed":
            raise ValidationError("Only suppressed packages can be restored.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        now = _utcnow()
        return replace(self, status="installed", suppressed_at=None, suppressed_reason_code=None, suppressed_by=None, updated_at=now)

    def uninstall(self, *, operator_id: str) -> TenantSkillPackageInstallation:
        if self.status not in {"installed", "suppressed"}:
            raise ValidationError("Only installed or suppressed packages can be uninstalled.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        now = _utcnow()
        return replace(self, status="uninstalled", uninstalled_at=now, uninstalled_by=operator_id, updated_at=now)

    def rollback(self, *, operator_id: str, replacement_installation_id: str) -> TenantSkillPackageInstallation:
        if self.status not in {"installed", "suppressed"}:
            raise ValidationError("Only installed or suppressed packages can be rolled back.")
        if not operator_id.strip():
            raise ValidationError("operator_id is required.")
        if not replacement_installation_id.strip():
            raise ValidationError("replacement_installation_id is required.")
        now = _utcnow()
        return replace(self, status="rolled_back", rolled_back_at=now, rolled_back_by=operator_id, rollback_source_installation_id=replacement_installation_id, updated_at=now)
