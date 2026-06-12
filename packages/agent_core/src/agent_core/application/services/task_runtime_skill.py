"""Task runtime skill facade service."""

from __future__ import annotations

from agent_core.application.services.task import AutonomousTaskService
from agent_core.application.services.tool_plan_runtime import (
    MultiStepToolPlanExecutionReport,
    ToolPlanExecutionContext,
)
from agent_core.domain.entities.planning import DailyTask, StudyPlan
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution


class TaskRuntimeSkillService:
    """Expose runtime skill orchestration helpers through a focused service."""

    def __init__(self, *, core: AutonomousTaskService) -> None:
        """Initialize the runtime skill service.

        Args:
            core: Shared task core implementation.
        """
        self._core = core

    async def resolve_autonomy_execution_plan(
        self,
        *,
        learner_goal_id: str,
        skill_name: str,
        surface: str,
        resource_id: str,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = True,
    ):
        """Resolve a runtime execution plan for autonomy flows."""
        return await self._core._resolve_autonomy_execution_plan(  # noqa: SLF001
            learner_goal_id=learner_goal_id,
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

    async def execute_runtime_tool_plan(
        self,
        *,
        runtime_plan,
        context: ToolPlanExecutionContext,
        default_tool_name: str,
        default_payload: dict[str, object] | None = None,
    ) -> MultiStepToolPlanExecutionReport:
        """Execute a runtime tool plan for a task surface."""
        return await self._core._execute_runtime_tool_plan(  # noqa: SLF001
            runtime_plan=runtime_plan,
            context=context,
            default_tool_name=default_tool_name,
            default_payload=default_payload,
        )

    def build_tool_plan_execution_context(
        self,
        *,
        surface: str,
        learner_goal_id: str,
        resource_id: str,
        topic_focus: str | None = None,
        study_plan_id: str | None = None,
        source_task_id: str | None = None,
        workflow_run_id: str | None = None,
        scheduled_job_id: str | None = None,
    ) -> ToolPlanExecutionContext:
        """Build a tool-plan execution context."""
        return self._core._build_tool_plan_execution_context(  # noqa: SLF001
            surface=surface,
            learner_goal_id=learner_goal_id,
            resource_id=resource_id,
            topic_focus=topic_focus,
            study_plan_id=study_plan_id,
            source_task_id=source_task_id,
            workflow_run_id=workflow_run_id,
            scheduled_job_id=scheduled_job_id,
        )

    async def resolve_review_skill_for_runtime(self, *, goal, source_task: DailyTask) -> SkillResolution:
        """Resolve review scheduling skill resolution."""
        return await self._core._resolve_review_skill_for_runtime(goal=goal, source_task=source_task)  # noqa: SLF001

    async def resolve_assessment_skill_for_runtime(
        self,
        *,
        goal,
        active_plan: StudyPlan,
        topic_key: str,
    ) -> SkillResolution:
        """Resolve assessment generation skill resolution."""
        return await self._core._resolve_assessment_skill_for_runtime(  # noqa: SLF001
            goal=goal,
            active_plan=active_plan,
            topic_key=topic_key,
        )

    async def resolve_replan_skill_for_runtime(
        self,
        *,
        goal,
        resource_id: str,
    ) -> SkillResolution:
        """Resolve replan skill resolution."""
        return await self._core._resolve_replan_skill_for_runtime(goal=goal, resource_id=resource_id)  # noqa: SLF001

    async def schedule_surface_rollout_observation(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> None:
        """Schedule rollout observation for a surface."""
        await self._core._schedule_surface_rollout_observation(  # noqa: SLF001
            learner_goal_id=learner_goal_id,
            surface=surface,
            trigger_source=trigger_source,
            source_ref=source_ref,
        )

    async def schedule_runtime_failure_rollout_observation(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> None:
        """Schedule rollout observation after a runtime failure."""
        await self._core._schedule_runtime_failure_rollout_observation(  # noqa: SLF001
            learner_goal_id=learner_goal_id,
            surface=surface,
            trigger_source=trigger_source,
            source_ref=source_ref,
        )

    async def get_rollout_overlay_payload(
        self,
        learner_goal_id: str,
        surface: str,
    ) -> dict[str, object] | None:
        """Fetch the rollout overlay payload for a surface."""
        return await self._core._get_rollout_overlay_payload(learner_goal_id, surface)  # noqa: SLF001

    async def get_skill_binding(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = True,
    ):
        """Resolve the active skill binding for a surface."""
        return await self._core._get_skill_binding(  # noqa: SLF001
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

    async def review_intervals(self, learner_goal_id: str, mastery) -> list[int]:
        """Resolve review intervals."""
        return await self._core._review_intervals(learner_goal_id, mastery)  # noqa: SLF001
