"""Infrastructure-level application container.

This module provides the application wiring entrypoints used by the API layer
and workers while keeping request-scoped services bound to a single session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.memory import MemoryService
from agent_core.application.services.task import AutonomousTaskService
from agent_core.application.services.task_autonomy_scheduling import TaskAutonomySchedulingService
from agent_core.application.services.task_execution import TaskExecutionService
from agent_core.application.services.task_plan_lifecycle import TaskPlanLifecycleService
from agent_core.application.services.task_runtime_skill import TaskRuntimeSkillService
from agent_core.application.services.task_status_update_support import TaskStatusUpdateSupportService
from agent_core.application.services.workspace import WorkspaceService
from agent_core.infrastructure.db.repositories import (
    GoalAutonomyStateRepository,
    LearnerGoalRepository,
    LearnerProfileRepository,
    SessionRepository,
    StudyPlanRepository,
    WorkflowRunRepository,
)


@dataclass(frozen=True)
class TaskServiceBundle:
    """Request-scoped task services."""

    core: AutonomousTaskService
    plan_lifecycle: TaskPlanLifecycleService
    execution: TaskExecutionService
    autonomy_scheduling: TaskAutonomySchedulingService
    runtime_skill: TaskRuntimeSkillService


class RequestScopeContainer:
    """Request-scoped dependency cache bound to a single DB session."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        task_core_builder: Callable[[AsyncSession], AutonomousTaskService],
        memory_service_builder: Callable[[AsyncSession], MemoryService],
    ) -> None:
        """Initialize a request scope.

        Args:
            session: Session backing all scoped repositories and services.
            task_core_builder: Builder for the legacy task core service.
            memory_service_builder: Builder for the memory service.
        """
        self._session = session
        self._task_core_builder = task_core_builder
        self._memory_service_builder = memory_service_builder
        self._task_services: TaskServiceBundle | None = None
        self._memory_service: MemoryService | None = None
        self._workspace_service: WorkspaceService | None = None

    @property
    def session(self) -> AsyncSession:
        """Expose the bound session."""
        return self._session

    def memory_service(self) -> MemoryService:
        """Get the scoped memory service."""
        if self._memory_service is None:
            self._memory_service = self._memory_service_builder(self._session)
        return self._memory_service

    def task_services(self) -> TaskServiceBundle:
        """Get the scoped task service bundle with real dependencies."""
        if self._task_services is None:
            from agent_core.infrastructure.db.repositories import (
                DailyTaskRepository,
                PlanStageRepository,
            )

            # Repositories
            goal_repository = LearnerGoalRepository(self._session)
            study_plan_repository = StudyPlanRepository(self._session)
            daily_task_repository = DailyTaskRepository(self._session)
            workflow_run_repository = WorkflowRunRepository(self._session)

            # Build legacy core service first; migration-safe facades may delegate to it.
            core = self._task_core_builder(self._session)

            # Services (Protocol-based)
            audit_service = core._audit_service
            session_service = core._session_service
            chat_service = core._chat_service
            quiz_service = core._quiz_service
            workflow_run_service = core._workflow_run_service
            status_update_support = TaskStatusUpdateSupportService(
                db_session=self._session,
                goal_repository=goal_repository,
                daily_task_repository=daily_task_repository,
                goal_autonomy_state_repository=core._goal_autonomy_state_repository,
                autonomy_job_repository=core._autonomy_job_repository,
                learner_availability_repository=core._learner_availability_repository,
                learner_topic_mastery_repository=core._learner_topic_mastery_repository,
                task_attempt_repository=core._task_attempt_repository,
                autonomy_job_service=core._autonomy_job_service,
                reflection_service=core._reflection_service,
                reflection_evidence_service=core._reflection_evidence_service,
                reflection_outcome_service=core._reflection_outcome_service,
                rollout_observation_scheduler=core._rollout_observation_scheduler,
                long_term_memory_materialization_service=core._long_term_memory_materialization_service,
                audit_service=audit_service,
                should_schedule_assessment=core._should_schedule_assessment,
                derive_replan_mode=core._derive_replan_mode,
                inline_status_followup_handler=core._run_inline_status_followups,
            )

            # Build TaskPlanLifecycleService (real implementation)
            plan_lifecycle = TaskPlanLifecycleService(
                db_session=self._session,
                goal_repository=goal_repository,
                study_plan_repository=study_plan_repository,
                plan_stage_repository=PlanStageRepository(self._session),
                daily_task_repository=daily_task_repository,
                workflow_run_repository=workflow_run_repository,
                planner_service=core._planner_service,
                workflow_run_service=workflow_run_service,
                audit_service=audit_service,
                memory_service=core._memory_service,
                status_update_support=status_update_support,
                sync_goal_state_after_plan=core._sync_goal_state_after_plan,
                schedule_rollout_observation=core._schedule_surface_rollout_observation,
                trigger_workflow_failure_reflection=core._trigger_workflow_failure_reflection,
            )

            # Build TaskExecutionService (real implementation)
            execution = TaskExecutionService(
                db_session=self._session,
                goal_repository=goal_repository,
                daily_task_repository=daily_task_repository,
                session_service=session_service,
                chat_service=chat_service,
                quiz_service=quiz_service,
                workflow_run_service=workflow_run_service,
                audit_service=audit_service,
                failure_reflection_callback=None,  # TODO: wire reflection service
            )

            # Build TaskAutonomySchedulingService (partial real implementation with callbacks)
            autonomy_scheduling = TaskAutonomySchedulingService(
                db_session=self._session,
                goal_repository=goal_repository,
                goal_autonomy_state_repository=GoalAutonomyStateRepository(self._session),
                learner_availability_repository=core._learner_availability_repository,
                learner_topic_mastery_repository=core._learner_topic_mastery_repository,
                autonomy_job_repository=core._autonomy_job_repository,
                audit_service=audit_service,
                sync_goal_state_callback=core._sync_goal_state,
                ensure_materialization_job_callback=core._ensure_daily_materialization_job,
                validate_timezone_callback=core._validate_timezone,
            )
            runtime_skill = TaskRuntimeSkillService(core=core)

            self._task_services = TaskServiceBundle(
                core=core,
                plan_lifecycle=plan_lifecycle,
                execution=execution,
                autonomy_scheduling=autonomy_scheduling,
                runtime_skill=runtime_skill,
            )
        return self._task_services

    def workspace_service(self) -> WorkspaceService:
        """Get the scoped workspace service."""
        if self._workspace_service is None:
            task_services = self.task_services()
            self._workspace_service = WorkspaceService(
                learner_profile_repository=LearnerProfileRepository(self._session),
                learner_goal_repository=LearnerGoalRepository(self._session),
                study_plan_repository=StudyPlanRepository(self._session),
                session_repository=SessionRepository(self._session),
                workflow_run_repository=WorkflowRunRepository(self._session),
                goal_autonomy_state_repository=GoalAutonomyStateRepository(self._session),
                task_plan_lifecycle_service=task_services.plan_lifecycle,
                task_autonomy_scheduling_service=task_services.autonomy_scheduling,
                memory_service=self.memory_service(),
            )
        return self._workspace_service


class ApplicationContainer:
    """Application-level dependency container."""

    def __init__(
        self,
        *,
        task_core_builder: Callable[[AsyncSession], AutonomousTaskService],
        memory_service_builder: Callable[[AsyncSession], MemoryService],
    ) -> None:
        """Initialize the application container.

        Args:
            task_core_builder: Builder for request-scoped task core services.
            memory_service_builder: Builder for request-scoped memory services.
        """
        self._task_core_builder = task_core_builder
        self._memory_service_builder = memory_service_builder

    def scope(self, session: AsyncSession) -> RequestScopeContainer:
        """Create a request scope for a database session."""
        return RequestScopeContainer(
            session=session,
            task_core_builder=self._task_core_builder,
            memory_service_builder=self._memory_service_builder,
        )
