from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.entities.skill.package import SkillPackage, TenantSkillPackageInstallation
from agent_core.infrastructure.db.models import SkillPackageModel, TenantSkillPackageInstallationModel


class SkillPackageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: SkillPackage) -> SkillPackage:
        self._session.add(self._to_model(entity))
        await self._session.flush()
        return entity

    async def update(self, entity: SkillPackage) -> None:
        model = await self._session.get(SkillPackageModel, entity.id)
        if model is None:
            return
        model.name = entity.name
        model.provider = entity.provider
        model.version = entity.version
        model.provenance_url = entity.provenance_url
        model.signature_hash = entity.signature_hash
        model.signature_algorithm = entity.signature_algorithm
        model.manifest = dict(entity.manifest)
        model.status = entity.status
        model.sandbox_eval_bundle = dict(entity.sandbox_eval_bundle)
        model.kill_switch = entity.kill_switch
        model.imported_by = entity.imported_by
        model.imported_at = entity.imported_at
        model.verified_at = entity.verified_at
        model.rejected_at = entity.rejected_at
        model.rejected_reason_code = entity.rejected_reason_code
        model.archived_at = entity.archived_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_id(self, package_id: str) -> SkillPackage | None:
        model = await self._session.get(SkillPackageModel, package_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_name_version_provider(self, *, name: str, version: str, provider: str) -> SkillPackage | None:
        result = await self._session.execute(
            select(SkillPackageModel).where(
                SkillPackageModel.name == name,
                SkillPackageModel.version == version,
                SkillPackageModel.provider == provider,
            )
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_status(self, status: str, *, limit: int = 50) -> list[SkillPackage]:
        result = await self._session.execute(
            select(SkillPackageModel)
            .where(SkillPackageModel.status == status)
            .order_by(SkillPackageModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_all(self, *, status: str | None = None, limit: int = 50) -> list[SkillPackage]:
        stmt = select(SkillPackageModel).order_by(SkillPackageModel.created_at.desc()).limit(limit)
        if status is not None:
            stmt = stmt.where(SkillPackageModel.status == status)
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_by_status(self) -> dict[str, int]:
        from sqlalchemy import func
        result = await self._session.execute(
            select(SkillPackageModel.status, func.count()).group_by(SkillPackageModel.status)
        )
        return {row[0]: row[1] for row in result.all()}

    @staticmethod
    def _to_model(entity: SkillPackage) -> SkillPackageModel:
        return SkillPackageModel(
            id=entity.id,
            name=entity.name,
            provider=entity.provider,
            version=entity.version,
            provenance_url=entity.provenance_url,
            signature_hash=entity.signature_hash,
            signature_algorithm=entity.signature_algorithm,
            manifest=dict(entity.manifest),
            status=entity.status,
            sandbox_eval_bundle=dict(entity.sandbox_eval_bundle),
            kill_switch=entity.kill_switch,
            imported_by=entity.imported_by,
            imported_at=entity.imported_at,
            verified_at=entity.verified_at,
            rejected_at=entity.rejected_at,
            rejected_reason_code=entity.rejected_reason_code,
            archived_at=entity.archived_at,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: SkillPackageModel) -> SkillPackage:
        return SkillPackage(
            id=model.id,
            name=model.name,
            provider=model.provider,
            version=model.version,
            provenance_url=model.provenance_url,
            signature_hash=model.signature_hash,
            signature_algorithm=model.signature_algorithm,
            manifest=dict(model.manifest or {}),
            status=model.status,
            sandbox_eval_bundle=dict(model.sandbox_eval_bundle or {}),
            kill_switch=model.kill_switch,
            imported_by=model.imported_by,
            imported_at=model.imported_at,
            verified_at=model.verified_at,
            rejected_at=model.rejected_at,
            rejected_reason_code=model.rejected_reason_code,
            archived_at=model.archived_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class TenantSkillPackageInstallationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: TenantSkillPackageInstallation) -> TenantSkillPackageInstallation:
        self._session.add(self._to_model(entity))
        await self._session.flush()
        return entity

    async def update(self, entity: TenantSkillPackageInstallation) -> None:
        model = await self._session.get(TenantSkillPackageInstallationModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.installed_by = entity.installed_by
        model.installed_at = entity.installed_at
        model.suppressed_at = entity.suppressed_at
        model.suppressed_reason_code = entity.suppressed_reason_code
        model.suppressed_by = entity.suppressed_by
        model.uninstalled_at = entity.uninstalled_at
        model.uninstalled_by = entity.uninstalled_by
        model.rolled_back_at = entity.rolled_back_at
        model.rolled_back_by = entity.rolled_back_by
        model.rollback_source_installation_id = entity.rollback_source_installation_id
        model.created_artifact_ids = list(entity.created_artifact_ids)
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_id(self, installation_id: str) -> TenantSkillPackageInstallation | None:
        model = await self._session.get(TenantSkillPackageInstallationModel, installation_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_active_by_profile_and_package(
        self, *, learner_profile_id: str, package_id: str
    ) -> TenantSkillPackageInstallation | None:
        result = await self._session.execute(
            select(TenantSkillPackageInstallationModel).where(
                TenantSkillPackageInstallationModel.learner_profile_id == learner_profile_id,
                TenantSkillPackageInstallationModel.package_id == package_id,
                TenantSkillPackageInstallationModel.status.in_(("installed", "suppressed")),
            )
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_profile(
        self, learner_profile_id: str, *, status: str | None = None, limit: int = 50
    ) -> list[TenantSkillPackageInstallation]:
        stmt = (
            select(TenantSkillPackageInstallationModel)
            .where(TenantSkillPackageInstallationModel.learner_profile_id == learner_profile_id)
            .order_by(TenantSkillPackageInstallationModel.created_at.desc())
            .limit(limit)
        )
        if status is not None:
            stmt = stmt.where(TenantSkillPackageInstallationModel.status == status)
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_by_package(self, package_id: str, *, limit: int = 50) -> list[TenantSkillPackageInstallation]:
        result = await self._session.execute(
            select(TenantSkillPackageInstallationModel)
            .where(TenantSkillPackageInstallationModel.package_id == package_id)
            .order_by(TenantSkillPackageInstallationModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_all(self, *, profile_id: str | None = None, status: str | None = None, limit: int = 50) -> list[TenantSkillPackageInstallation]:
        stmt = select(TenantSkillPackageInstallationModel).order_by(
            TenantSkillPackageInstallationModel.created_at.desc()
        ).limit(limit)
        if profile_id is not None:
            stmt = stmt.where(TenantSkillPackageInstallationModel.learner_profile_id == profile_id)
        if status is not None:
            stmt = stmt.where(TenantSkillPackageInstallationModel.status == status)
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_active_by_profile(self, learner_profile_id: str) -> int:
        from sqlalchemy import func
        result = await self._session.execute(
            select(func.count()).select_from(TenantSkillPackageInstallationModel).where(
                TenantSkillPackageInstallationModel.learner_profile_id == learner_profile_id,
                TenantSkillPackageInstallationModel.status.in_(("installed", "suppressed")),
            )
        )
        return result.scalar_one()

    async def get_installed_package_ids_for_profile(self, learner_profile_id: str) -> set[str]:
        result = await self._session.execute(
            select(TenantSkillPackageInstallationModel.package_id).where(
                TenantSkillPackageInstallationModel.learner_profile_id == learner_profile_id,
                TenantSkillPackageInstallationModel.status == "installed",
            )
        )
        return {row[0] for row in result.all()}

    @staticmethod
    def _to_model(entity: TenantSkillPackageInstallation) -> TenantSkillPackageInstallationModel:
        return TenantSkillPackageInstallationModel(
            id=entity.id,
            learner_profile_id=entity.learner_profile_id,
            package_id=entity.package_id,
            status=entity.status,
            installed_by=entity.installed_by,
            installed_at=entity.installed_at,
            suppressed_at=entity.suppressed_at,
            suppressed_reason_code=entity.suppressed_reason_code,
            suppressed_by=entity.suppressed_by,
            uninstalled_at=entity.uninstalled_at,
            uninstalled_by=entity.uninstalled_by,
            rolled_back_at=entity.rolled_back_at,
            rolled_back_by=entity.rolled_back_by,
            rollback_source_installation_id=entity.rollback_source_installation_id,
            created_artifact_ids=list(entity.created_artifact_ids),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: TenantSkillPackageInstallationModel) -> TenantSkillPackageInstallation:
        return TenantSkillPackageInstallation(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            package_id=model.package_id,
            status=model.status,
            installed_by=model.installed_by,
            installed_at=model.installed_at,
            suppressed_at=model.suppressed_at,
            suppressed_reason_code=model.suppressed_reason_code,
            suppressed_by=model.suppressed_by,
            uninstalled_at=model.uninstalled_at,
            uninstalled_by=model.uninstalled_by,
            rolled_back_at=model.rolled_back_at,
            rolled_back_by=model.rolled_back_by,
            rollback_source_installation_id=model.rollback_source_installation_id,
            created_artifact_ids=list(model.created_artifact_ids or []),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
