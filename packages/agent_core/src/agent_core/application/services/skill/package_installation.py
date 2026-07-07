from __future__ import annotations

from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.skill import SkillArtifact
from agent_core.domain.entities.skill.package import SkillPackage, TenantSkillPackageInstallation
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.db.repositories.skill import SkillArtifactRepository
from agent_core.infrastructure.db.repositories.skill_package import SkillPackageRepository, TenantSkillPackageInstallationRepository


class TenantSkillPackageInstallationService:
    def __init__(
        self,
        *,
        installation_repository: TenantSkillPackageInstallationRepository,
        package_repository: SkillPackageRepository,
        artifact_repository: SkillArtifactRepository,
        audit_service: AuditService,
    ) -> None:
        self._installation_repository = installation_repository
        self._package_repository = package_repository
        self._artifact_repository = artifact_repository
        self._audit_service = audit_service

    async def install(
        self,
        *,
        learner_profile_id: str,
        package_id: str,
        operator_id: str,
    ) -> TenantSkillPackageInstallation:
        package = await self._package_repository.get_by_id(package_id)
        if package is None:
            raise ValidationError(f"Skill package not found: {package_id}")
        if package.status != "verified":
            raise ValidationError(f"Only verified packages can be installed (current status: {package.status}).")
        if package.kill_switch:
            raise ValidationError("Package has kill switch activated and cannot be installed.")

        existing = await self._installation_repository.get_active_by_profile_and_package(
            learner_profile_id=learner_profile_id, package_id=package_id,
        )
        if existing is not None:
            raise ValidationError(
                f"Active installation already exists for profile={learner_profile_id}, package={package_id}."
            )

        artifact_ids = await self._create_candidate_artifacts(package=package, operator_id=operator_id)

        installation = TenantSkillPackageInstallation.build(
            learner_profile_id=learner_profile_id,
            package_id=package_id,
            installed_by=operator_id,
            created_artifact_ids=artifact_ids,
        )
        installation = await self._installation_repository.create(installation)

        await self._audit_service.record(
            event_type="skill.package.installed",
            resource_type="tenant_skill_package_installation",
            resource_id=installation.id,
            actor=operator_id,
            event_data={
                "learner_profile_id": learner_profile_id,
                "package_id": package_id,
                "package_name": package.name,
                "package_version": package.version,
                "created_artifact_ids": artifact_ids,
            },
        )
        return installation

    async def suppress(
        self,
        *,
        installation_id: str,
        operator_id: str,
        reason_code: str,
    ) -> TenantSkillPackageInstallation:
        installation = await self._installation_repository.get_by_id(installation_id)
        if installation is None:
            raise ValidationError(f"Installation not found: {installation_id}")
        installation = installation.suppress(operator_id=operator_id, reason_code=reason_code)
        await self._installation_repository.update(installation)

        for artifact_id in installation.created_artifact_ids:
            artifact = await self._artifact_repository.get_by_id(artifact_id)
            if artifact is not None and artifact.status in {"active", "stable"}:
                artifact = artifact.mark_suppressed(operator_id=operator_id, reason_code=reason_code, reason_note=f"Package installation suppressed: {installation_id}")
                await self._artifact_repository.update(artifact)

        await self._audit_service.record(
            event_type="skill.package.installation.suppressed",
            resource_type="tenant_skill_package_installation",
            resource_id=installation.id,
            actor=operator_id,
            event_data={"reason_code": reason_code},
        )
        return installation

    async def restore(
        self,
        *,
        installation_id: str,
        operator_id: str,
    ) -> TenantSkillPackageInstallation:
        installation = await self._installation_repository.get_by_id(installation_id)
        if installation is None:
            raise ValidationError(f"Installation not found: {installation_id}")
        installation = installation.restore(operator_id=operator_id)
        await self._installation_repository.update(installation)

        for artifact_id in installation.created_artifact_ids:
            artifact = await self._artifact_repository.get_by_id(artifact_id)
            if artifact is not None and artifact.status == "suppressed":
                artifact = artifact.restore_suppressed(operator_id=operator_id)
                await self._artifact_repository.update(artifact)

        await self._audit_service.record(
            event_type="skill.package.installation.restored",
            resource_type="tenant_skill_package_installation",
            resource_id=installation.id,
            actor=operator_id,
            event_data={},
        )
        return installation

    async def uninstall(
        self,
        *,
        installation_id: str,
        operator_id: str,
    ) -> TenantSkillPackageInstallation:
        installation = await self._installation_repository.get_by_id(installation_id)
        if installation is None:
            raise ValidationError(f"Installation not found: {installation_id}")
        installation = installation.uninstall(operator_id=operator_id)
        await self._installation_repository.update(installation)

        for artifact_id in installation.created_artifact_ids:
            artifact = await self._artifact_repository.get_by_id(artifact_id)
            if artifact is None:
                continue
            if artifact.status in {"active", "stable", "suppressed"}:
                artifact = artifact.mark_deprecated(operator_id=operator_id)
                await self._artifact_repository.update(artifact)

        await self._audit_service.record(
            event_type="skill.package.installation.uninstalled",
            resource_type="tenant_skill_package_installation",
            resource_id=installation.id,
            actor=operator_id,
            event_data={},
        )
        return installation

    async def rollback(
        self,
        *,
        installation_id: str,
        operator_id: str,
    ) -> tuple[TenantSkillPackageInstallation, TenantSkillPackageInstallation]:
        old_installation = await self._installation_repository.get_by_id(installation_id)
        if old_installation is None:
            raise ValidationError(f"Installation not found: {installation_id}")

        package = await self._package_repository.get_by_id(old_installation.package_id)
        if package is None:
            raise ValidationError(f"Skill package not found: {old_installation.package_id}")

        new_installation = TenantSkillPackageInstallation.build(
            learner_profile_id=old_installation.learner_profile_id,
            package_id=old_installation.package_id,
            installed_by=operator_id,
        )
        new_installation = await self._installation_repository.create(new_installation)

        old_installation = old_installation.rollback(
            operator_id=operator_id,
            replacement_installation_id=new_installation.id,
        )
        await self._installation_repository.update(old_installation)

        await self._audit_service.record(
            event_type="skill.package.installation.rolled_back",
            resource_type="tenant_skill_package_installation",
            resource_id=old_installation.id,
            actor=operator_id,
            event_data={
                "replacement_installation_id": new_installation.id,
            },
        )
        return old_installation, new_installation

    async def _create_candidate_artifacts(
        self,
        *,
        package: SkillPackage,
        operator_id: str,
    ) -> list[str]:
        surfaces = package.manifest.get("surfaces", [])
        artifact_ids: list[str] = []
        for surface in surfaces:
            artifact = SkillArtifact.build(
                name=f"{package.provider}_{package.name}",
                version=package.version,
                skill_type="curated",
                scope=surface,
                status="candidate",
                description=f"External skill package: {package.name} v{package.version} from {package.provider}",
                definition={
                    "source": "external_package",
                    "package_id": package.id,
                    "package_name": package.name,
                    "package_provider": package.provider,
                    "directives_contract": package.manifest.get("directives_contract", {}),
                    "input_schema": package.manifest.get("input_schema", {}),
                    "output_schema": package.manifest.get("output_schema", {}),
                },
                runtime_directives=package.manifest.get("directives_contract", {}),
                tool_plan=[],
                compatibility_contract={
                    "surfaces": [surface],
                    "implementation_binding": f"{package.provider}_{package.name}",
                    "input_schema_version": "1.0",
                    "output_schema_version": "1.0",
                    "dynamic_execution": False,
                },
                created_by=operator_id,
            )
            await self._artifact_repository.create(artifact)
            artifact_ids.append(artifact.id)
        return artifact_ids
