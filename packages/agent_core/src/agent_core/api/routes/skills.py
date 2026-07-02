from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import (
    get_access_context,
    get_audit_service,
    get_db_session,
    get_skill_artifact_lifecycle_service,
    get_skill_candidate_service,
    get_skill_catalog_service,
    get_skill_curator_recommendation_service,
    get_skill_replacement_readiness_service,
    get_skill_registry,
    get_skill_replacement_staging_service,
    get_skill_resolver,
    get_skill_usage_service,
    get_runtime_explain_service,
    require_operator_api_key,
)
from agent_core.application.services.audit import AuditService
from agent_core.application.services.skills import (
    SkillArtifactLifecycleService,
    SkillCandidateService,
    SkillCatalogService,
    SkillCuratorRecommendationService,
    SkillReplacementReadinessService,
    SkillReplacementStagingService,
    SkillResolver,
    SkillUsageService,
    RuntimeExplainService,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.schemas.skill import (
    AcceptSkillCuratorRecommendationRequest,
    ArchiveSkillArtifactRequest,
    ActivateSkillArtifactRequest,
    CreateSkillCandidateFromProposalRequest,
    DeactivateSkillArtifactRequest,
    DismissSkillCuratorRecommendationRequest,
    ReplaceSkillArtifactRequest,
    RestoreSkillArtifactRequest,
    SkillArtifactResponse,
    SkillCuratorRecommendationResponse,
    SkillDescriptorResponse,
    SkillReplacementReadinessResponse,
    SkillResolutionResponse,
    StageSkillArtifactRequest,
    StageSkillReplacementFromProposalRequest,
    StabilizeSkillArtifactRequest,
    SuppressSkillArtifactRequest,
    SkillUsageEventResponse,
    RuntimeBindingExplainResponse,
)

router = APIRouter(tags=["skills"])


@router.get(
    "/skills",
    response_model=list[SkillDescriptorResponse],
    dependencies=[Depends(get_access_context)],
)
async def list_skills(
    registry: SkillRegistry = Depends(get_skill_registry),
) -> list[SkillDescriptorResponse]:
    return [SkillDescriptorResponse.model_validate(skill) for skill in registry.list_skills()]


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


@router.get(
    "/skill-curator-recommendations",
    response_model=list[SkillCuratorRecommendationResponse],
    dependencies=[Depends(require_operator_api_key)],
)
async def list_skill_curator_recommendations(
    status: str | None = Query(default=None, max_length=32),
    recommendation_type: str | None = Query(default=None, max_length=64),
    recommended_action: str | None = Query(default=None, max_length=64),
    artifact_id: str | None = Query(default=None, max_length=36),
    skill_name: str | None = Query(default=None, max_length=128),
    scope: str | None = Query(default=None, max_length=64),
    surface: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    service: SkillCuratorRecommendationService = Depends(get_skill_curator_recommendation_service),
) -> list[SkillCuratorRecommendationResponse]:
    recommendations = await service.list_recommendations(
        status=status,
        recommendation_type=recommendation_type,
        recommended_action=recommended_action,
        artifact_id=artifact_id,
        skill_name=skill_name,
        scope=scope,
        surface=surface,
        limit=limit,
    )
    return [SkillCuratorRecommendationResponse.model_validate(item) for item in recommendations]


@router.get(
    "/skill-curator-recommendations/{recommendation_id}",
    response_model=SkillCuratorRecommendationResponse,
    dependencies=[Depends(require_operator_api_key)],
)
async def get_skill_curator_recommendation(
    recommendation_id: str,
    service: SkillCuratorRecommendationService = Depends(get_skill_curator_recommendation_service),
) -> SkillCuratorRecommendationResponse:
    recommendation = await service.get_recommendation(recommendation_id)
    return SkillCuratorRecommendationResponse.model_validate(recommendation)


@router.post(
    "/skill-curator-recommendations/{recommendation_id}/accept",
    response_model=SkillCuratorRecommendationResponse,
)
async def accept_skill_curator_recommendation(
    recommendation_id: str,
    payload: AcceptSkillCuratorRecommendationRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillCuratorRecommendationService = Depends(get_skill_curator_recommendation_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillCuratorRecommendationResponse:
    try:
        recommendation = await service.accept_recommendation(
            recommendation_id=recommendation_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillCuratorRecommendationResponse.model_validate(recommendation)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/skill-curator-recommendations/{recommendation_id}/dismiss",
    response_model=SkillCuratorRecommendationResponse,
)
async def dismiss_skill_curator_recommendation(
    recommendation_id: str,
    payload: DismissSkillCuratorRecommendationRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillCuratorRecommendationService = Depends(get_skill_curator_recommendation_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillCuratorRecommendationResponse:
    try:
        recommendation = await service.dismiss_recommendation(
            recommendation_id=recommendation_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillCuratorRecommendationResponse.model_validate(recommendation)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/skill-artifacts/from-reflection-proposal",
    response_model=SkillArtifactResponse,
)
async def create_skill_candidate_from_reflection_proposal(
    payload: CreateSkillCandidateFromProposalRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillCandidateService = Depends(get_skill_candidate_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    artifact = await service.create_candidate_from_proposal(
        proposal_id=payload.proposal_id,
        operator_id=operator_id,
    )
    await session.commit()
    return SkillArtifactResponse.model_validate(artifact)


@router.post(
    "/skill-artifacts/staged-replacements/from-reflection-proposal",
    response_model=SkillArtifactResponse,
)
async def stage_skill_replacement_from_reflection_proposal(
    payload: StageSkillReplacementFromProposalRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillReplacementStagingService = Depends(get_skill_replacement_staging_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    try:
        artifact = await service.stage_replacement_from_proposal(
            proposal_id=payload.proposal_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillArtifactResponse.model_validate(artifact)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/skill-artifacts/{artifact_id}/stage",
    response_model=SkillArtifactResponse,
)
async def stage_skill_artifact(
    artifact_id: str,
    payload: StageSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    artifact = await service.stage_candidate(
        artifact_id=artifact_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return SkillArtifactResponse.model_validate(artifact)


@router.post(
    "/skill-artifacts/{artifact_id}/activate",
    response_model=SkillArtifactResponse,
)
async def activate_skill_artifact(
    artifact_id: str,
    payload: ActivateSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    artifact = await service.activate_staged(
        artifact_id=artifact_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return SkillArtifactResponse.model_validate(artifact)


@router.post(
    "/skill-artifacts/{artifact_id}/replace",
    response_model=SkillArtifactResponse,
)
async def replace_skill_artifact(
    artifact_id: str,
    payload: ReplaceSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    try:
        artifact = await service.replace_selectable(
            artifact_id=artifact_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillArtifactResponse.model_validate(artifact)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/skill-artifacts/{artifact_id}/stabilize",
    response_model=SkillArtifactResponse,
)
async def stabilize_skill_artifact(
    artifact_id: str,
    payload: StabilizeSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    artifact = await service.stabilize_active(
        artifact_id=artifact_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return SkillArtifactResponse.model_validate(artifact)


@router.post(
    "/skill-artifacts/{artifact_id}/suppress",
    response_model=SkillArtifactResponse,
)
async def suppress_skill_artifact(
    artifact_id: str,
    payload: SuppressSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    try:
        artifact = await service.suppress_selectable(
            artifact_id=artifact_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillArtifactResponse.model_validate(artifact)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/skill-artifacts/{artifact_id}/restore",
    response_model=SkillArtifactResponse,
)
async def restore_skill_artifact(
    artifact_id: str,
    payload: RestoreSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    try:
        artifact = await service.restore_suppressed(
            artifact_id=artifact_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillArtifactResponse.model_validate(artifact)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/skill-artifacts/{artifact_id}/archive",
    response_model=SkillArtifactResponse,
)
async def archive_skill_artifact(
    artifact_id: str,
    payload: ArchiveSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    try:
        artifact = await service.archive_deprecated(
            artifact_id=artifact_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillArtifactResponse.model_validate(artifact)
    except Exception:
        await session.rollback()
        raise


@router.post(
    "/skill-artifacts/{artifact_id}/deactivate",
    response_model=SkillArtifactResponse,
)
async def deactivate_skill_artifact(
    artifact_id: str,
    payload: DeactivateSkillArtifactRequest,
    session: AsyncSession = Depends(get_db_session),
    service: SkillArtifactLifecycleService = Depends(get_skill_artifact_lifecycle_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillArtifactResponse:
    try:
        artifact = await service.deactivate_active(
            artifact_id=artifact_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return SkillArtifactResponse.model_validate(artifact)
    except Exception:
        await session.rollback()
        raise


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
    "/skill-artifacts/{artifact_id}/replacement-readiness",
    response_model=SkillReplacementReadinessResponse,
    dependencies=[Depends(require_operator_api_key)],
)
async def get_skill_artifact_replacement_readiness(
    artifact_id: str,
    service: SkillReplacementReadinessService = Depends(get_skill_replacement_readiness_service),
) -> SkillReplacementReadinessResponse:
    readiness = await service.get_replacement_readiness(artifact_id=artifact_id)
    return SkillReplacementReadinessResponse.model_validate(readiness)


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
    "/skill-runtime-binding/explain",
    response_model=RuntimeBindingExplainResponse,
    dependencies=[Depends(require_operator_api_key)],
)
async def explain_runtime_binding(
    skill_name: str = Query(..., max_length=128),
    surface: str = Query(..., max_length=64),
    learner_goal_id: str | None = Query(default=None, max_length=36),
    topic_key: str | None = Query(default=None, max_length=128),
    task_type: str | None = Query(default=None, max_length=64),
    trigger_source: str | None = Query(default=None, max_length=64),
    include_staged: bool = Query(default=False),
    service: RuntimeExplainService = Depends(get_runtime_explain_service),
) -> RuntimeBindingExplainResponse:
    result = await service.explain(
        learner_goal_id=learner_goal_id,
        skill_name=skill_name,
        surface=surface,
        topic_key=topic_key,
        task_type=task_type,
        trigger_source=trigger_source,
        include_staged=include_staged,
    )
    return RuntimeBindingExplainResponse.model_validate(result)


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
)
async def resolve_skill(
    skill_name: str = Query(max_length=128),
    surface: str = Query(max_length=64),
    audit: bool = Query(default=False),
    session: AsyncSession = Depends(get_db_session),
    service: SkillResolver = Depends(get_skill_resolver),
    audit_service: AuditService = Depends(get_audit_service),
    operator_id: str = Depends(require_operator_api_key),
) -> SkillResolutionResponse:
    resolution = await service.resolve(skill_name=skill_name, surface=surface, audit=audit)
    if audit:
        await audit_service.record(
            event_type="skill.resolution.probed",
            resource_type="skill",
            resource_id=resolution.artifact_id,
            actor=operator_id,
            event_data={
                "skill_name": resolution.skill_name,
                "surface": resolution.surface,
                "resolver_status": resolution.resolver_status,
                "selection_reason": resolution.selection_reason,
                "artifact_id": resolution.artifact_id,
                "operator_id": operator_id,
                "audit_resolution": audit,
            },
        )
    await session.commit()
    return SkillResolutionResponse.model_validate(resolution)
