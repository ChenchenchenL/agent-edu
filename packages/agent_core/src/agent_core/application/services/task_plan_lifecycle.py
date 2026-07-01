"""Task planning and lifecycle service with real business logic.

This service handles study plan and daily task lifecycle operations,
migrated from AutonomousTaskService to reduce God Class complexity.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.interfaces.memory import MemoryServiceProtocol
from agent_core.application.interfaces.planner import PlannerServiceProtocol
from agent_core.application.interfaces.workflow import WorkflowRunServiceProtocol
from agent_core.application.services.task_status_update_support import TaskStatusUpdateSupportService
from agent_core.domain.entities.planning import StudyPlan
from agent_core.domain.errors import NotFoundError, ValidationError
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

if TYPE_CHECKING:
    from agent_core.application.services.audit import AuditService
    from agent_core.application.services.reflection import ReflectionService
    from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
        ReflectionProposalRolloutObservationScheduler,
    )
    from agent_core.domain.entities.goal import LearnerGoal


GoalStateSyncCallback = Callable[[str, str, str], Awaitable[None]]


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
        planner_service: PlannerServiceProtocol,
        workflow_run_service: WorkflowRunServiceProtocol,
        audit_service: AuditService | None = None,
        memory_service: MemoryServiceProtocol | None = None,
        status_update_support: TaskStatusUpdateSupportService | None = None,
        sync_goal_state_after_plan: GoalStateSyncCallback | None = None,
        rollout_observation_scheduler: ReflectionProposalRolloutObservationScheduler | None = None,
        reflection_service: ReflectionService | None = None,
    ) -> None:
        """Initialize the lifecycle service with real dependencies.

        Args:
            db_session: Database session for transaction management.
            goal_repository: Repository for learner goals.
            study_plan_repository: Repository for study plans.
            plan_stage_repository: Repository for plan stages.
            daily_task_repository: Repository for daily tasks.
            workflow_run_repository: Repository for workflow runs.
            planner_service: Planner used to materialize study plans.
            workflow_run_service: Workflow orchestration service.
            audit_service: Optional audit service for standalone status updates.
            memory_service: Optional memory interpretation provider for planning.
            status_update_support: Shared support for attempts, mastery, and post-update side effects.
            sync_goal_state_after_plan: Optional callback for autonomy state synchronization.
            rollout_observation_scheduler: Optional scheduler for rollout observation tracking.
            reflection_service: Optional reflection service for workflow failure reflection.
        """
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._study_plan_repository = study_plan_repository
        self._plan_stage_repository = plan_stage_repository
        self._daily_task_repository = daily_task_repository
        self._workflow_run_repository = workflow_run_repository
        self._planner_service = planner_service
        self._workflow_run_service = workflow_run_service
        self._audit_service = audit_service
        self._memory_service = memory_service
        self._status_update_support = status_update_support
        self._sync_goal_state_after_plan_callback = sync_goal_state_after_plan
        self._rollout_observation_scheduler = rollout_observation_scheduler
        self._reflection_service = reflection_service

    async def generate_plan(
        self,
        *,
        goal_id: str,
        trigger_source: str,
        commit: bool = True,
        scheduled_job_id: str | None = None,
    ) -> tuple[StudyPlanResponse, str]:
        """Generate or replan a study plan.

        Args:
            goal_id: Learner goal identifier.
            trigger_source: Source that triggered plan generation.
            commit: Whether to commit the transaction.
            scheduled_job_id: Optional scheduled job identifier.

        Returns:
            Generated study plan response.
        """
        if self._audit_service is None:
            raise RuntimeError("Standalone plan generation requires an audit service.")

        goal = await self._require_goal(goal_id)
        active_plan = await self._study_plan_repository.get_active_by_goal(goal.id)
        if active_plan is not None and trigger_source not in {"manual_replan", "task_failed", "task_skipped"}:
            raise ValidationError("An active study plan already exists for this goal.")

        version = 1 if active_plan is None else active_plan.version + 1
        run = await self._workflow_run_service.create_run(
            workflow_type="plan_generation",
            trigger_source=trigger_source,
            learner_goal_id=goal.id,
            study_plan_id=active_plan.id if active_plan is not None else None,
            daily_task_id=None,
            scheduled_job_id=scheduled_job_id,
        )

        try:
            memory_interpretation = None
            if self._memory_service is not None:
                memory_interpretation = await self._memory_service.build_interpretation(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    limit_per_type=4,
                )
            materialized = await self._planner_service.build_plan(
                goal=goal,
                version=version,
                trigger_source=trigger_source,
                supersedes_plan_id=active_plan.id if active_plan is not None else None,
                memory_interpretation=memory_interpretation,
            )
            if active_plan is not None:
                await self._supersede_active_plan(
                    goal=goal,
                    active_plan=active_plan,
                    replacement_plan_id=materialized.study_plan.id,
                )
            await self._study_plan_repository.create(materialized.study_plan)
            await self._plan_stage_repository.create_many(materialized.stages)
            await self._daily_task_repository.create_many(materialized.tasks)
            await self._audit_generated_plan(
                goal_id=goal.id,
                trigger_source=trigger_source,
                active_plan=active_plan,
                materialized_plan=materialized.study_plan,
                task_count=len(materialized.tasks),
                fallback_used=materialized.llm_draft.fallback_used,
            )
            await self._audit_created_tasks(materialized.tasks)
            run = await self._workflow_run_service.complete_run(
                run=run,
                result_resource_type="study_plan",
                result_resource_ids=[materialized.study_plan.id, *[task.id for task in materialized.tasks]],
            )
            await self._sync_goal_state_after_plan(
                goal_id=goal.id,
                plan_id=materialized.study_plan.id,
                trigger_source=trigger_source,
            )
            await self._schedule_surface_rollout_observation(
                learner_goal_id=goal.id,
                surface="plan_generation",
                trigger_source=trigger_source,
                source_ref=run.id,
            )
            if commit:
                await self._db_session.commit()
        except Exception as exc:
            await self._db_session.rollback()
            await self._workflow_run_service.fail_run(run=run, error_code=type(exc).__name__)
            await self._trigger_workflow_failure_reflection(
                goal=goal,
                workflow_run_id=run.id,
                study_plan_id=active_plan.id if active_plan is not None else None,
            )
            raise

        return await self.get_plan(materialized.study_plan.id), run.id

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
    ) -> DailyTaskResponse:
        """Update a daily task's status with validation and audit logging.

        This service owns the core task status write. Post-write coordination
        stays injectable during migration so the write path can cut over without
        forcing every downstream dependency into this service constructor.

        Args:
            task_id: Daily task identifier.
            payload: Status update request with new status and optional note.

        Returns:
            Updated daily task response.

        Raises:
            ValidationError: If status transition is invalid.
            NotFoundError: If task does not exist.
        """
        from agent_core.domain.errors import ValidationError
        from agent_core.infrastructure.observability.metrics import observe_daily_task_status_transition

        if self._audit_service is None:
            raise RuntimeError("Standalone task lifecycle status updates require an audit service.")

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
            await self._audit_service.record(
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

            attempt = None
            if self._status_update_support is not None:
                attempt = await self._status_update_support.record_attempt_and_update_mastery(updated_task)
                await self._status_update_support.coordinate_post_update(updated_task, attempt)

            await self._db_session.commit()

        except Exception as exc:
            await self._db_session.rollback()

            # Durable audit log for failures
            await self._audit_service.record_durable(
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

    async def _supersede_active_plan(
        self,
        *,
        goal: LearnerGoal,
        active_plan: StudyPlan,
        replacement_plan_id: str,
    ) -> None:
        superseded = active_plan.with_status("superseded")
        await self._study_plan_repository.update(superseded)
        await self._daily_task_repository.bulk_mark_superseded(active_plan.id)
        await self._audit_service.record(
            event_type="study_plan.superseded",
            resource_type="study_plan",
            resource_id=active_plan.id,
            actor="system",
            event_data={
                "study_plan_id": active_plan.id,
                "learner_goal_id": goal.id,
                "superseded_by_plan_id": replacement_plan_id,
            },
        )

    async def _audit_generated_plan(
        self,
        *,
        goal_id: str,
        trigger_source: str,
        active_plan: StudyPlan | None,
        materialized_plan: StudyPlan,
        task_count: int,
        fallback_used: bool,
    ) -> None:
        await self._audit_service.record(
            event_type="study_plan.generated" if active_plan is None else "study_plan.replanned",
            resource_type="study_plan",
            resource_id=materialized_plan.id,
            actor="system",
            event_data={
                "learner_goal_id": goal_id,
                "study_plan_id": materialized_plan.id,
                "version": materialized_plan.version,
                "trigger_source": trigger_source,
                "task_count": task_count,
                "fallback_used": fallback_used,
            },
        )

    async def _audit_created_tasks(self, tasks) -> None:
        for task in tasks:
            await self._audit_service.record(
                event_type="daily_task.created",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "learner_goal_id": task.learner_goal_id,
                    "study_plan_id": task.study_plan_id,
                    "task_type": task.task_type,
                    "scheduled_for": task.scheduled_for.isoformat(),
                },
            )

    async def _sync_goal_state_after_plan(
        self,
        *,
        goal_id: str,
        plan_id: str,
        trigger_source: str,
    ) -> None:
        if self._sync_goal_state_after_plan_callback is None:
            return
        await self._sync_goal_state_after_plan_callback(goal_id, plan_id, trigger_source)

    async def _schedule_surface_rollout_observation(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> None:
        if self._rollout_observation_scheduler is None:
            return
        await self._rollout_observation_scheduler.schedule_active(
            learner_goal_id=learner_goal_id,
            surface=surface,
            trigger_source=trigger_source,
            source_ref=source_ref,
        )

    async def _trigger_workflow_failure_reflection(
        self,
        *,
        goal: LearnerGoal,
        workflow_run_id: str,
        study_plan_id: str | None,
    ) -> None:
        if self._reflection_service is None:
            return
        from agent_core.application.services.reflection import ReflectionTriggerRequest

        await self._reflection_service.trigger_reflection(
            ReflectionTriggerRequest(
                learner_profile_id=goal.learner_profile_id,
                learner_goal_id=goal.id,
                scope="goal",
                target_type="workflow_run",
                target_id=workflow_run_id,
                trigger_source="workflow_failed",
                reflection_depth=1,
                workflow_run_id=workflow_run_id,
                study_plan_id=study_plan_id,
                source_attempt_id=workflow_run_id,
            )
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
