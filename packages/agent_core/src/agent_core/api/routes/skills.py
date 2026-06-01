from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from agent_core.api.dependencies import (
    get_skill_catalog_service,
    get_skill_registry,
    get_skill_usage_service,
    require_operator_api_key,
)
from agent_core.application.services.skills import SkillCatalogService, SkillUsageService
from agent_core.domain.schemas.skill import SkillArtifactResponse, SkillDescriptorResponse, SkillUsageEventResponse

router = APIRouter(tags=["skills"])


@router.get("/skills", response_model=list[SkillDescriptorResponse])
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
    limit: int = Query(default=50, ge=1, le=200),
    service: SkillCatalogService = Depends(get_skill_catalog_service),
) -> list[SkillArtifactResponse]:
    artifacts = await service.list_artifacts(status=status, name=name, limit=limit)
    return [SkillArtifactResponse.model_validate(item) for item in artifacts]


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
    learner_goal_id: str | None = Query(default=None, max_length=36),
    session_id: str | None = Query(default=None, max_length=36),
    surface: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    service: SkillUsageService = Depends(get_skill_usage_service),
) -> list[SkillUsageEventResponse]:
    events = await service.list_usage(
        learner_goal_id=learner_goal_id,
        session_id=session_id,
        surface=surface,
        limit=limit,
    )
    return [SkillUsageEventResponse.model_validate(item) for item in events]
