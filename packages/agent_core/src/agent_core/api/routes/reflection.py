from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import (
    AccessContext,
    require_goal_access,
    require_reflection_access,
    require_reflection_proposal_access,
    require_task_access,
)
from agent_core.api.dependencies import (
    get_access_context,
    get_db_session,
    get_goal_skill_binding_resolver,
    get_reflection_governance_service,
    get_reflection_proposal_rollout_service,
    get_reflection_proposal_sandbox_service,
    get_reflection_proposal_service,
    get_reflection_service,
    require_operator_api_key,
)
from agent_core.domain.schemas.reflection_closure import (
    ActivateReflectionProposalRequest,
    ApproveReflectionProposalRequest,
    EnqueueReflectionProposalSandboxRequest,
    GoalSkillBindingResponse,
    ObserveReflectionProposalRolloutRequest,
    ReflectionProposalApprovalDecisionResponse,
    ReflectionProposalEvaluationResponse,
    ReflectionProposalQueueItemResponse,
    ReflectionProposalQueueResponse,
    ReflectionProposalResponse,
    ReflectionProposalRolloutDecisionResponse,
    ReflectionProposalRolloutObservationResponse,
    ReflectionProposalRolloutResponse,
    ReflectionProposalSandboxRunResponse,
    RealizeSkillPatchRequest,
    RejectReflectionProposalRequest,
    RollbackReflectionProposalRolloutRequest,
    PromoteReflectionProposalRolloutRequest,
    ReviewReflectionProposalRequest,
)
from agent_core.domain.schemas.reflection import (
    ReflectionListResponse,
    ReflectionRecordDetailResponse,
    ReflectionActionResponse,
)
from agent_core.domain.schemas.reflection_v2 import (
    OverrideReflectionActionRequest,
    OverrideReflectionRootCauseRequest,
    ReflectionReviewDecisionResponse,
    ReflectionReviewQueueResponse,
    ReviewReflectionRequest,
    ResolveReflectionRequest,
    ActivateReflectionActionRequest,
)
from agent_core.infrastructure.db.repositories import GoalSkillBindingRepository

router = APIRouter(tags=["reflection"])


@router.get("/goals/{goal_id}/reflections", response_model=ReflectionListResponse)
async def list_goal_reflections(
    goal_id: str,
    scope: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> ReflectionListResponse:
    await require_goal_access(goal_id, context, session)
    service = get_reflection_service(session)
    return await service.list_goal_reflections(
        goal_id=goal_id,
        scopes=set(scope) if scope else None,
        statuses=set(status) if status else None,
        limit=limit,
        offset=offset,
    )


@router.get("/tasks/{task_id}/reflections", response_model=ReflectionListResponse)
async def list_task_reflections(
    task_id: str,
    status: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> ReflectionListResponse:
    await require_task_access(task_id, context, session)
    service = get_reflection_service(session)
    return await service.list_task_reflections(
        task_id=task_id,
        statuses=set(status) if status else None,
        limit=limit,
        offset=offset,
    )


@router.get("/reflections/{reflection_id}", response_model=ReflectionRecordDetailResponse)
async def get_reflection(
    reflection_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> ReflectionRecordDetailResponse:
    await require_reflection_access(reflection_id, context, session)
    service = get_reflection_service(session)
    return await service.get_reflection(reflection_id)


@router.get("/reflections/{reflection_id}/outcome-evaluation")
async def get_reflection_outcome_evaluation(
    reflection_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
):
    from agent_core.infrastructure.db.repositories.reflection_outcome_evaluation import ReflectionOutcomeEvaluationRepository
    await require_reflection_access(reflection_id, context, session)
    repo = ReflectionOutcomeEvaluationRepository(session)
    eval = await repo.find_by_reflection(reflection_id)
    if not eval:
        raise HTTPException(status_code=404, detail="Outcome evaluation not found")
    return eval


@router.get("/reflections/{reflection_id}/reviews", response_model=list[ReflectionReviewDecisionResponse])
async def list_reflection_reviews(
    reflection_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[ReflectionReviewDecisionResponse]:
    await require_reflection_access(reflection_id, context, session)
    service = get_reflection_governance_service(session)
    return [ReflectionReviewDecisionResponse.model_validate(item) for item in await service.list_review_decisions(reflection_id)]


@router.get("/reflections/review-queue", response_model=ReflectionReviewQueueResponse)
async def list_reflection_review_queue(
    status: list[str] = Query(default=[]),
    priority_min: float = Query(default=0.0, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000),
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionReviewQueueResponse:
    service = get_reflection_service(session)
    return await service.list_review_queue(
        statuses=set(status) if status else None,
        priority_min=priority_min,
        limit=limit,
        offset=offset,
    )


@router.post("/reflections/{reflection_id}/review", response_model=ReflectionReviewDecisionResponse)
async def review_reflection(
    reflection_id: str,
    payload: ReviewReflectionRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionReviewDecisionResponse:
    service = get_reflection_governance_service(session)
    result = await service.review(
        reflection_id=reflection_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionReviewDecisionResponse.model_validate(result)


@router.post("/reflections/{reflection_id}/resolve", response_model=ReflectionReviewDecisionResponse)
async def resolve_reflection(
    reflection_id: str,
    payload: ResolveReflectionRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionReviewDecisionResponse:
    service = get_reflection_governance_service(session)
    result = await service.resolve(
        reflection_id=reflection_id,
        operator_id=operator_id,
        new_status=payload.new_status,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionReviewDecisionResponse.model_validate(result)


@router.post("/reflections/{reflection_id}/override-root-cause", response_model=ReflectionReviewDecisionResponse)
async def override_reflection_root_cause(
    reflection_id: str,
    payload: OverrideReflectionRootCauseRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionReviewDecisionResponse:
    service = get_reflection_governance_service(session)
    result = await service.override_root_cause(
        reflection_id=reflection_id,
        operator_id=operator_id,
        new_root_cause=payload.new_root_cause,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionReviewDecisionResponse.model_validate(result)


@router.post("/reflections/{reflection_id}/override-action", response_model=ReflectionReviewDecisionResponse)
async def override_reflection_action(
    reflection_id: str,
    payload: OverrideReflectionActionRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionReviewDecisionResponse:
    service = get_reflection_governance_service(session)
    result = await service.override_action(
        reflection_id=reflection_id,
        operator_id=operator_id,
        action_type=payload.action_type,
        payload=payload.payload,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionReviewDecisionResponse.model_validate(result)


@router.post("/reflections/{reflection_id}/actions/{action_id}/activate", response_model=ReflectionActionResponse)
async def activate_reflection_action(
    reflection_id: str,
    action_id: str,
    payload: ActivateReflectionActionRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionActionResponse:
    service = get_reflection_governance_service(session)
    result = await service.activate_action(
        reflection_id=reflection_id,
        action_id=action_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionActionResponse.model_validate(result)


@router.get("/reflections/{reflection_id}/proposals", response_model=list[ReflectionProposalResponse])
async def list_reflection_proposals(
    reflection_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[ReflectionProposalResponse]:
    await require_reflection_access(reflection_id, context, session)
    service = get_reflection_proposal_service(session)
    proposals = await service.list_by_reflection(reflection_id)
    return [ReflectionProposalResponse.model_validate(await service.describe(item)) for item in proposals]


@router.get("/proposals/review-queue", response_model=ReflectionProposalQueueResponse)
async def list_proposal_review_queue(
    status: list[str] = Query(default=[]),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=1000),
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalQueueResponse:
    service = get_reflection_proposal_service(session)
    items, total = await service.list_queue(statuses=set(status) if status else None, limit=limit, offset=offset)
    return ReflectionProposalQueueResponse(
        items=[ReflectionProposalQueueItemResponse.model_validate(await service.describe(item)) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/proposals/{proposal_id}", response_model=ReflectionProposalResponse)
async def get_reflection_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> ReflectionProposalResponse:
    await require_reflection_proposal_access(proposal_id, context, session)
    service = get_reflection_proposal_service(session)
    proposal = await service.get(proposal_id)
    return ReflectionProposalResponse.model_validate(await service.describe(proposal))


@router.get("/proposals/{proposal_id}/evaluation", response_model=ReflectionProposalEvaluationResponse)
async def get_reflection_proposal_evaluation(
    proposal_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalEvaluationResponse:
    service = get_reflection_proposal_service(session)
    return ReflectionProposalEvaluationResponse.model_validate(await service.get_evaluation(proposal_id))


@router.post("/proposals/{proposal_id}/review", response_model=ReflectionProposalResponse)
async def review_reflection_proposal(
    proposal_id: str,
    payload: ReviewReflectionProposalRequest,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalResponse:
    service = get_reflection_proposal_service(session)
    proposal = await service.review(
        proposal_id=proposal_id,
        status=(await service.get(proposal_id)).status,
        evaluation_summary=payload.reason_note or payload.reason_code,
    )
    await session.commit()
    return ReflectionProposalResponse.model_validate(await service.describe(proposal))


@router.post("/proposals/{proposal_id}/sandbox", response_model=ReflectionProposalResponse)
async def enqueue_reflection_proposal_sandbox(
    proposal_id: str,
    payload: EnqueueReflectionProposalSandboxRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalResponse:
    service = get_reflection_proposal_service(session)
    proposal = await service.enqueue_sandbox(
        proposal_id=proposal_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionProposalResponse.model_validate(await service.describe(proposal))


@router.get("/proposals/{proposal_id}/sandbox-runs", response_model=list[ReflectionProposalSandboxRunResponse])
async def list_reflection_proposal_sandbox_runs(
    proposal_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReflectionProposalSandboxRunResponse]:
    service = get_reflection_proposal_sandbox_service(session)
    return [ReflectionProposalSandboxRunResponse.model_validate(item) for item in await service.list_runs(proposal_id)]


@router.get("/sandbox-runs/{sandbox_run_id}", response_model=ReflectionProposalSandboxRunResponse)
async def get_reflection_proposal_sandbox_run(
    sandbox_run_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalSandboxRunResponse:
    service = get_reflection_proposal_sandbox_service(session)
    return ReflectionProposalSandboxRunResponse.model_validate(await service.get_run(sandbox_run_id))


@router.get("/proposals/{proposal_id}/approval-decisions", response_model=list[ReflectionProposalApprovalDecisionResponse])
async def list_reflection_proposal_approval_decisions(
    proposal_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReflectionProposalApprovalDecisionResponse]:
    service = get_reflection_proposal_service(session)
    return [ReflectionProposalApprovalDecisionResponse.model_validate(item) for item in await service.list_approval_decisions(proposal_id)]


@router.post("/proposals/{proposal_id}/approve", response_model=ReflectionProposalResponse)
@router.post("/proposals/{proposal_id}/accept", response_model=ReflectionProposalResponse)
async def approve_reflection_proposal(
    proposal_id: str,
    payload: ApproveReflectionProposalRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalResponse:
    service = get_reflection_proposal_service(session)
    proposal = await service.approve(
        proposal_id=proposal_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionProposalResponse.model_validate(await service.describe(proposal))


@router.post("/proposals/{proposal_id}/realize-skill-patch", response_model=ReflectionProposalResponse)
async def realize_skill_patch_request(
    proposal_id: str,
    payload: RealizeSkillPatchRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalResponse:
    service = get_reflection_proposal_service(session)
    try:
        proposal = await service.realize_skill_patch_request(
            proposal_id=proposal_id,
            operator_id=operator_id,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
        )
        await session.commit()
        return ReflectionProposalResponse.model_validate(await service.describe(proposal))
    except Exception:
        await session.rollback()
        raise


@router.post("/proposals/{proposal_id}/reject", response_model=ReflectionProposalResponse)
async def reject_reflection_proposal(
    proposal_id: str,
    payload: RejectReflectionProposalRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalResponse:
    service = get_reflection_proposal_service(session)
    proposal = await service.reject(
        proposal_id=proposal_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionProposalResponse.model_validate(await service.describe(proposal))


@router.post("/proposals/{proposal_id}/activate", response_model=ReflectionProposalRolloutResponse)
async def activate_reflection_proposal_rollout(
    proposal_id: str,
    payload: ActivateReflectionProposalRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalRolloutResponse:
    service = get_reflection_proposal_rollout_service(session)
    rollout = await service.activate(
        proposal_id=proposal_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionProposalRolloutResponse.model_validate(rollout)


@router.get("/proposals/{proposal_id}/rollouts", response_model=list[ReflectionProposalRolloutResponse])
async def list_reflection_proposal_rollouts(
    proposal_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReflectionProposalRolloutResponse]:
    service = get_reflection_proposal_rollout_service(session)
    return [ReflectionProposalRolloutResponse.model_validate(item) for item in await service.list_rollouts(proposal_id)]


@router.get("/goals/{goal_id}/skill-bindings", response_model=list[GoalSkillBindingResponse])
async def list_goal_skill_bindings(
    goal_id: str,
    context: AccessContext = Depends(get_access_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[GoalSkillBindingResponse]:
    if context.actor_type != "operator":
        raise HTTPException(status_code=403, detail="Operator access is required.")
    await require_goal_access(goal_id, context, session)
    _ = get_goal_skill_binding_resolver(session)
    repository = GoalSkillBindingRepository(session)
    items = await repository.list_by_goal(goal_id)
    return [GoalSkillBindingResponse.model_validate(item) for item in items]


@router.get("/skill-bindings/{binding_id}", response_model=GoalSkillBindingResponse)
async def get_goal_skill_binding(
    binding_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> GoalSkillBindingResponse:
    _ = get_goal_skill_binding_resolver(session)
    repository = GoalSkillBindingRepository(session)
    item = await repository.get_by_id(binding_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Goal skill binding not found.")
    return GoalSkillBindingResponse.model_validate(item)


@router.get("/rollouts/{rollout_id}", response_model=ReflectionProposalRolloutResponse)
async def get_reflection_proposal_rollout(
    rollout_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalRolloutResponse:
    service = get_reflection_proposal_rollout_service(session)
    return ReflectionProposalRolloutResponse.model_validate(await service.get_rollout(rollout_id))


@router.get("/rollouts/{rollout_id}/observations", response_model=list[ReflectionProposalRolloutObservationResponse])
async def list_reflection_proposal_rollout_observations(
    rollout_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReflectionProposalRolloutObservationResponse]:
    service = get_reflection_proposal_rollout_service(session)
    return [
        ReflectionProposalRolloutObservationResponse.model_validate(item)
        for item in await service.list_observations(rollout_id)
    ]


@router.get("/rollouts/{rollout_id}/decisions", response_model=list[ReflectionProposalRolloutDecisionResponse])
async def list_reflection_proposal_rollout_decisions(
    rollout_id: str,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> list[ReflectionProposalRolloutDecisionResponse]:
    service = get_reflection_proposal_rollout_service(session)
    return [
        ReflectionProposalRolloutDecisionResponse.model_validate(item)
        for item in await service.list_decisions(rollout_id)
    ]


@router.post("/rollouts/{rollout_id}/observe", response_model=ReflectionProposalRolloutObservationResponse)
async def observe_reflection_proposal_rollout(
    rollout_id: str,
    payload: ObserveReflectionProposalRolloutRequest,
    _: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalRolloutObservationResponse:
    service = get_reflection_proposal_rollout_service(session)
    observation = await service.observe(
        rollout_id=rollout_id,
        trigger_source=payload.reason_code,
    )
    await session.commit()
    return ReflectionProposalRolloutObservationResponse.model_validate(observation)


@router.post("/rollouts/{rollout_id}/promote", response_model=ReflectionProposalRolloutResponse)
async def promote_reflection_proposal_rollout(
    rollout_id: str,
    payload: PromoteReflectionProposalRolloutRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalRolloutResponse:
    service = get_reflection_proposal_rollout_service(session)
    rollout = await service.promote(
        rollout_id=rollout_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionProposalRolloutResponse.model_validate(rollout)


@router.post("/rollouts/{rollout_id}/rollback", response_model=ReflectionProposalRolloutResponse)
async def rollback_reflection_proposal_rollout(
    rollout_id: str,
    payload: RollbackReflectionProposalRolloutRequest,
    operator_id: str = Depends(require_operator_api_key),
    session: AsyncSession = Depends(get_db_session),
) -> ReflectionProposalRolloutResponse:
    service = get_reflection_proposal_rollout_service(session)
    rollout = await service.rollback(
        rollout_id=rollout_id,
        operator_id=operator_id,
        reason_code=payload.reason_code,
        reason_note=payload.reason_note,
    )
    await session.commit()
    return ReflectionProposalRolloutResponse.model_validate(rollout)
