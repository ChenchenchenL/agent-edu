from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import AccessContext, require_goal_access, require_profile_access
from agent_core.api.dependencies import (
    get_access_context,
    get_db_session,
    get_goal_service,
    get_reflective_memory_service,
    get_strategy_card_service,
    get_task_autonomy_scheduling_service,
    get_task_plan_lifecycle_service,
)
from agent_core.domain.schemas.goal import (
    CreateLearnerGoalRequest,
    LearnerGoalResponse,
    UpdateLearnerGoalStatusRequest,
)
from agent_core.domain.schemas.planning import CreateStudyPlanRequest, DailyTaskResponse, StudyPlanResponse, WorkflowRunResponse
from agent_core.domain.schemas.reflection_v2 import LearnerGoalStrategyCardResponse, ReflectiveMemorySummaryResponse

router = APIRouter(tags=["learner_goals"])


@router.post("/learner-profiles/{profile_id}/goals", response_model=LearnerGoalResponse)
async def create_goal(
    profile_id: str,
    payload: CreateLearnerGoalRequest,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerGoalResponse:
    require_profile_access(profile_id, context)
    service = get_goal_service(session)
    return await service.create_goal(learner_profile_id=profile_id, payload=payload)


@router.get("/learner-profiles/{profile_id}/goals", response_model=list[LearnerGoalResponse])
async def list_goals(
    profile_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[LearnerGoalResponse]:
    require_profile_access(profile_id, context)
    service = get_goal_service(session)
    return await service.list_goals(profile_id)


@router.get("/goals/{goal_id}", response_model=LearnerGoalResponse)
async def get_goal(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerGoalResponse:
    await require_goal_access(goal_id, context, session)
    service = get_goal_service(session)
    return await service.get_goal(goal_id)


@router.patch("/goals/{goal_id}/status", response_model=LearnerGoalResponse)
async def update_goal_status(
    goal_id: str,
    payload: UpdateLearnerGoalStatusRequest,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerGoalResponse:
    await require_goal_access(goal_id, context, session)
    service = get_goal_service(session)
    return await service.update_goal_status(goal_id=goal_id, payload=payload)


@router.post("/goals/{goal_id}/plans", response_model=StudyPlanResponse)
async def create_study_plan(
    goal_id: str,
    payload: CreateStudyPlanRequest,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> StudyPlanResponse:
    await require_goal_access(goal_id, context, session)
    service = get_task_plan_lifecycle_service(session)
    return await service.generate_plan(goal_id=goal_id, trigger_source=payload.trigger_source)


@router.get("/goals/{goal_id}/plans", response_model=list[StudyPlanResponse])
async def list_study_plans(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[StudyPlanResponse]:
    await require_goal_access(goal_id, context, session)
    service = get_task_plan_lifecycle_service(session)
    return await service.list_plans(goal_id)


@router.get("/goals/{goal_id}/tasks", response_model=list[DailyTaskResponse])
async def list_goal_tasks(
    goal_id: str,
    status: list[str] = Query(default=[]),
    scheduled_from: date | None = Query(default=None),
    scheduled_to: date | None = Query(default=None),
    task_type: str | None = Query(default=None, max_length=64),
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[DailyTaskResponse]:
    await require_goal_access(goal_id, context, session)
    service = get_task_plan_lifecycle_service(session)
    return await service.list_tasks(
        goal_id,
        statuses=set(status) if status else None,
        scheduled_from=scheduled_from,
        scheduled_to=scheduled_to,
        task_type=task_type,
    )


@router.get("/goals/{goal_id}/workflow-runs", response_model=list[WorkflowRunResponse])
async def list_goal_workflow_runs(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[WorkflowRunResponse]:
    await require_goal_access(goal_id, context, session)
    service = get_task_plan_lifecycle_service(session)
    return await service.list_workflow_runs(goal_id)


@router.get("/goals/{goal_id}/strategy-card", response_model=LearnerGoalStrategyCardResponse | None)
async def get_goal_strategy_card(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> LearnerGoalStrategyCardResponse | None:
    await require_goal_access(goal_id, context, session)
    service = get_strategy_card_service(session)
    card = await service.get_active(goal_id)
    return None if card is None else LearnerGoalStrategyCardResponse.model_validate(card)


@router.get("/goals/{goal_id}/reflective-memories", response_model=list[ReflectiveMemorySummaryResponse])
async def list_goal_reflective_memories(
    goal_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> list[ReflectiveMemorySummaryResponse]:
    await require_goal_access(goal_id, context, session)
    service = get_reflective_memory_service(session)
    return [ReflectiveMemorySummaryResponse.model_validate(item) for item in await service.list_by_goal(goal_id)]
