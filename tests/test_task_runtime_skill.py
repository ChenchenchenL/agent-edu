"""Unit tests for TaskRuntimeSkillService."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_core.application.services.task_runtime_skill import TaskRuntimeSkillService
from agent_core.application.services.dynamic_runtime_registry import (
    DynamicRuntimeRegistryService,
    RuntimeSkillExecutionPlan,
)
from agent_core.application.services.skills import SkillUsageService
from agent_core.application.services.goal_skill_binding_resolver import GoalSkillBindingResolver, ActiveGoalSkillBinding
from agent_core.application.services.tool_plan_runtime import ToolPlanRuntimeExecutor, ToolPlanExecutionContext, MultiStepToolPlanExecutionReport
from agent_core.application.tools.registry import InternalToolRegistry
from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import ReflectionProposalRolloutObservationScheduler
from agent_core.application.services.review import ReviewService

from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.planning import DailyTask, StudyPlan
from agent_core.domain.entities.skill import SkillResolution
from agent_core.domain.entities.autonomy import LearnerTopicMastery
from agent_core.domain.errors import ValidationError


@pytest.fixture
def mock_runtime_registry():
    service = MagicMock(spec=DynamicRuntimeRegistryService)
    service.resolve_runtime_plan = AsyncMock()
    return service


@pytest.fixture
def mock_skill_usage_service():
    service = MagicMock(spec=SkillUsageService)
    service.resolve_execution_plan = AsyncMock()
    service.resolve_for_runtime = AsyncMock()
    return service


@pytest.fixture
def mock_goal_skill_binding_resolver():
    service = MagicMock(spec=GoalSkillBindingResolver)
    service.get_active_binding = AsyncMock()
    return service


@pytest.fixture
def mock_tool_plan_runtime_executor():
    executor = MagicMock(spec=ToolPlanRuntimeExecutor)
    executor.execute = AsyncMock()
    return executor


@pytest.fixture
def mock_internal_tool_registry():
    registry = MagicMock(spec=InternalToolRegistry)
    registry.execute = AsyncMock()
    return registry


@pytest.fixture
def mock_rollout_resolver():
    resolver = MagicMock(spec=ReflectionProposalRolloutResolver)
    resolver.get_active_overlay = AsyncMock()
    return resolver


@pytest.fixture
def mock_rollout_observation_scheduler():
    scheduler = MagicMock(spec=ReflectionProposalRolloutObservationScheduler)
    scheduler.schedule_active = AsyncMock()
    return scheduler


@pytest.fixture
def mock_review_service():
    service = MagicMock(spec=ReviewService)
    service.get_review_intervals = AsyncMock()
    return service


@pytest.fixture
def runtime_skill_service(
    mock_runtime_registry,
    mock_skill_usage_service,
    mock_goal_skill_binding_resolver,
    mock_tool_plan_runtime_executor,
    mock_internal_tool_registry,
    mock_rollout_resolver,
    mock_rollout_observation_scheduler,
    mock_review_service,
):
    return TaskRuntimeSkillService(
        runtime_registry=mock_runtime_registry,
        skill_usage_service=mock_skill_usage_service,
        goal_skill_binding_resolver=mock_goal_skill_binding_resolver,
        tool_plan_runtime_executor=mock_tool_plan_runtime_executor,
        internal_tool_registry=mock_internal_tool_registry,
        rollout_resolver=mock_rollout_resolver,
        rollout_observation_scheduler=mock_rollout_observation_scheduler,
        review_service=mock_review_service,
    )


@pytest.mark.asyncio
async def test_resolve_autonomy_execution_plan_from_registry(runtime_skill_service, mock_runtime_registry):
    # Setup
    expected_plan = MagicMock(spec=RuntimeSkillExecutionPlan)
    mock_runtime_registry.resolve_runtime_plan.return_value = expected_plan

    # Execute
    res = await runtime_skill_service.resolve_autonomy_execution_plan(
        learner_goal_id="g1",
        skill_name="test_skill",
        surface="test_surface",
        resource_id="r1",
    )

    # Verify
    assert res == expected_plan
    mock_runtime_registry.resolve_runtime_plan.assert_called_once_with(
        learner_goal_id="g1",
        skill_name="test_skill",
        surface="test_surface",
        resource_id="r1",
        topic_key=None,
        task_type=None,
        trigger_source=None,
        include_staged=False,
    )


@pytest.mark.asyncio
async def test_resolve_autonomy_execution_plan_fallback(
    runtime_skill_service, mock_runtime_registry, mock_skill_usage_service, mock_goal_skill_binding_resolver
):
    # Setup
    mock_runtime_registry.resolve_runtime_plan.return_value = None
    binding = MagicMock(spec=ActiveGoalSkillBinding)
    binding.binding_id = "test_binding_id"
    binding.rollout_id = "test_rollout_id"
    binding.runtime_directives = {}
    binding.tool_plan = []
    mock_goal_skill_binding_resolver.get_active_binding.return_value = binding
    
    plan_mock = MagicMock()
    mock_skill_usage_service.resolve_execution_plan.return_value = plan_mock

    # Execute
    res = await runtime_skill_service.resolve_autonomy_execution_plan(
        learner_goal_id="g1",
        skill_name="test_skill",
        surface="test_surface",
        resource_id="r1",
    )

    # Verify
    assert res is not None
    mock_skill_usage_service.resolve_execution_plan.assert_called_once_with(
        skill_name="test_skill",
        surface="test_surface",
        resource_id="r1",
        skill_binding=binding,
    )


@pytest.mark.asyncio
async def test_execute_runtime_tool_plan_no_plan(runtime_skill_service, mock_internal_tool_registry):
    # Setup
    context = ToolPlanExecutionContext(
        surface="test_surface",
        learner_goal_id="g1",
        resource_id="r1",
        actor="system",
    )
    mock_internal_tool_registry.execute.return_value = {"status": "ok"}

    # Execute
    report = await runtime_skill_service.execute_runtime_tool_plan(
        runtime_plan=None,
        context=context,
        default_tool_name="default_tool",
        default_payload={"param": "val"},
    )

    # Verify
    assert report.surface == "test_surface"
    assert len(report.steps) == 1
    assert report.steps[0].tool_name == "default_tool"
    assert report.steps[0].result_payload == {"status": "ok"}
    mock_internal_tool_registry.execute.assert_called_once()


@pytest.mark.asyncio
async def test_execute_runtime_tool_plan_with_plan(runtime_skill_service, mock_tool_plan_runtime_executor):
    # Setup
    runtime_plan = MagicMock(spec=RuntimeSkillExecutionPlan)
    runtime_plan.tool_plan = ["step1"]
    context = ToolPlanExecutionContext(
        surface="test_surface",
        learner_goal_id="g1",
        resource_id="r1",
        actor="system",
    )
    expected_report = MagicMock(spec=MultiStepToolPlanExecutionReport)
    mock_tool_plan_runtime_executor.execute.return_value = expected_report

    # Execute
    report = await runtime_skill_service.execute_runtime_tool_plan(
        runtime_plan=runtime_plan,
        context=context,
        default_tool_name="default_tool",
    )

    # Verify
    assert report == expected_report
    mock_tool_plan_runtime_executor.execute.assert_called_once_with(
        surface="test_surface",
        tool_plan=["step1"],
        context=context,
        dry_run=False,
    )


def test_build_tool_plan_execution_context(runtime_skill_service):
    context = runtime_skill_service.build_tool_plan_execution_context(
        surface="surface1",
        learner_goal_id="goal1",
        resource_id="res1",
        topic_focus="topic1",
        study_plan_id="plan1",
        source_task_id="task1",
        workflow_run_id="run1",
        scheduled_job_id="job1",
    )
    assert context.surface == "surface1"
    assert context.learner_goal_id == "goal1"
    assert context.resource_id == "res1"
    assert context.topic_focus == "topic1"
    assert context.study_plan_id == "plan1"
    assert context.source_task_id == "task1"
    assert context.workflow_run_id == "run1"
    assert context.scheduled_job_id == "job1"


@pytest.mark.asyncio
async def test_resolve_skills_for_runtime(runtime_skill_service, mock_skill_usage_service):
    # Setup
    goal = MagicMock(spec=LearnerGoal)
    goal.id = "g1"
    task = MagicMock(spec=DailyTask)
    task.id = "t1"
    expected_res = MagicMock(spec=SkillResolution)
    mock_skill_usage_service.resolve_for_runtime.return_value = expected_res

    # Test review
    res = await runtime_skill_service.resolve_review_skill_for_runtime(goal=goal, source_task=task)
    assert res == expected_res
    mock_skill_usage_service.resolve_for_runtime.assert_called_with(
        skill_name="schedule_review",
        surface="review_scheduling",
        resource_id="t1",
    )

    # Test replan
    res = await runtime_skill_service.resolve_replan_skill_for_runtime(goal=goal, resource_id="r1")
    assert res == expected_res
    mock_skill_usage_service.resolve_for_runtime.assert_called_with(
        skill_name="plan_study_path",
        surface="replan",
        resource_id="r1",
    )

    # Test assessment
    active_plan = MagicMock(spec=StudyPlan)
    active_plan.id = "sp1"
    res = await runtime_skill_service.resolve_assessment_skill_for_runtime(goal=goal, active_plan=active_plan, topic_key="topic_key")
    assert res == expected_res
    mock_skill_usage_service.resolve_for_runtime.assert_called_with(
        skill_name="create_quiz",
        surface="assessment_generation",
        resource_id="sp1",
    )


@pytest.mark.asyncio
async def test_schedule_rollout_observations(runtime_skill_service, mock_rollout_observation_scheduler):
    # Test schedule rollout observation
    await runtime_skill_service.schedule_surface_rollout_observation(
        learner_goal_id="g1",
        surface="s1",
        trigger_source="ts1",
        source_ref="ref1",
    )
    mock_rollout_observation_scheduler.schedule_active.assert_called_once_with(
        learner_goal_id="g1",
        surface="s1",
        trigger_source="ts1",
        source_ref="ref1",
    )

    # Test schedule failure rollout observation
    mock_rollout_observation_scheduler.schedule_active.reset_mock()
    await runtime_skill_service.schedule_runtime_failure_rollout_observation(
        learner_goal_id="g1",
        surface="s1",
        trigger_source="ts1",
        source_ref="ref2",
    )
    mock_rollout_observation_scheduler.schedule_active.assert_called_once_with(
        learner_goal_id="g1",
        surface="s1",
        trigger_source="ts1",
        source_ref="ref2",
    )


@pytest.mark.asyncio
async def test_get_rollout_overlay_payload(runtime_skill_service, mock_rollout_resolver):
    # Setup
    overlay = MagicMock()
    overlay.payload = {"k": "v"}
    mock_rollout_resolver.get_active_overlay.return_value = overlay

    # Execute
    res = await runtime_skill_service.get_rollout_overlay_payload(learner_goal_id="g1", surface="s1")

    # Verify
    assert res == {"k": "v"}
    mock_rollout_resolver.get_active_overlay.assert_called_once_with(
        learner_goal_id="g1",
        surface="s1",
        include_staged=False,
    )


@pytest.mark.asyncio
async def test_get_skill_binding(runtime_skill_service, mock_goal_skill_binding_resolver):
    # Setup
    binding = MagicMock(spec=ActiveGoalSkillBinding)
    mock_goal_skill_binding_resolver.get_active_binding.return_value = binding

    # Execute
    res = await runtime_skill_service.get_skill_binding(
        learner_goal_id="g1",
        surface="s1",
    )

    # Verify
    assert res == binding
    mock_goal_skill_binding_resolver.get_active_binding.assert_called_once_with(
        learner_goal_id="g1",
        surface="s1",
        topic_key=None,
        task_type=None,
        trigger_source=None,
        include_staged=False,
    )


@pytest.mark.asyncio
async def test_review_intervals(runtime_skill_service, mock_review_service):
    # Setup
    mastery = MagicMock(spec=LearnerTopicMastery)
    mock_review_service.get_review_intervals.return_value = [1, 2, 3]

    # Execute
    res = await runtime_skill_service.review_intervals("g1", mastery)

    # Verify
    assert res == [1, 2, 3]
    mock_review_service.get_review_intervals.assert_called_once_with("g1", mastery)
