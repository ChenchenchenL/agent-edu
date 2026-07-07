"""Tests for Phase 6: External Skill Package Registry and Installation Pipeline."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.package_import import SkillPackageImportService
from agent_core.application.services.skill.package_installation import TenantSkillPackageInstallationService
from agent_core.application.services.skill.package_manifest import SkillPackageManifestParser
from agent_core.application.services.skill.package_verification import SkillPackageVerifier
from agent_core.domain.entities.skill.package import (
    SKILL_PACKAGE_INSTALLATION_STATUSES,
    SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS,
    SKILL_PACKAGE_SIGNATURE_ALGORITHMS,
    SKILL_PACKAGE_STATUSES,
    SkillPackage,
    TenantSkillPackageInstallation,
)
from agent_core.domain.errors import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_manifest(**overrides: Any) -> dict[str, Any]:
    base = {
        "surfaces": ["chat"],
        "topic_scope": "math_basics",
        "directives_contract": {"mode": "guided"},
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "tool_permission_profile": {"allowed_tools": ["Read"]},
        "compatibility_range": {"min_version": "1.0", "max_version": "2.0"},
    }
    base.update(overrides)
    return base


def _compute_hash(manifest: dict[str, Any], algorithm: str = "sha256") -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if algorithm == "sha256":
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return hashlib.sha512(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Stub repositories and services
# ---------------------------------------------------------------------------

class _StubAuditRepo:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def create(self, event: Any) -> Any:
        self.events.append(event)
        return event


class _StubPackageRepo:
    def __init__(self) -> None:
        self.packages: list[SkillPackage] = []

    async def create(self, entity: SkillPackage) -> SkillPackage:
        self.packages.append(entity)
        return entity

    async def update(self, entity: SkillPackage) -> None:
        for i, p in enumerate(self.packages):
            if p.id == entity.id:
                self.packages[i] = entity
                return

    async def get_by_id(self, package_id: str) -> SkillPackage | None:
        for p in self.packages:
            if p.id == package_id:
                return p
        return None

    async def get_by_name_version_provider(self, *, name: str, version: str, provider: str) -> SkillPackage | None:
        for p in self.packages:
            if p.name == name and p.version == version and p.provider == provider:
                return p
        return None

    async def list_all(self, *, status: str | None = None, limit: int = 50) -> list[SkillPackage]:
        result = [p for p in self.packages if status is None or p.status == status]
        return result[:limit]


class _StubArtifactRepo:
    def __init__(self) -> None:
        self.artifacts: list[Any] = []

    async def create(self, entity: Any) -> None:
        self.artifacts.append(entity)

    async def update(self, entity: Any) -> None:
        for i, a in enumerate(self.artifacts):
            if a.id == entity.id:
                self.artifacts[i] = entity
                return

    async def get_by_id(self, artifact_id: str) -> Any | None:
        for a in self.artifacts:
            if a.id == artifact_id:
                return a
        return None


class _StubInstallationRepo:
    def __init__(self) -> None:
        self.installations: list[TenantSkillPackageInstallation] = []

    async def create(self, entity: TenantSkillPackageInstallation) -> TenantSkillPackageInstallation:
        self.installations.append(entity)
        return entity

    async def update(self, entity: TenantSkillPackageInstallation) -> None:
        for i, inst in enumerate(self.installations):
            if inst.id == entity.id:
                self.installations[i] = entity
                return

    async def get_by_id(self, installation_id: str) -> TenantSkillPackageInstallation | None:
        for inst in self.installations:
            if inst.id == installation_id:
                return inst
        return None

    async def get_active_by_profile_and_package(
        self, *, learner_profile_id: str, package_id: str
    ) -> TenantSkillPackageInstallation | None:
        for inst in self.installations:
            if (
                inst.learner_profile_id == learner_profile_id
                and inst.package_id == package_id
                and inst.status in ("installed", "suppressed")
            ):
                return inst
        return None

    async def get_installed_package_ids_for_profile(self, learner_profile_id: str) -> set[str]:
        return {
            inst.package_id
            for inst in self.installations
            if inst.learner_profile_id == learner_profile_id and inst.status == "installed"
        }


def _make_import_service(
    *,
    package_repo: _StubPackageRepo | None = None,
    audit_repo: _StubAuditRepo | None = None,
) -> tuple[SkillPackageImportService, _StubPackageRepo, _StubAuditRepo]:
    pkg_repo = package_repo or _StubPackageRepo()
    aud_repo = audit_repo or _StubAuditRepo()
    svc = SkillPackageImportService(
        repository=pkg_repo,
        audit_service=AuditService(aud_repo),
    )
    return svc, pkg_repo, aud_repo


def _make_installation_service(
    *,
    package_repo: _StubPackageRepo | None = None,
    installation_repo: _StubInstallationRepo | None = None,
    artifact_repo: _StubArtifactRepo | None = None,
    audit_repo: _StubAuditRepo | None = None,
) -> tuple[TenantSkillPackageInstallationService, _StubPackageRepo, _StubInstallationRepo, _StubArtifactRepo, _StubAuditRepo]:
    pkg_repo = package_repo or _StubPackageRepo()
    inst_repo = installation_repo or _StubInstallationRepo()
    art_repo = artifact_repo or _StubArtifactRepo()
    aud_repo = audit_repo or _StubAuditRepo()
    svc = TenantSkillPackageInstallationService(
        installation_repository=inst_repo,
        package_repository=pkg_repo,
        artifact_repository=art_repo,
        audit_service=AuditService(aud_repo),
    )
    return svc, pkg_repo, inst_repo, art_repo, aud_repo


# ===========================================================================
# Domain: SkillPackage
# ===========================================================================


class TestSkillPackageDomain:
    def test_build_valid(self) -> None:
        manifest = _valid_manifest()
        pkg = SkillPackage.build(
            name="math_tutor",
            provider="edu_org",
            version="1.0.0",
            signature_hash="abc123",
            manifest=manifest,
            imported_by="operator:abc",
        )
        assert pkg.status == "imported"
        assert pkg.name == "math_tutor"
        assert pkg.kill_switch is False

    def test_build_missing_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="name is required"):
            SkillPackage.build(
                name="",
                provider="edu_org",
                version="1.0.0",
                signature_hash="abc123",
                manifest=_valid_manifest(),
                imported_by="operator:abc",
            )

    def test_build_missing_signature_rejected(self) -> None:
        with pytest.raises(ValidationError, match="signature_hash is required"):
            SkillPackage.build(
                name="math_tutor",
                provider="edu_org",
                version="1.0.0",
                signature_hash="",
                manifest=_valid_manifest(),
                imported_by="operator:abc",
            )

    def test_build_invalid_algorithm_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Unsupported signature algorithm"):
            SkillPackage.build(
                name="math_tutor",
                provider="edu_org",
                version="1.0.0",
                signature_hash="abc123",
                signature_algorithm="md5",
                manifest=_valid_manifest(),
                imported_by="operator:abc",
            )

    def test_build_missing_manifest_keys_rejected(self) -> None:
        with pytest.raises(ValidationError, match="missing required keys"):
            SkillPackage.build(
                name="math_tutor",
                provider="edu_org",
                version="1.0.0",
                signature_hash="abc123",
                manifest={"surfaces": ["chat"]},
                imported_by="operator:abc",
            )

    def test_mark_verified_from_imported(self) -> None:
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="abc", manifest=_valid_manifest(), imported_by="op",
        )
        verified = pkg.mark_verified()
        assert verified.status == "verified"
        assert verified.verified_at is not None

    def test_mark_rejected_from_imported(self) -> None:
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="abc", manifest=_valid_manifest(), imported_by="op",
        )
        rejected = pkg.mark_rejected(reason_code="signature_mismatch")
        assert rejected.status == "rejected"
        assert rejected.rejected_reason_code == "signature_mismatch"

    def test_mark_archived_from_verified(self) -> None:
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="abc", manifest=_valid_manifest(), imported_by="op",
        )
        archived = pkg.mark_verified().mark_archived()
        assert archived.status == "archived"

    def test_mark_verified_from_archived_rejected(self) -> None:
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="abc", manifest=_valid_manifest(), imported_by="op",
        )
        archived = pkg.mark_verified().mark_archived()
        with pytest.raises(ValidationError):
            archived.mark_verified()

    def test_kill_switch_on_verified(self) -> None:
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="abc", manifest=_valid_manifest(), imported_by="op",
        )
        activated = pkg.mark_verified().activate_kill_switch()
        assert activated.kill_switch is True

    def test_kill_switch_on_imported_rejected(self) -> None:
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="abc", manifest=_valid_manifest(), imported_by="op",
        )
        with pytest.raises(ValidationError):
            pkg.activate_kill_switch()


# ===========================================================================
# Domain: TenantSkillPackageInstallation
# ===========================================================================


class TestInstallationDomain:
    def test_build_valid(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1",
            package_id="pkg-1",
            installed_by="operator:abc",
        )
        assert inst.status == "installed"

    def test_suppress_from_installed(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1", package_id="pkg-1", installed_by="op",
        )
        suppressed = inst.suppress(operator_id="op", reason_code="safety_review")
        assert suppressed.status == "suppressed"
        assert suppressed.suppressed_reason_code == "safety_review"

    def test_restore_from_suppressed(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1", package_id="pkg-1", installed_by="op",
        )
        restored = inst.suppress(operator_id="op", reason_code="review").restore(operator_id="op")
        assert restored.status == "installed"
        assert restored.suppressed_at is None

    def test_uninstall_from_installed(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1", package_id="pkg-1", installed_by="op",
        )
        uninstalled = inst.uninstall(operator_id="op")
        assert uninstalled.status == "uninstalled"

    def test_uninstall_from_suppressed(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1", package_id="pkg-1", installed_by="op",
        )
        uninstalled = inst.suppress(operator_id="op", reason_code="review").uninstall(operator_id="op")
        assert uninstalled.status == "uninstalled"

    def test_rollback(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1", package_id="pkg-1", installed_by="op",
        )
        rolled_back = inst.rollback(operator_id="op", replacement_installation_id="new-inst-1")
        assert rolled_back.status == "rolled_back"
        assert rolled_back.rollback_source_installation_id == "new-inst-1"

    def test_suppress_from_uninstalled_rejected(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1", package_id="pkg-1", installed_by="op",
        )
        uninstalled = inst.uninstall(operator_id="op")
        with pytest.raises(ValidationError):
            uninstalled.suppress(operator_id="op", reason_code="review")

    def test_restore_from_installed_rejected(self) -> None:
        inst = TenantSkillPackageInstallation.build(
            learner_profile_id="profile-1", package_id="pkg-1", installed_by="op",
        )
        with pytest.raises(ValidationError):
            inst.restore(operator_id="op")


# ===========================================================================
# Manifest Parsing
# ===========================================================================


class TestManifestParser:
    def test_parse_valid(self) -> None:
        parser = SkillPackageManifestParser()
        manifest = _valid_manifest()
        result = parser.parse(manifest, name="math_tutor", provider="edu_org", version="1.0.0")
        assert result.surfaces == ["chat"]
        assert result.topic_scope == "math_basics"
        assert "Read" in result.allowed_tools

    def test_parse_missing_keys_rejected(self) -> None:
        parser = SkillPackageManifestParser()
        with pytest.raises(ValidationError, match="missing required keys"):
            parser.parse({"surfaces": ["chat"]}, name="x", provider="y", version="1")

    def test_parse_invalid_surface_rejected(self) -> None:
        parser = SkillPackageManifestParser()
        with pytest.raises(ValidationError, match="unsupported surface"):
            parser.parse(
                _valid_manifest(surfaces=["nonexistent_surface"]),
                name="x", provider="y", version="1",
            )

    def test_parse_disallowed_tool_rejected(self) -> None:
        parser = SkillPackageManifestParser()
        with pytest.raises(ValidationError, match="tools outside allowed set"):
            parser.parse(
                _valid_manifest(tool_permission_profile={"allowed_tools": ["DangerousTool"]}),
                name="x", provider="y", version="1",
            )

    def test_parse_empty_surfaces_rejected(self) -> None:
        parser = SkillPackageManifestParser()
        with pytest.raises(ValidationError, match="non-empty list"):
            parser.parse(
                _valid_manifest(surfaces=[]),
                name="x", provider="y", version="1",
            )


# ===========================================================================
# Signature Verification
# ===========================================================================


class TestSignatureVerification:
    def test_correct_hash_verified(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash=sig_hash, manifest=manifest, imported_by="op",
        )
        result = SkillPackageVerifier().verify(pkg)
        assert result.verified is True
        assert result.reason_code == "signature_valid"

    def test_wrong_hash_rejected(self) -> None:
        manifest = _valid_manifest()
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="wrong_hash_value", manifest=manifest, imported_by="op",
        )
        result = SkillPackageVerifier().verify(pkg)
        assert result.verified is False
        assert result.reason_code == "signature_mismatch"

    def test_sha512_algorithm(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest, algorithm="sha512")
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash=sig_hash, signature_algorithm="sha512",
            manifest=manifest, imported_by="op",
        )
        result = SkillPackageVerifier().verify(pkg)
        assert result.verified is True


# ===========================================================================
# Import Service
# ===========================================================================


class TestImportService:
    @pytest.mark.asyncio
    async def test_import_valid_package(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        svc, pkg_repo, aud_repo = _make_import_service()
        package = await svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )
        assert package.status == "verified"
        assert len(pkg_repo.packages) == 1
        assert len(aud_repo.events) == 1
        assert aud_repo.events[0].event_type == "skill.package.imported"

    @pytest.mark.asyncio
    async def test_import_wrong_signature_rejected(self) -> None:
        manifest = _valid_manifest()
        svc, pkg_repo, aud_repo = _make_import_service()
        package = await svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash="wrong_hash", operator_id="operator:test",
        )
        assert package.status == "rejected"
        assert package.rejected_reason_code == "signature_mismatch"

    @pytest.mark.asyncio
    async def test_import_duplicate_rejected(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        svc, pkg_repo, aud_repo = _make_import_service()
        await svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )
        with pytest.raises(ValidationError, match="already exists"):
            await svc.import_package(
                name="math_tutor", provider="edu_org", version="1.0.0",
                manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
            )

    @pytest.mark.asyncio
    async def test_reject_package(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        svc, pkg_repo, aud_repo = _make_import_service()
        package = await svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )
        rejected = await svc.reject_package(
            package_id=package.id, operator_id="operator:test", reason_code="policy_violation",
        )
        assert rejected.status == "rejected"
        assert rejected.rejected_reason_code == "policy_violation"

    @pytest.mark.asyncio
    async def test_archive_package(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        svc, pkg_repo, aud_repo = _make_import_service()
        package = await svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )
        archived = await svc.archive_package(package_id=package.id, operator_id="operator:test")
        assert archived.status == "archived"


# ===========================================================================
# Installation Service
# ===========================================================================


class TestInstallationService:
    @pytest.mark.asyncio
    async def test_install_verified_package(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        pkg_repo = _StubPackageRepo()
        import_svc, _, _ = _make_import_service(package_repo=pkg_repo)
        package = await import_svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )

        inst_svc, _, inst_repo, art_repo, aud_repo = _make_installation_service(package_repo=pkg_repo)
        installation = await inst_svc.install(
            learner_profile_id="profile-1", package_id=package.id, operator_id="operator:test",
        )
        assert installation.status == "installed"
        assert len(installation.created_artifact_ids) == 1
        assert len(art_repo.artifacts) == 1
        assert art_repo.artifacts[0].status == "candidate"
        assert art_repo.artifacts[0].skill_type == "curated"
        assert len(aud_repo.events) == 1

    @pytest.mark.asyncio
    async def test_install_unverified_package_rejected(self) -> None:
        pkg = SkillPackage.build(
            name="math_tutor", provider="edu_org", version="1.0.0",
            signature_hash="abc", manifest=_valid_manifest(), imported_by="op",
        )
        pkg_repo = _StubPackageRepo()
        pkg_repo.packages.append(pkg)
        inst_svc, _, _, _, _ = _make_installation_service(package_repo=pkg_repo)
        with pytest.raises(ValidationError, match="Only verified"):
            await inst_svc.install(learner_profile_id="profile-1", package_id=pkg.id, operator_id="op")

    @pytest.mark.asyncio
    async def test_install_kill_switched_package_rejected(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        pkg_repo = _StubPackageRepo()
        import_svc, _, _ = _make_import_service(package_repo=pkg_repo)
        package = await import_svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )
        killed = package.activate_kill_switch()
        pkg_repo.packages[0] = killed

        inst_svc, _, _, _, _ = _make_installation_service(package_repo=pkg_repo)
        with pytest.raises(ValidationError, match="kill switch"):
            await inst_svc.install(learner_profile_id="profile-1", package_id=killed.id, operator_id="op")

    @pytest.mark.asyncio
    async def test_duplicate_installation_rejected(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        pkg_repo = _StubPackageRepo()
        import_svc, _, _ = _make_import_service(package_repo=pkg_repo)
        package = await import_svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )

        inst_svc, _, _, _, _ = _make_installation_service(package_repo=pkg_repo)
        await inst_svc.install(learner_profile_id="profile-1", package_id=package.id, operator_id="operator:test")
        with pytest.raises(ValidationError, match="already exists"):
            await inst_svc.install(learner_profile_id="profile-1", package_id=package.id, operator_id="operator:test")

    @pytest.mark.asyncio
    async def test_suppress_and_restore(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        pkg_repo = _StubPackageRepo()
        import_svc, _, _ = _make_import_service(package_repo=pkg_repo)
        package = await import_svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )

        inst_svc, _, inst_repo, _, _ = _make_installation_service(package_repo=pkg_repo)
        installation = await inst_svc.install(
            learner_profile_id="profile-1", package_id=package.id, operator_id="operator:test",
        )
        suppressed = await inst_svc.suppress(
            installation_id=installation.id, operator_id="operator:test", reason_code="safety_review",
        )
        assert suppressed.status == "suppressed"

        restored = await inst_svc.restore(installation_id=suppressed.id, operator_id="operator:test")
        assert restored.status == "installed"

    @pytest.mark.asyncio
    async def test_uninstall(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        pkg_repo = _StubPackageRepo()
        import_svc, _, _ = _make_import_service(package_repo=pkg_repo)
        package = await import_svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )

        inst_svc, _, _, art_repo, _ = _make_installation_service(package_repo=pkg_repo)
        installation = await inst_svc.install(
            learner_profile_id="profile-1", package_id=package.id, operator_id="operator:test",
        )
        uninstalled = await inst_svc.uninstall(installation_id=installation.id, operator_id="operator:test")
        assert uninstalled.status == "uninstalled"

    @pytest.mark.asyncio
    async def test_rollback(self) -> None:
        manifest = _valid_manifest()
        sig_hash = SkillPackageVerifier.compute_signature_hash(manifest=manifest)
        pkg_repo = _StubPackageRepo()
        import_svc, _, _ = _make_import_service(package_repo=pkg_repo)
        package = await import_svc.import_package(
            name="math_tutor", provider="edu_org", version="1.0.0",
            manifest=manifest, signature_hash=sig_hash, operator_id="operator:test",
        )

        inst_svc, _, inst_repo, _, _ = _make_installation_service(package_repo=pkg_repo)
        installation = await inst_svc.install(
            learner_profile_id="profile-1", package_id=package.id, operator_id="operator:test",
        )
        old, new = await inst_svc.rollback(installation_id=installation.id, operator_id="operator:test")
        assert old.status == "rolled_back"
        assert new.status == "installed"
        assert old.rollback_source_installation_id == new.id


# ===========================================================================
# Constants
# ===========================================================================


class TestConstants:
    def test_package_statuses(self) -> None:
        assert "imported" in SKILL_PACKAGE_STATUSES
        assert "verified" in SKILL_PACKAGE_STATUSES
        assert "rejected" in SKILL_PACKAGE_STATUSES
        assert "archived" in SKILL_PACKAGE_STATUSES

    def test_installation_statuses(self) -> None:
        assert "installed" in SKILL_PACKAGE_INSTALLATION_STATUSES
        assert "suppressed" in SKILL_PACKAGE_INSTALLATION_STATUSES
        assert "uninstalled" in SKILL_PACKAGE_INSTALLATION_STATUSES
        assert "rolled_back" in SKILL_PACKAGE_INSTALLATION_STATUSES

    def test_signature_algorithms(self) -> None:
        assert "sha256" in SKILL_PACKAGE_SIGNATURE_ALGORITHMS
        assert "sha512" in SKILL_PACKAGE_SIGNATURE_ALGORITHMS

    def test_manifest_required_keys(self) -> None:
        assert "surfaces" in SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS
        assert "tool_permission_profile" in SKILL_PACKAGE_MANIFEST_REQUIRED_KEYS
