from __future__ import annotations

from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.package_manifest import NormalizedManifest, SkillPackageManifestParser
from agent_core.application.services.skill.package_verification import SkillPackageVerifier
from agent_core.domain.entities.skill.package import SkillPackage
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.db.repositories.skill_package import SkillPackageRepository


class SkillPackageImportService:
    def __init__(
        self,
        *,
        repository: SkillPackageRepository,
        audit_service: AuditService,
        manifest_parser: SkillPackageManifestParser | None = None,
        verifier: SkillPackageVerifier | None = None,
    ) -> None:
        self._repository = repository
        self._audit_service = audit_service
        self._manifest_parser = manifest_parser or SkillPackageManifestParser()
        self._verifier = verifier or SkillPackageVerifier()

    async def import_package(
        self,
        *,
        name: str,
        provider: str,
        version: str,
        manifest: dict[str, Any],
        signature_hash: str,
        signature_algorithm: str = "sha256",
        provenance_url: str | None = None,
        sandbox_eval_bundle: dict[str, Any] | None = None,
        operator_id: str,
    ) -> SkillPackage:
        normalized = self._manifest_parser.parse(manifest, name=name, provider=provider, version=version)

        existing = await self._repository.get_by_name_version_provider(
            name=name, version=version, provider=provider,
        )
        if existing is not None:
            raise ValidationError(
                f"Skill package already exists: {name}@{version} from {provider} (id={existing.id})."
            )

        package = SkillPackage.build(
            name=name,
            provider=provider,
            version=version,
            signature_hash=signature_hash,
            signature_algorithm=signature_algorithm,
            manifest=manifest,
            imported_by=operator_id,
            provenance_url=provenance_url,
            sandbox_eval_bundle=sandbox_eval_bundle,
        )
        package = await self._repository.create(package)

        result = self._verifier.verify(package)
        if result.verified:
            package = package.mark_verified()
        else:
            package = package.mark_rejected(reason_code=result.reason_code)
        await self._repository.update(package)

        await self._audit_service.record(
            event_type="skill.package.imported",
            resource_type="skill_package",
            resource_id=package.id,
            actor=operator_id,
            event_data={
                "name": package.name,
                "provider": package.provider,
                "version": package.version,
                "status": package.status,
                "signature_algorithm": package.signature_algorithm,
                "verification_reason_code": result.reason_code,
                "surfaces": normalized.surfaces,
                "topic_scope": normalized.topic_scope,
            },
        )
        return package

    async def reject_package(
        self,
        *,
        package_id: str,
        operator_id: str,
        reason_code: str,
    ) -> SkillPackage:
        package = await self._repository.get_by_id(package_id)
        if package is None:
            raise ValidationError(f"Skill package not found: {package_id}")
        package = package.mark_rejected(reason_code=reason_code)
        await self._repository.update(package)
        await self._audit_service.record(
            event_type="skill.package.rejected",
            resource_type="skill_package",
            resource_id=package.id,
            actor=operator_id,
            event_data={"reason_code": reason_code, "previous_status": package.status},
        )
        return package

    async def archive_package(
        self,
        *,
        package_id: str,
        operator_id: str,
    ) -> SkillPackage:
        package = await self._repository.get_by_id(package_id)
        if package is None:
            raise ValidationError(f"Skill package not found: {package_id}")
        package = package.mark_archived()
        await self._repository.update(package)
        await self._audit_service.record(
            event_type="skill.package.archived",
            resource_type="skill_package",
            resource_id=package.id,
            actor=operator_id,
            event_data={"previous_status": package.status},
        )
        return package
