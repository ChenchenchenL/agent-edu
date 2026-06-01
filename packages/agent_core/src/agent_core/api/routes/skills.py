from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import (
    get_access_context,
    get_db_session,
    get_skill_candidate_service,
    get_skill_catalog_service,
    get_skill_registry,
    get_skill_resolver,
    get_skill_usage_service,
    require_operator_api_key,
)
from agent_core.application.services.skills import SkillCandidateService, SkillCatalogService, SkillResolver, SkillUsageService
from agent_core.domain.schemas.skill import (
    CreateSkillCandidateFromProposalRequest,
    SkillArtifactResponse,
    SkillDescriptorResponse,
    SkillResolutionResponse,
    SkillUsageEventResponse,
)

router = APIRouter(tags=["skills"])


@router.get(
    "/skills",
    response_model=list[SkillDescriptorResponse],
    dependencies=[Depends(get_access_context)],
)
async def list_skills() -> list[SkillDescriptorResponse]:
    return [SkillDescriptorResponse.model_validate(skill) for skill in get_skill_registry().list_skills()]


@router.get(
    "/skill-artifacts",
    response_model=list[SkillArtifactResponse],
    dependencies=[Depends(require_operator_api_key)],
)
async def list_skill_artifacts(
    status: str | None = Query(default=None, max_length=32),
    name: str | None = Query(default=None, max_length=128),
    scope: str | None = Query(default=None, max_length=64),
    lineage_id: str | None = Query(default=None, max_length=36),
    limit: int = Query(default=50, ge=1, le=200),
    service: SkillCatalogService = Depends(get_skill_catalog_service),
) -> list[SkillArtifactResponse]:
    artifacts = await service.list_artifacts(
        status=status,
        name=name,
        scope=scope,
        lineage_id=lineage_id,
        limit=limit,
    )
    return [SkillArtifactResponse.model_validate(item) for item in artifacts]


@router.post(
    "/skill-artifacts/from-reflection-proposal",
    response_model=SkillArtifactResponse,
    dependencies=[Depends(require_operator_api_key)],
)
async def create_skill_candidate_from_reflection_proposal(
    payload: CreateSkillCandidateFromProposalRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillCandidateService = Depends(get_skill_candidate_service),
) -> SkillArtifactResponse:
    artifact = await service.create_candidate_from_proposal(
        proposal_id=payload.proposal_id,
        operator_id="operator",
    )
    await session.commit()
    return SkillArtifactResponse.model_validate(artifact)


@router.get(
    "/skill-artifacts/{artifact_id}",
    response_model=SkillArtifactResponse,
    dependencies=[Depends(require_operator_api_key)],
)
async def get_skill_artifact(
    artifact_id: str,
    service: SkillCatalogService = Depends(get_skill_catalog_service),
) -> SkillArtifactResponse:
    artifact = await service.get_artifact(artifact_id)
    return SkillArtifactResponse.model_validate(artifact)


@router.get(
    "/skill-artifacts/{artifact_id}/lineage",
    response_model=list[SkillArtifactResponse],
    dependencies=[Depends(require_operator_api_key)],
)
async def list_skill_artifact_lineage(
    artifact_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    service: SkillCatalogService = Depends(get_skill_catalog_service),
) -> list[SkillArtifactResponse]:
    artifacts = await service.list_lineage(artifact_id, limit=limit)
    return [SkillArtifactResponse.model_validate(item) for item in artifacts]


@router.get(
    "/skill-artifacts/{artifact_id}/usage",
    response_model=list[SkillUsageEventResponse],
    dependencies=[Depends(require_operator_api_key)],
)
async def list_skill_artifact_usage(
    artifact_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    service: SkillUsageService = Depends(get_skill_usage_service),
) -> list[SkillUsageEventResponse]:
    events = await service.list_usage_by_artifact(artifact_id, limit=limit)
    return [SkillUsageEventResponse.model_validate(item) for item in events]


@router.get(
    "/skill-usage",
    response_model=list[SkillUsageEventResponse],
    dependencies=[Depends(require_operator_api_key)],
)
async def list_skill_usage(
    artifact_id: str | None = Query(default=None, max_length=36),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    session_id: str | None = Query(default=None, max_length=36),
    surface: str | None = Query(default=None, max_length=64),
    outcome_status: str | None = Query(default=None, max_length=32),
    resolver_status: str | None = Query(default=None, max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    service: SkillUsageService = Depends(get_skill_usage_service),
) -> list[SkillUsageEventResponse]:
    events = await service.list_usage(
        artifact_id=artifact_id,
        learner_goal_id=learner_goal_id,
        session_id=session_id,
        surface=surface,
        outcome_status=outcome_status,
        resolver_status=resolver_status,
        limit=limit,
    )
    return [SkillUsageEventResponse.model_validate(item) for item in events]


@router.get(
    "/skill-resolution",
    response_model=SkillResolutionResponse,
    dependencies=[Depends(require_operator_api_key)],
)
async def resolve_skill(
    skill_name: str = Query(max_length=128),
    surface: str = Query(max_length=64),
    session: AsyncSession = Depends(get_db_session),
) -> SkillResolutionResponse:
    service: SkillResolver = get_skill_resolver(session)
    resolution = await service.resolve(skill_name=skill_name, surface=surface)
    await session.commit()
    return SkillResolutionResponse.model_validate(resolution)
