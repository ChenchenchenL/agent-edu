from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import (
    get_audit_service,
    get_db_session,
    require_operator_api_key,
)
from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.package_import import SkillPackageImportService
from agent_core.application.services.skill.package_installation import TenantSkillPackageInstallationService
from agent_core.domain.errors import ValidationError
from agent_core.domain.schemas.skill import (
    ImportSkillPackageRequest,
    InstallSkillPackageRequest,
    RejectSkillPackageRequest,
    SkillPackageResponse,
    SuppressInstallationRequest,
    TenantSkillPackageInstallationResponse,
)
from agent_core.infrastructure.db.repositories.skill import SkillArtifactRepository
from agent_core.infrastructure.db.repositories.skill_package import (
    SkillPackageRepository,
    TenantSkillPackageInstallationRepository,
)

router = APIRouter(tags=["skill-packages"])


def _import_service(session: AsyncSession, audit_service: AuditService) -> SkillPackageImportService:
    return SkillPackageImportService(
        repository=SkillPackageRepository(session),
        audit_service=audit_service,
    )


def _installation_service(session: AsyncSession, audit_service: AuditService) -> TenantSkillPackageInstallationService:
    return TenantSkillPackageInstallationService(
        installation_repository=TenantSkillPackageInstallationRepository(session),
        package_repository=SkillPackageRepository(session),
        artifact_repository=SkillArtifactRepository(session),
        audit_service=audit_service,
    )


@router.post("/skill-packages/import", response_model=SkillPackageResponse, status_code=201)
async def import_skill_package(
    body: ImportSkillPackageRequest,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> SkillPackageResponse:
    svc = _import_service(session, audit_service)
    try:
        package = await svc.import_package(
            name=body.name,
            provider=body.provider,
            version=body.version,
            manifest=body.manifest,
            signature_hash=body.signature_hash,
            signature_algorithm=body.signature_algorithm,
            provenance_url=body.provenance_url,
            sandbox_eval_bundle=body.sandbox_eval_bundle,
            operator_id=operator,
        )
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return SkillPackageResponse.model_validate(package)


@router.get("/skill-packages", response_model=list[SkillPackageResponse])
async def list_skill_packages(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[SkillPackageResponse]:
    repo = SkillPackageRepository(session)
    packages = await repo.list_all(status=status, limit=limit)
    return [SkillPackageResponse.model_validate(p) for p in packages]


@router.get("/skill-packages/{package_id}", response_model=SkillPackageResponse)
async def get_skill_package(
    package_id: str,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> SkillPackageResponse:
    repo = SkillPackageRepository(session)
    package = await repo.get_by_id(package_id)
    if package is None:
        raise HTTPException(status_code=404, detail="Skill package not found.")
    return SkillPackageResponse.model_validate(package)


@router.post("/skill-packages/{package_id}/reject", response_model=SkillPackageResponse)
async def reject_skill_package(
    package_id: str,
    body: RejectSkillPackageRequest,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> SkillPackageResponse:
    svc = _import_service(session, audit_service)
    try:
        package = await svc.reject_package(package_id=package_id, operator_id=operator, reason_code=body.reason_code)
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return SkillPackageResponse.model_validate(package)


@router.post("/skill-packages/{package_id}/archive", response_model=SkillPackageResponse)
async def archive_skill_package(
    package_id: str,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> SkillPackageResponse:
    svc = _import_service(session, audit_service)
    try:
        package = await svc.archive_package(package_id=package_id, operator_id=operator)
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return SkillPackageResponse.model_validate(package)


@router.post(
    "/skill-packages/{package_id}/install",
    response_model=TenantSkillPackageInstallationResponse,
    status_code=201,
)
async def install_skill_package(
    package_id: str,
    body: InstallSkillPackageRequest,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> TenantSkillPackageInstallationResponse:
    svc = _installation_service(session, audit_service)
    try:
        installation = await svc.install(
            learner_profile_id=body.learner_profile_id,
            package_id=package_id,
            operator_id=operator,
        )
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return TenantSkillPackageInstallationResponse.model_validate(installation)


@router.get("/skill-package-installations", response_model=list[TenantSkillPackageInstallationResponse])
async def list_installations(
    learner_profile_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[TenantSkillPackageInstallationResponse]:
    repo = TenantSkillPackageInstallationRepository(session)
    installations = await repo.list_all(profile_id=learner_profile_id, status=status, limit=limit)
    return [TenantSkillPackageInstallationResponse.model_validate(i) for i in installations]


@router.get(
    "/skill-package-installations/{installation_id}",
    response_model=TenantSkillPackageInstallationResponse,
)
async def get_installation(
    installation_id: str,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> TenantSkillPackageInstallationResponse:
    repo = TenantSkillPackageInstallationRepository(session)
    installation = await repo.get_by_id(installation_id)
    if installation is None:
        raise HTTPException(status_code=404, detail="Installation not found.")
    return TenantSkillPackageInstallationResponse.model_validate(installation)


@router.post(
    "/skill-package-installations/{installation_id}/suppress",
    response_model=TenantSkillPackageInstallationResponse,
)
async def suppress_installation(
    installation_id: str,
    body: SuppressInstallationRequest,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> TenantSkillPackageInstallationResponse:
    svc = _installation_service(session, audit_service)
    try:
        installation = await svc.suppress(
            installation_id=installation_id, operator_id=operator, reason_code=body.reason_code,
        )
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return TenantSkillPackageInstallationResponse.model_validate(installation)


@router.post(
    "/skill-package-installations/{installation_id}/restore",
    response_model=TenantSkillPackageInstallationResponse,
)
async def restore_installation(
    installation_id: str,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> TenantSkillPackageInstallationResponse:
    svc = _installation_service(session, audit_service)
    try:
        installation = await svc.restore(installation_id=installation_id, operator_id=operator)
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return TenantSkillPackageInstallationResponse.model_validate(installation)


@router.post(
    "/skill-package-installations/{installation_id}/uninstall",
    response_model=TenantSkillPackageInstallationResponse,
)
async def uninstall_installation(
    installation_id: str,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> TenantSkillPackageInstallationResponse:
    svc = _installation_service(session, audit_service)
    try:
        installation = await svc.uninstall(installation_id=installation_id, operator_id=operator)
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return TenantSkillPackageInstallationResponse.model_validate(installation)


@router.post(
    "/skill-package-installations/{installation_id}/rollback",
    response_model=TenantSkillPackageInstallationResponse,
)
async def rollback_installation(
    installation_id: str,
    operator: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
    audit_service: AuditService = Depends(get_audit_service),
) -> TenantSkillPackageInstallationResponse:
    svc = _installation_service(session, audit_service)
    try:
        old, _new = await svc.rollback(installation_id=installation_id, operator_id=operator)
        await session.commit()
    except ValidationError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception:
        await session.rollback()
        raise
    return TenantSkillPackageInstallationResponse.model_validate(old)
