"""Task runtime skill orchest service."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.application.services.dynamic_runtime_registry import DynamicRuntimeRegistryService
    from agent_core.application.services.skills import SkillUsageService
    from agent_core.application.services.goal_skill_binding_resolver import GoalSkillBindingResolver
    from agent_core.application.services.tool_plan_runtime import ToolPlanRuntimeExecutor
    from agent_core.application.tools.registry import InternalToolRegistry
    from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
    from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import ReflectionProposalRolloutObservationScheduler

from agent_core.application.services.review import ReviewService
from agent_core.application.services.skill.capability import (
    CapabilityRequest,
    RuntimeCapabilityExecutionPlan,
)
from agent_core.application.services.skill.capability_catalog import reverse_lookup
from agent_core.domain.entities.autonomy import LearnerTopicMastery
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.errors import ValidationError
from agent_core.application.tools.registry import ToolExecutionRequest

from agent_core.application.services.tool_plan_runtime import (
    MultiStepToolPlanExecutionReport,
    ToolPlanExecutionContext,
    ToolPlanStepResult,
)
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.domain.entities.planning import DailyTask, StudyPlan
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution
from agent_core.application.services.dynamic_runtime_registry import (
    DynamicRuntimeRegistryService,
    RuntimeSkillExecutionPlan,
)


class TaskRuntimeSkillService:
    """Expose runtime skill orchestration helpers through a focused service."""

    def __init__(
        self,
        *,
        runtime_registry: DynamicRuntimeRegistryService | None = None,
        skill_usage_service: SkillUsageService | None = None,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None = None,
        tool_plan_runtime_executor: ToolPlanRuntimeExecutor | None = None,
        internal_tool_registry: InternalToolRegistry | None = None,
        rollout_resolver: ReflectionProposalRolloutResolver | None = None,
        rollout_observation_scheduler: ReflectionProposalRolloutObservationScheduler | None = None,
        review_service: ReviewService | None = None,
    ) -> None:
        """Initialize the runtime skill service.

        Args:
            runtime_registry: Dynamic runtime registry service.
            skill_usage_service: Skill usage service.
            goal_skill_binding_resolver: Goal skill binding resolver.
            tool_plan_runtime_executor: Tool plan runtime executor.
            internal_tool_registry: Internal tool registry.
            rollout_resolver: Rollout resolver.
            rollout_observation_scheduler: Rollout observation scheduler.
            review_service: Review service.
        """
        self._runtime_registry = runtime_registry
        self._skill_usage_service = skill_usage_service
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._tool_plan_runtime_executor = tool_plan_runtime_executor
        self._internal_tool_registry = internal_tool_registry
        self._rollout_resolver = rollout_resolver
        self._rollout_observation_scheduler = rollout_observation_scheduler
        self._review_service = review_service

    async def resolve_capability_execution_plan(
        self,
        request: CapabilityRequest,
        resource_id: str | None,
    ) -> RuntimeCapabilityExecutionPlan | None:
        """Resolve a capability-driven runtime execution plan."""
        if self._runtime_registry is not None:
            result = await self._runtime_registry.resolve_capability_request(
                request,
                resource_id=resource_id or request.learner_goal_id or "capability",
            )
            if result is not None:
                return result
        return None

    async def resolve_autonomy_execution_plan(
        self,
        *,
        learner_goal_id: str,
        skill_name: str,
        surface: str,
        resource_id: str | None,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = False,
    ) -> RuntimeSkillExecutionPlan | None:
        """Resolve a runtime execution plan for autonomy flows.

        Compatibility bridge -- constructs a CapabilityRequest internally
        when a capability mapping exists, otherwise falls back to the
        legacy resolution path.
        """
        capability = reverse_lookup(skill_name, surface)
        if capability is not None:
            request = CapabilityRequest(
                capability=capability,
                surface=surface,
                learner_goal_id=learner_goal_id,
                topic_key=topic_key,
                task_type=task_type,
                trigger_source=trigger_source,
            )
            result = await self.resolve_capability_execution_plan(
                request,
                resource_id=resource_id,
            )
            if result is not None:
                return result.plan

        if self._runtime_registry is not None:
            runtime_plan = await self._runtime_registry.resolve_runtime_plan(
                learner_goal_id=learner_goal_id,
                skill_name=skill_name,
                surface=surface,
                resource_id=resource_id or learner_goal_id,
                topic_key=topic_key,
                task_type=task_type,
                trigger_source=trigger_source,
                include_staged=include_staged,
            )
            if runtime_plan is not None:
                return runtime_plan
        
        if self._skill_usage_service is None:
            return None
        
        skill_binding = await self.get_skill_binding(
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )
        
        plan = await self._skill_usage_service.resolve_execution_plan(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            skill_binding=skill_binding,
        )
        
        return DynamicRuntimeRegistryService.build_runtime_plan(
            plan=plan,
            binding=skill_binding,
        )

    async def execute_runtime_tool_plan(
        self,
        *,
        runtime_plan: RuntimeSkillExecutionPlan | None,
        context: ToolPlanExecutionContext,
        default_tool_name: str,
        default_payload: dict[str, object] | None = None,
    ) -> MultiStepToolPlanExecutionReport:
        """Execute a runtime tool plan for a task surface."""
        if runtime_plan is None or not runtime_plan.tool_plan:
            if self._internal_tool_registry is None:
                raise ValidationError("Runtime tool execution requires an internal tool registry.")
            payload = default_payload or {}
            result_payload = await self._internal_tool_registry.execute(
                ToolExecutionRequest(
                    name=default_tool_name,
                    payload=payload,
                    actor=context.actor,
                    resource_id=context.resource_id,
                )
            )
            return MultiStepToolPlanExecutionReport(
                surface=context.surface,
                steps=[
                    ToolPlanStepResult(
                        step_id="default",
                        tool_name=default_tool_name,
                        resolved_payload=dict(payload),
                        result_payload=result_payload,
                        dry_run=False,
                    )
                ],
                dry_run=False,
            )
        if self._tool_plan_runtime_executor is None:
            raise ValidationError("Runtime tool plan execution is not configured.")
        return await self._tool_plan_runtime_executor.execute(
            surface=context.surface,
            tool_plan=runtime_plan.tool_plan,
            context=context,
            dry_run=False,
            template_id=runtime_plan.selected_template_id,
            template_source=runtime_plan.selected_template_source,
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
        return ToolPlanExecutionContext(
            surface=surface,
            learner_goal_id=learner_goal_id,
            resource_id=resource_id,
            actor="system",
            source_task_id=source_task_id,
            topic_focus=topic_focus,
            study_plan_id=study_plan_id,
            workflow_run_id=workflow_run_id,
            scheduled_job_id=scheduled_job_id,
        )

    async def resolve_review_skill_for_runtime(self, *, goal: LearnerGoal, source_task: DailyTask) -> SkillResolution | None:
        """Resolve review scheduling skill resolution."""
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_for_runtime(
            skill_name="schedule_review",
            surface="review_scheduling",
            resource_id=source_task.id or goal.id,
        )

    async def resolve_replan_skill_for_runtime(
        self,
        *,
        goal: LearnerGoal,
        resource_id: str | None,
    ) -> SkillResolution | None:
        """Resolve replan skill resolution."""
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_for_runtime(
            skill_name="plan_study_path",
            surface="replan",
            resource_id=resource_id or goal.id,
        )

    async def resolve_assessment_skill_for_runtime(
        self,
        *,
        goal: LearnerGoal,
        active_plan: StudyPlan,
        topic_key: str,
    ) -> SkillResolution | None:
        """Resolve assessment generation skill resolution."""
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_for_runtime(
            skill_name="create_quiz",
            surface="assessment_generation",
            resource_id=active_plan.id or goal.id,
        )

    async def schedule_surface_rollout_observation(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> None:
        """Schedule rollout observation for a surface."""
        if self._rollout_observation_scheduler is None:
            return
        await self._rollout_observation_scheduler.schedule_active(
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
        if not source_ref:
            return
        await self.schedule_surface_rollout_observation(
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
        if self._rollout_resolver is None:
            return None
        overlay = await self._rollout_resolver.get_active_overlay(
            learner_goal_id=learner_goal_id,
            surface=surface,
            include_staged=False,
        )
        if overlay is not None:
            return dict(overlay.payload)
        return None

    async def get_skill_binding(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        topic_key: str | None = None,
        task_type: str | None = None,
        trigger_source: str | None = None,
        include_staged: bool = False,
    ) -> ActiveGoalSkillBinding | None:
        """Resolve the active skill binding for a surface."""
        if self._goal_skill_binding_resolver is None:
            return None
        return await self._goal_skill_binding_resolver.get_active_binding(
            learner_goal_id=learner_goal_id,
            surface=surface,
            topic_key=topic_key,
            task_type=task_type,
            trigger_source=trigger_source,
            include_staged=include_staged,
        )

    async def review_intervals(self, learner_goal_id: str, mastery: LearnerTopicMastery | None) -> list[int]:
        """Resolve review intervals."""
        if self._review_service is None:
            raise ValidationError("Review service is not configured.")
        return await self._review_service.get_review_intervals(learner_goal_id, mastery)
