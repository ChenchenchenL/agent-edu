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
            # Import dependencies
            from agent_core.application.services.audit import AuditService
            from agent_core.application.services.chat import ChatService
            from agent_core.application.services.quiz import QuizService
            from agent_core.application.services.session import SessionService
            from agent_core.application.services.workflow import WorkflowRunService
            from agent_core.infrastructure.db.repositories import (
                AuditRepository,
                DailyTaskRepository,
                PlanStageRepository,
                SessionRepository,
                SessionMessageRepository,
            )

            # Repositories
            goal_repository = LearnerGoalRepository(self._session)
            study_plan_repository = StudyPlanRepository(self._session)
            daily_task_repository = DailyTaskRepository(self._session)
            workflow_run_repository = WorkflowRunRepository(self._session)

            # Services (Protocol-based)
            session_service = SessionService(
                SessionRepository(self._session),
                SessionMessageRepository(self._session),
            )
            chat_service = ChatService(session_service)
            quiz_service = QuizService(session_service)
            workflow_run_service = WorkflowRunService(workflow_run_repository)

            # Audit service (simplified - no session_factory for now)
            audit_service = AuditService(
                AuditRepository(self._session),
                None,  # session_factory - optional
            )

            # Build TaskPlanLifecycleService (real implementation)
            plan_lifecycle = TaskPlanLifecycleService(
                db_session=self._session,
                goal_repository=goal_repository,
                study_plan_repository=study_plan_repository,
                plan_stage_repository=PlanStageRepository(self._session),
                daily_task_repository=daily_task_repository,
                workflow_run_repository=workflow_run_repository,
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

            # Build legacy core service (still used by other facades during migration)
            core = self._task_core_builder(self._session)

            # Other facades still delegate to core (migration pending)
            autonomy_scheduling = TaskAutonomySchedulingService(core=core)
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
