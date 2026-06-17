"""Task execution service with real business logic.

This service handles daily task execution operations,
migrated from AutonomousTaskService.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.interfaces import (
    ChatServiceProtocol,
    QuizServiceProtocol,
    SessionServiceProtocol,
    WorkflowRunServiceProtocol,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.planning import (
    DailyTaskResponse,
    ExecuteDailyTaskResponse,
)
from agent_core.domain.schemas.session import CreateSessionRequest, MessageRequest
from agent_core.domain.schemas.quiz import GenerateQuizRequest
from agent_core.infrastructure.db.repositories import (
    LearnerGoalRepository,
    DailyTaskRepository,
)


class TaskExecutionService:
    """Handle daily task execution operations.

    Responsibilities:
    - Execute pending tasks (create session, trigger workflow)
    - Handle different execution modes (chat, quiz, workflow)
    - Manage execution lifecycle and audit logging
    """

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        daily_task_repository: DailyTaskRepository,
        session_service: SessionServiceProtocol,
        chat_service: ChatServiceProtocol,
        quiz_service: QuizServiceProtocol,
        workflow_run_service: WorkflowRunServiceProtocol,
        audit_service,
        failure_reflection_callback=None,
    ) -> None:
        """Initialize the execution service with real dependencies.

        Args:
            db_session: Database session for transaction management.
            goal_repository: Repository for learner goals.
            daily_task_repository: Repository for daily tasks.
            session_service: Service for creating learning sessions.
            chat_service: Service for chat interactions.
            quiz_service: Service for quiz generation.
            workflow_run_service: Service for workflow management.
            audit_service: Service for audit logging.
            failure_reflection_callback: Optional async callback(goal, task, run_id)
                for triggering reflection on workflow failures.
        """
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._daily_task_repository = daily_task_repository
        self._session_service = session_service
        self._chat_service = chat_service
        self._quiz_service = quiz_service
        self._workflow_run_service = workflow_run_service
        self._audit_service = audit_service
        self._failure_reflection_callback = failure_reflection_callback

    async def execute_task(self, task_id: str) -> ExecuteDailyTaskResponse:
        """Execute a pending daily task.

        Creates a learning session and triggers the appropriate execution mode
        (chat, quiz, or workflow). If the task is already in progress with an
        existing session, reuses that session.

        Args:
            task_id: Daily task identifier.

        Returns:
            Execution response with task, workflow run, and session IDs.

        Raises:
            NotFoundError: If task does not exist.
            ValidationError: If task is not in pending status or has unsupported mode.
        """
        task = await self._require_task(task_id)

        # Reuse existing in-progress execution
        if (
            task.status == "in_progress"
            and task.execution_session_id is not None
            and task.last_workflow_run_id is not None
        ):
            await self._audit_service.record_durable(
                event_type="daily_task.execution.reused",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": task.last_workflow_run_id,
                    "execution_session_id": task.execution_session_id,
                    "task_type": task.task_type,
                    "execution_mode": task.execution_mode,
                },
            )
            return ExecuteDailyTaskResponse(
                task=DailyTaskResponse.model_validate(task),
                workflow_run_id=task.last_workflow_run_id,
                execution_session_id=task.execution_session_id,
                reused_existing_execution=True,
            )

        # Only pending tasks can be executed
        if task.status != "pending":
            raise ValidationError("Only pending tasks can be executed.")

        # Create workflow run
        run = await self._workflow_run_service.create_run(
            workflow_type="task_execution",
            trigger_source="manual_execute",
            learner_goal_id=task.learner_goal_id,
            study_plan_id=task.study_plan_id,
            daily_task_id=task.id,
        )

        try:
            # Create learning session
            goal = await self._require_goal(task.learner_goal_id)
            session = await self._session_service.create_session(
                CreateSessionRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    title=task.title,
                    subject=goal.subject,
                ),
                daily_task_id=task.id,
                commit=False,
            )

            # Update task with execution session
            working_task = task.with_execution_session(
                execution_session_id=session.id,
                workflow_run_id=run.id,
            )
            await self._daily_task_repository.update(working_task)

            # Audit: execution started
            await self._audit_service.record(
                event_type="daily_task.execution.started",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": run.id,
                    "execution_session_id": session.id,
                    "execution_mode": task.execution_mode,
                },
            )

            # Execute based on mode
            if task.execution_mode == "chat":
                await self._chat_service.create_message(
                    session_id=session.id,
                    payload=MessageRequest(content=task.instructions, mode="chat"),
                    commit=False,
                )
            elif task.execution_mode == "quiz":
                await self._quiz_service.generate_quiz(
                    GenerateQuizRequest(
                        session_id=session.id,
                        topic=task.topic_focus,
                        difficulty=task.difficulty or "medium",
                        question_count=task.question_count or 3,
                    ),
                    commit=False,
                )
            else:
                raise ValidationError("Unsupported task execution mode.")

            # Complete workflow run
            run = await self._workflow_run_service.complete_run(
                run=run,
                result_resource_type="learning_session",
                result_resource_ids=[session.id],
            )

            # Audit: execution completed
            await self._audit_service.record(
                event_type="daily_task.execution.completed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": run.id,
                    "execution_session_id": session.id,
                },
            )

            await self._db_session.commit()

            # Return execution response
            refreshed_task = await self._require_task(task.id)
            return ExecuteDailyTaskResponse(
                task=DailyTaskResponse.model_validate(refreshed_task),
                workflow_run_id=run.id,
                execution_session_id=session.id,
                reused_existing_execution=False,
            )

        except Exception as exc:
            # Fail workflow run
            await self._workflow_run_service.fail_run(run=run, error_code=type(exc).__name__)

            # Trigger failure reflection (optional)
            if self._failure_reflection_callback is not None:
                goal = await self._require_goal(task.learner_goal_id)
                await self._failure_reflection_callback(
                    goal=goal,
                    task=task,
                    run_id=run.id,
                )

            # Audit: execution failed
            await self._audit_service.record_durable(
                event_type="daily_task.execution.failed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data={
                    "daily_task_id": task.id,
                    "workflow_run_id": run.id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                },
            )

            await self._db_session.rollback()
            raise

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
