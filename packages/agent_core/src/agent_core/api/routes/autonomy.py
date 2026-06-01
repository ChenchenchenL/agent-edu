from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import AccessContext, require_goal_access
from agent_core.api.dependencies import get_access_context, get_db_session, get_task_service
from agent_core.domain.schemas.autonomy import (
    GoalAutonomyStateResponse,
    LearnerAvailabilityResponse,
    LearnerTopicMasteryResponse,
    ManualReplanRequest,
    PauseAutonomyRequest,
    ScheduledAutonomyJobResponse,
    UpdateLearnerAvailabilityRequest,
)

router = APIRouter(tags=["autonomy"])


@router.get("/goals/{goal_id}/autonomy", response_model=GoalAutonomyStateResponse)
async def get_goal_autonomy_state(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> GoalAutonomyStateResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.get_goal_autonomy_state(goal_id)


@router.patch("/goals/{goal_id}/autonomy/pause", response_model=GoalAutonomyStateResponse)
async def pause_goal_autonomy(
    goal_id: str,
    payload: PauseAutonomyRequest,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> GoalAutonomyStateResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.pause_goal_autonomy(goal_id, reason=payload.reason)


@router.patch("/goals/{goal_id}/autonomy/resume", response_model=GoalAutonomyStateResponse)
async def resume_goal_autonomy(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> GoalAutonomyStateResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.resume_goal_autonomy(goal_id)


@router.put("/goals/{goal_id}/availability", response_model=LearnerAvailabilityResponse)
async def update_goal_availability(
    goal_id: str,
    payload: UpdateLearnerAvailabilityRequest,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerAvailabilityResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.update_goal_availability(goal_id=goal_id, payload=payload)


@router.get("/goals/{goal_id}/availability", response_model=LearnerAvailabilityResponse)
async def get_goal_availability(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerAvailabilityResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.get_goal_availability(goal_id)


@router.get("/goals/{goal_id}/mastery", response_model=list[LearnerTopicMasteryResponse])
async def list_goal_mastery(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[LearnerTopicMasteryResponse]:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.list_goal_mastery(goal_id)


@router.get("/goals/{goal_id}/autonomy/jobs", response_model=list[ScheduledAutonomyJobResponse])
async def list_goal_autonomy_jobs(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[ScheduledAutonomyJobResponse]:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    jobs = await service.list_autonomy_jobs(goal_id)
    return [ScheduledAutonomyJobResponse.model_validate(item) for item in jobs]


@router.post("/goals/{goal_id}/replan", response_model=GoalAutonomyStateResponse)
async def manual_replan_goal(
    goal_id: str,
    payload: ManualReplanRequest,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> GoalAutonomyStateResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.manual_replan_goal(goal_id, payload)


@router.post("/goals/{goal_id}/autonomy/materialize-today", response_model=GoalAutonomyStateResponse)
async def materialize_goal_today(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> GoalAutonomyStateResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.materialize_today(goal_id)


@router.post("/goals/{goal_id}/periodic-reflection", response_model=GoalAutonomyStateResponse)
async def run_goal_periodic_reflection(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> GoalAutonomyStateResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_service(session)
    return await service.run_periodic_goal_reflection(goal_id)
