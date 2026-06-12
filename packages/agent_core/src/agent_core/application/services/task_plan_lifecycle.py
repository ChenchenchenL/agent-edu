"""Task planning and lifecycle service with real business logic.

This service handles study plan and daily task lifecycle operations,
migrated from AutonomousTaskService to reduce God Class complexity.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.entities.planning import StudyPlan
from agent_core.domain.errors import NotFoundError
from agent_core.domain.schemas.planning import (
    DailyTaskResponse,
    StudyPlanResponse,
    UpdateDailyTaskStatusRequest,
    WorkflowRunResponse,
)
from agent_core.infrastructure.db.repositories import (
    LearnerGoalRepository,
    StudyPlanRepository,
    PlanStageRepository,
    DailyTaskRepository,
    WorkflowRunRepository,
)


class TaskPlanLifecycleService:
    """Manage study plan and daily task lifecycle operations.

    Responsibilities:
    - Study plan CRUD operations
    - Daily task CRUD operations
    - Task status updates
    - Workflow run queries

    Note: Plan generation logic remains in AutonomousTaskService until
    full migration is complete.
    """

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        study_plan_repository: StudyPlanRepository,
        plan_stage_repository: PlanStageRepository,
        daily_task_repository: DailyTaskRepository,
        workflow_run_repository: WorkflowRunRepository,
    ) -> None:
        """Initialize the lifecycle service with real dependencies.

        Args:
            db_session: Database session for transaction management.
            goal_repository: Repository for learner goals.
            study_plan_repository: Repository for study plans.
            plan_stage_repository: Repository for plan stages.
            daily_task_repository: Repository for daily tasks.
            workflow_run_repository: Repository for workflow runs.
        """
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._study_plan_repository = study_plan_repository
        self._plan_stage_repository = plan_stage_repository
        self._daily_task_repository = daily_task_repository
        self._workflow_run_repository = workflow_run_repository

    async def generate_plan(
        self,
        *,
        goal_id: str,
        trigger_source: str,
        commit: bool = True,
        scheduled_job_id: str | None = None,
    ) -> StudyPlanResponse:
        """Generate or replan a study plan.

        Note: This method is a placeholder. Real implementation
        remains in AutonomousTaskService until full migration.

        Args:
            goal_id: Learner goal identifier.
            trigger_source: Source that triggered plan generation.
            commit: Whether to commit the transaction.
            scheduled_job_id: Optional scheduled job identifier.

        Returns:
            Generated study plan response.
        """
        # TODO: Migrate generate_plan implementation from AutonomousTaskService
        raise NotImplementedError("generate_plan migration pending")

    async def list_plans(self, goal_id: str) -> list[StudyPlanResponse]:
        """List all study plans for a goal.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            List of study plan responses.

        Raises:
            NotFoundError: If goal does not exist.
        """
        await self._require_goal(goal_id)
        plans = await self._study_plan_repository.list_by_goal(goal_id)
        return [await self._to_plan_response(plan) for plan in plans]

    async def get_plan(self, plan_id: str) -> StudyPlanResponse:
        """Fetch a single study plan by ID.

        Args:
            plan_id: Study plan identifier.

        Returns:
            Study plan response with stages.

        Raises:
            NotFoundError: If plan does not exist.
        """
        plan = await self._study_plan_repository.get_by_id(plan_id)
        if plan is None:
            raise NotFoundError(f"Study plan '{plan_id}' was not found.")
        return await self._to_plan_response(plan)

    async def list_tasks(
        self,
        goal_id: str,
        *,
        statuses: set[str] | None = None,
        scheduled_from: date | None = None,
        scheduled_to: date | None = None,
        task_type: str | None = None,
    ) -> list[DailyTaskResponse]:
        """List daily tasks for a goal with optional filters.

        Args:
            goal_id: Learner goal identifier.
            statuses: Optional set of task statuses to filter.
            scheduled_from: Optional start date for scheduled tasks.
            scheduled_to: Optional end date for scheduled tasks.
            task_type: Optional task type filter.

        Returns:
            List of daily task responses.

        Raises:
            NotFoundError: If goal does not exist.
        """
        await self._require_goal(goal_id)

        if statuses is None and scheduled_from is None and scheduled_to is None and task_type is None:
            tasks = await self._daily_task_repository.list_by_goal(goal_id)
        else:
            tasks = await self._daily_task_repository.list_filtered(
                learner_goal_id=goal_id,
                statuses=statuses,
                scheduled_from=self._to_datetime(scheduled_from) if scheduled_from is not None else None,
                scheduled_to=self._to_datetime(scheduled_to) if scheduled_to is not None else None,
                task_type=task_type,
            )
        return [DailyTaskResponse.model_validate(task) for task in tasks]

    async def get_task(self, task_id: str) -> DailyTaskResponse:
        """Fetch a single daily task by ID.

        Args:
            task_id: Daily task identifier.

        Returns:
            Daily task response.

        Raises:
            NotFoundError: If task does not exist.
        """
        task = await self._daily_task_repository.get_by_id(task_id)
        if task is None:
            raise NotFoundError(f"Daily task '{task_id}' was not found.")
        return DailyTaskResponse.model_validate(task)

    async def update_task_status(
        self,
        *,
        task_id: str,
        payload: UpdateDailyTaskStatusRequest,
        audit_service,
        post_update_callback=None,
    ) -> DailyTaskResponse:
        """Update a daily task's status with validation and audit logging.

        This is a simplified implementation focusing on core status update logic.
        Complex followup actions (reflection, memory, rollout observation) are
        handled via optional callback to avoid circular dependencies during migration.

        Args:
            task_id: Daily task identifier.
            payload: Status update request with new status and optional note.
            audit_service: Audit service for logging status changes.
            post_update_callback: Optional async callback(task) for complex followups.

        Returns:
            Updated daily task response.

        Raises:
            ValidationError: If status transition is invalid.
            NotFoundError: If task does not exist.
        """
        from agent_core.domain.errors import ValidationError
        from agent_core.infrastructure.observability.metrics import observe_daily_task_status_transition

        # Validate status transition
        if payload.status not in {"completed", "skipped", "failed"}:
            raise ValidationError("Only completed, skipped, or failed status updates are supported.")

        task = await self._require_task(task_id)

        if task.status not in {"pending", "in_progress"}:
            raise ValidationError("Only pending or in-progress tasks can be updated.")

        updated_task = task.with_status(payload.status, result_note=payload.result_note)

        try:
            # Core update: persist task status
            await self._daily_task_repository.update(updated_task)

            # Metrics observation
            observe_daily_task_status_transition(
                from_status=task.status,
                to_status=updated_task.status,
                task_type=updated_task.task_type,
            )

            # Audit logging
            await audit_service.record(
                event_type="daily_task.status.updated",
                resource_type="daily_task",
                resource_id=task.id,
                actor="learner",
                event_data={
                    "daily_task_id": task.id,
                    "previous_status": task.status,
                    "new_status": updated_task.status,
                    "result_note": payload.result_note,
                },
            )

            # Optional complex followups (reflection, memory, etc.)
            if post_update_callback is not None:
                await post_update_callback(updated_task)

            await self._db_session.commit()

        except Exception as exc:
            await self._db_session.rollback()

            # Durable audit log for failures
            await audit_service.record_durable(
                event_type="daily_task.status.update.failed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="learner",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": task.last_workflow_run_id,
                    "previous_status": task.status,
                    "requested_status": payload.status,
                    "result_note": payload.result_note,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )
            raise

        # Refresh and return updated task
        refreshed_task = await self._daily_task_repository.get_by_id(task.id)
        if refreshed_task is None:
            raise NotFoundError(f"Daily task '{task.id}' was not found after update.")
        return DailyTaskResponse.model_validate(refreshed_task)

    async def list_workflow_runs(self, goal_id: str) -> list[WorkflowRunResponse]:
        """List workflow runs for a goal.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            List of workflow run responses.

        Raises:
            NotFoundError: If goal does not exist.
        """
        await self._require_goal(goal_id)
        runs = await self._workflow_run_repository.list_by_goal(goal_id)
        return [WorkflowRunResponse.model_validate(run) for run in runs]

    async def get_workflow_run(self, run_id: str) -> WorkflowRunResponse:
        """Fetch a single workflow run by ID.

        Args:
            run_id: Workflow run identifier.

        Returns:
            Workflow run response.

        Raises:
            NotFoundError: If run does not exist.
        """
        run = await self._workflow_run_repository.get_by_id(run_id)
        if run is None:
            raise NotFoundError(f"Workflow run '{run_id}' was not found.")
        return WorkflowRunResponse.model_validate(run)

    # Private helper methods

    async def _require_goal(self, goal_id: str):
        """Require goal to exist, raising NotFoundError otherwise.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            The learner goal entity.

        Raises:
            NotFoundError: If goal does not exist.
        """
        goal = await self._goal_repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        return goal

    async def _require_task(self, task_id: str):
        """Require task to exist, raising NotFoundError otherwise.

        Args:
            task_id: Daily task identifier.

        Returns:
            The daily task entity.

        Raises:
            NotFoundError: If task does not exist.
        """
        task = await self._daily_task_repository.get_by_id(task_id)
        if task is None:
            raise NotFoundError(f"Daily task '{task_id}' was not found.")
        return task

    async def _to_plan_response(self, plan: StudyPlan) -> StudyPlanResponse:
        """Convert StudyPlan entity to response DTO with stages.

        Args:
            plan: Study plan entity.

        Returns:
            Study plan response with embedded stages.
        """
        stages = await self._plan_stage_repository.list_by_plan(plan.id)
        return StudyPlanResponse.model_validate(
            {
                "id": plan.id,
                "learner_goal_id": plan.learner_goal_id,
                "version": plan.version,
                "status": plan.status,
                "trigger_source": plan.trigger_source,
                "plan_summary": plan.plan_summary,
                "blueprint_payload": plan.blueprint_payload,
                "materialized_until_date": plan.materialized_until_date,
                "supersedes_plan_id": plan.supersedes_plan_id,
                "created_at": plan.created_at,
                "updated_at": plan.updated_at,
                "stages": [
                    {
                        "id": stage.id,
                        "study_plan_id": stage.study_plan_id,
                        "position": stage.position,
                        "title": stage.title,
                        "objective": stage.objective,
                        "focus_topics": stage.focus_topics,
                        "start_date": stage.start_date,
                        "end_date": stage.end_date,
                    }
                    for stage in stages
                ],
            }
        )

    @staticmethod
    def _to_datetime(value: date) -> datetime:
        """Convert date to datetime at UTC midnight.

        Args:
            value: Date to convert.

        Returns:
            Datetime at midnight UTC.
        """
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
