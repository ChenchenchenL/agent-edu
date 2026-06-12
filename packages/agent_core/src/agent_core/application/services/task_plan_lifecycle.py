"""Task planning and lifecycle facade service."""

from __future__ import annotations

from datetime import date

from agent_core.application.services.task import AutonomousTaskService
from agent_core.domain.schemas.planning import (
    DailyTaskResponse,
    StudyPlanResponse,
    UpdateDailyTaskStatusRequest,
    WorkflowRunResponse,
)


class TaskPlanLifecycleService:
    """Expose planning and task lifecycle operations through a focused service."""

    def __init__(self, *, core: AutonomousTaskService) -> None:
        """Initialize the lifecycle service.

        Args:
            core: Shared task core implementation.
        """
        self._core = core

    async def generate_plan(
        self,
        *,
        goal_id: str,
        trigger_source: str,
        commit: bool = True,
        scheduled_job_id: str | None = None,
    ) -> StudyPlanResponse:
        """Generate or replan a study plan."""
        return await self._core.generate_plan(
            goal_id=goal_id,
            trigger_source=trigger_source,
            commit=commit,
            scheduled_job_id=scheduled_job_id,
        )

    async def list_plans(self, goal_id: str) -> list[StudyPlanResponse]:
        """List plans for a goal."""
        return await self._core.list_plans(goal_id)

    async def get_plan(self, plan_id: str) -> StudyPlanResponse:
        """Fetch a single study plan."""
        return await self._core.get_plan(plan_id)

    async def list_tasks(
        self,
        goal_id: str,
        *,
        statuses: set[str] | None = None,
        scheduled_from: date | None = None,
        scheduled_to: date | None = None,
        task_type: str | None = None,
    ) -> list[DailyTaskResponse]:
        """List tasks for a goal."""
        return await self._core.list_tasks(
            goal_id,
            statuses=statuses,
            scheduled_from=scheduled_from,
            scheduled_to=scheduled_to,
            task_type=task_type,
        )

    async def get_task(self, task_id: str) -> DailyTaskResponse:
        """Fetch a single task."""
        return await self._core.get_task(task_id)

    async def update_task_status(
        self,
        *,
        task_id: str,
        payload: UpdateDailyTaskStatusRequest,
    ) -> DailyTaskResponse:
        """Update a task status."""
        return await self._core.update_task_status(task_id=task_id, payload=payload)

    async def list_workflow_runs(self, goal_id: str) -> list[WorkflowRunResponse]:
        """List workflow runs for a goal."""
        return await self._core.list_workflow_runs(goal_id)

    async def get_workflow_run(self, run_id: str) -> WorkflowRunResponse:
        """Fetch a single workflow run."""
        return await self._core.get_workflow_run(run_id)
