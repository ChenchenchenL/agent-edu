from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.access_control import (
    AccessContext,
    require_plan_access,
    require_task_access,
    require_workflow_run_access,
)
from agent_core.api.dependencies import get_access_context, get_db_session, get_task_service
from agent_core.domain.schemas.planning import (
    DailyTaskResponse,
    ExecuteDailyTaskResponse,
    StudyPlanResponse,
    UpdateDailyTaskStatusRequest,
    WorkflowRunResponse,
)

router = APIRouter(tags=["planning"])


@router.get("/plans/{plan_id}", response_model=StudyPlanResponse)
async def get_study_plan(
    plan_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> StudyPlanResponse:
    await require_plan_access(plan_id, context, session)
    service = get_task_service(session)
    return await service.get_plan(plan_id)


@router.get("/tasks/{task_id}", response_model=DailyTaskResponse)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> DailyTaskResponse:
    await require_task_access(task_id, context, session)
    service = get_task_service(session)
    return await service.get_task(task_id)


@router.post("/tasks/{task_id}/execute", response_model=ExecuteDailyTaskResponse)
async def execute_task(
    task_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> ExecuteDailyTaskResponse:
    await require_task_access(task_id, context, session)
    service = get_task_service(session)
    return await service.execute_task(task_id)


@router.patch("/tasks/{task_id}/status", response_model=DailyTaskResponse)
async def update_task_status(
    task_id: str,
    payload: UpdateDailyTaskStatusRequest,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> DailyTaskResponse:
    await require_task_access(task_id, context, session)
    service = get_task_service(session)
    return await service.update_task_status(task_id=task_id, payload=payload)


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunResponse)
async def get_workflow_run(
    run_id: str,
    session: AsyncSession = Depends(get_db_session),
    context: AccessContext = Depends(get_access_context),
) -> WorkflowRunResponse:
    await require_workflow_run_access(run_id, context, session)
    service = get_task_service(session)
    return await service.get_workflow_run(run_id)
