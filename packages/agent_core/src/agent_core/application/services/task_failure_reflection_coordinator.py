"""Task failure reflection coordinator.

Triggers a reflection when a task-execution workflow run fails.
Replaces the ``failure_reflection_callback`` that was previously
threaded through ``TaskExecutionService`` and ``AutonomousTaskService``.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.application.services.reflection import ReflectionService
    from agent_core.domain.entities.goal import LearnerGoal


class TaskFailureReflectionCoordinator:
    """Trigger failure-scoped reflection after a workflow-run error."""

    def __init__(
        self,
        *,
        reflection_service: ReflectionService | None = None,
    ) -> None:
        self._reflection_service = reflection_service

    async def trigger_for_task_failure(
        self,
        *,
        goal: LearnerGoal,
        workflow_run_id: str,
        daily_task_id: str | None = None,
        study_plan_id: str | None = None,
    ) -> None:
        if self._reflection_service is None:
            return
        from agent_core.application.services.reflection import ReflectionTriggerRequest

        await self._reflection_service.trigger_reflection(
            ReflectionTriggerRequest(
                learner_profile_id=goal.learner_profile_id,
                learner_goal_id=goal.id,
                scope="task" if daily_task_id is not None else "goal",
                target_type="workflow_run",
                target_id=workflow_run_id,
                trigger_source="workflow_failed",
                reflection_depth=1,
                daily_task_id=daily_task_id,
                workflow_run_id=workflow_run_id,
                study_plan_id=study_plan_id,
                source_attempt_id=workflow_run_id,
            )
        )
