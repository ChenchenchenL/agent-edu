"""测试TaskService真实迁移的行为一致性.

确保从AutonomousTaskService迁移到专注服务后，行为保持不变。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.planner import MaterializedPlan
from agent_core.application.services.task_plan_lifecycle import TaskPlanLifecycleService
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.planning import DailyTask, PlanStage, StudyPlan
from agent_core.infrastructure.llm.types import StudyPlanDraft, StudyPlanStageDraft, StudyPlanTaskDraft
from agent_core.infrastructure.db.repositories import (
    PlanStageRepository,
    DailyTaskRepository,
    LearnerGoalRepository,
    StudyPlanRepository,
)


@pytest.fixture
def mock_session():
    """模拟数据库session."""
    class MockSession:
        pass
    return MockSession()


@pytest.fixture
def plan_lifecycle_service(mock_session):
    """创建TaskPlanLifecycleService用于测试."""
    return TaskPlanLifecycleService(
        db_session=mock_session,
        goal_repository=LearnerGoalRepository(mock_session),
        study_plan_repository=StudyPlanRepository(mock_session),
        plan_stage_repository=PlanStageRepository(mock_session),
        daily_task_repository=DailyTaskRepository(mock_session),
        workflow_run_repository=_UnusedRepository(),
        planner_service=_UnusedRepository(),
        workflow_run_service=_UnusedRepository(),
    )


class _UnusedRepository:
    def __getattr__(self, name: str):
        raise AssertionError(f"Unexpected repository call: {name}")


class _FakeAsyncSession:
    def __init__(self) -> None:
        self.committed = 0
        self.rolled_back = 0

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        self.rolled_back += 1


class _StubGoalRepository:
    def __init__(self, goal: LearnerGoal) -> None:
        self.goal = goal

    async def get_by_id(self, goal_id: str):
        if self.goal.id == goal_id:
            return self.goal
        return None


class _StubStudyPlanRepository:
    def __init__(self, active_plan: StudyPlan | None = None) -> None:
        self.active_plan = active_plan
        self.created: list[StudyPlan] = []
        self.updated: list[StudyPlan] = []
        self.by_id: dict[str, StudyPlan] = {}

    async def get_active_by_goal(self, goal_id: str):
        if self.active_plan is not None and self.active_plan.learner_goal_id == goal_id:
            return self.active_plan
        return None

    async def create(self, plan: StudyPlan) -> None:
        self.created.append(plan)
        self.by_id[plan.id] = plan

    async def update(self, plan: StudyPlan) -> None:
        self.updated.append(plan)
        self.by_id[plan.id] = plan

    async def get_by_id(self, plan_id: str):
        return self.by_id.get(plan_id)


class _StubPlanStageRepository:
    def __init__(self) -> None:
        self.created_batches: list[list[PlanStage]] = []
        self.by_plan_id: dict[str, list[PlanStage]] = {}

    async def create_many(self, stages: list[PlanStage]) -> None:
        self.created_batches.append(stages)
        if stages:
            self.by_plan_id[stages[0].study_plan_id] = stages

    async def list_by_plan(self, plan_id: str):
        return self.by_plan_id.get(plan_id, [])


class _StubDailyTaskRepository:
    def __init__(self) -> None:
        self.created_batches: list[list[DailyTask]] = []
        self.superseded_plan_ids: list[str] = []

    async def create_many(self, tasks: list[DailyTask]) -> None:
        self.created_batches.append(tasks)

    async def bulk_mark_superseded(self, plan_id: str) -> None:
        self.superseded_plan_ids.append(plan_id)


class _StubAuditRepository:
    def __init__(self) -> None:
        self.events = []

    async def create(self, entity):
        self.events.append(entity)


@dataclass
class _WorkflowRun:
    id: str


class _StubWorkflowRunService:
    def __init__(self) -> None:
        self.create_calls: list[dict[str, object]] = []
        self.complete_calls: list[dict[str, object]] = []
        self.fail_calls: list[dict[str, object]] = []
        self._counter = 0

    async def create_run(self, **kwargs):
        self._counter += 1
        self.create_calls.append(kwargs)
        return _WorkflowRun(id=f"run-{self._counter}")

    async def complete_run(self, **kwargs):
        self.complete_calls.append(kwargs)
        return kwargs["run"]

    async def fail_run(self, **kwargs):
        self.fail_calls.append(kwargs)
        return kwargs["run"]


class _StubMemoryService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def build_interpretation(self, **kwargs):
        self.calls.append(kwargs)
        return None


class _ExplodingCore:
    def __init__(self) -> None:
        self.generate_called = False

    async def generate_plan(self, **kwargs):
        self.generate_called = True
        raise AssertionError("TaskPlanLifecycleService should not delegate generate_plan to core")


class _StubPlannerService:
    def __init__(self, materialized_plan: MaterializedPlan) -> None:
        self.materialized_plan = materialized_plan
        self.calls: list[dict[str, object]] = []

    async def build_plan(self, **kwargs) -> MaterializedPlan:
        self.calls.append(kwargs)
        return self.materialized_plan


class TestGetPlanMigration:
    """测试get_plan方法迁移."""

    async def test_get_plan_returns_study_plan_response(self, plan_lifecycle_service):
        """测试get_plan返回StudyPlanResponse."""
        # 这是一个占位测试，真实实现后需要mock repository
        # 验证：给定plan_id，返回正确的StudyPlanResponse
        pass

    async def test_get_plan_raises_not_found_error_when_missing(self, plan_lifecycle_service):
        """测试plan不存在时抛出NotFoundError."""
        # 验证：plan_id不存在时，抛出NotFoundError
        pass

    async def test_get_plan_includes_stages(self, plan_lifecycle_service):
        """测试返回的plan包含stages."""
        # 验证：返回的StudyPlanResponse包含plan_stages字段
        pass


class TestListPlansMigration:
    """测试list_plans方法迁移."""

    async def test_list_plans_returns_all_goal_plans(self, plan_lifecycle_service):
        """测试list_plans返回目标的所有计划."""
        pass


class TestGetTaskMigration:
    """测试get_task方法迁移."""

    async def test_get_task_returns_task_response(self, plan_lifecycle_service):
        """测试get_task返回DailyTaskResponse."""
        pass

    async def test_get_task_raises_not_found_when_missing(self, plan_lifecycle_service):
        """测试task不存在时抛出NotFoundError."""
        pass


class TestListTasksMigration:
    """测试list_tasks方法迁移."""

    async def test_list_tasks_with_status_filter(self, plan_lifecycle_service):
        """测试按状态过滤任务."""
        pass

    async def test_list_tasks_with_date_range(self, plan_lifecycle_service):
        """测试按日期范围过滤任务."""
        pass


class TestUpdateTaskStatusMigration:
    """测试update_task_status方法迁移."""

    async def test_update_task_status_changes_status(self, plan_lifecycle_service):
        """测试更新任务状态."""
        pass

    async def test_update_task_status_records_audit_log(self, plan_lifecycle_service):
        """测试状态更新记录审计日志."""
        pass


# 迁移完成的验收标准
class TestMigrationCompleteness:
    """验证迁移完成度."""

    def test_all_lifecycle_methods_migrated(self):
        """验证所有生命周期方法已迁移到TaskPlanLifecycleService."""
        service = TaskPlanLifecycleService
        required_methods = [
            'generate_plan',
            'list_plans',
            'get_plan',
            'list_tasks',
            'get_task',
            'update_task_status',
            'list_workflow_runs',
            'get_workflow_run',
        ]
        for method in required_methods:
            assert hasattr(service, method), f"Missing method: {method}"

    def test_service_has_real_dependencies(self):
        """验证服务有真实依赖，不是只依赖core."""
        import inspect
        sig = inspect.signature(TaskPlanLifecycleService.__init__)
        params = list(sig.parameters.keys())

        # 应该有真实依赖，不是只有core参数
        assert 'db_session' in params or len(params) > 2, \
            "Service should have real dependencies, not just 'core'"


@pytest.mark.asyncio
async def test_generate_plan_runs_real_lifecycle_logic_without_core_delegation():
    session = _FakeAsyncSession()
    audit_repository = _StubAuditRepository()
    audit_service = AuditService(audit_repository)

    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master calculus",
        subject="Calculus",
        target_outcome="Handle derivative drills",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=240,
    )

    draft = StudyPlanDraft(
        plan_summary="Derivative plan",
        stages=[
            StudyPlanStageDraft(
                title="Foundations",
                objective="Refresh limits and derivative rules",
                focus_topics=["limits", "derivatives"],
            )
        ],
        tasks=[
            StudyPlanTaskDraft(
                stage_position=1,
                scheduled_for=date.today(),
                due_on=date.today(),
                task_type="practice",
                execution_mode="chat",
                title="Derivative warmup",
                instructions="Solve 5 derivative problems",
                topic_focus="derivatives",
                difficulty="medium",
                question_count=None,
                estimated_minutes=25,
            )
        ],
        provider="test-provider",
        model="test-model",
        latency_ms=12,
        retry_count=0,
        response_shape_valid=True,
        fallback_used=False,
    )
    study_plan = StudyPlan.build(
        learner_goal_id=goal.id,
        version=1,
        trigger_source="initial",
        plan_summary=draft.plan_summary,
        blueprint_payload={},
        materialized_until_date=date.today() + timedelta(days=13),
        supersedes_plan_id=None,
    )
    stage = PlanStage.build(
        study_plan_id=study_plan.id,
        position=1,
        title="Foundations",
        objective="Refresh limits and derivative rules",
        focus_topics=["limits", "derivatives"],
        start_date=date.today(),
        end_date=date.today() + timedelta(days=6),
    )
    task = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id=study_plan.id,
        plan_stage_id=stage.id,
        task_origin="planner",
        task_type="practice",
        execution_mode="chat",
        title="Derivative warmup",
        instructions="Solve 5 derivative problems",
        topic_focus="derivatives",
        difficulty="medium",
        question_count=None,
        estimated_minutes=25,
        scheduled_for=date.today(),
        due_on=date.today(),
    )
    planner_service = _StubPlannerService(
        MaterializedPlan(
            study_plan=study_plan,
            stages=[stage],
            tasks=[task],
            llm_draft=draft,
        )
    )
    workflow_service = _StubWorkflowRunService()
    memory_service = _StubMemoryService()
    core = _ExplodingCore()
    study_plan_repository = _StubStudyPlanRepository()
    plan_stage_repository = _StubPlanStageRepository()
    daily_task_repository = _StubDailyTaskRepository()

    sync_calls: list[tuple[str, str, str]] = []
    rollout_calls: list[tuple[str, str, str, str]] = []
    reflection_calls: list[tuple[str, str, str, str | None, str | None]] = []

    service = TaskPlanLifecycleService(
        db_session=session,
        goal_repository=_StubGoalRepository(goal),
        study_plan_repository=study_plan_repository,
        plan_stage_repository=plan_stage_repository,
        daily_task_repository=daily_task_repository,
        workflow_run_repository=_UnusedRepository(),
        planner_service=planner_service,
        workflow_run_service=workflow_service,
        audit_service=audit_service,
        memory_service=memory_service,
        status_update_support=None,
        sync_goal_state_after_plan=lambda goal_id, plan_id, trigger: _append_and_return(
            sync_calls, (goal_id, plan_id, trigger)
        ),
        schedule_rollout_observation=lambda learner_goal_id, surface, trigger_source, source_ref: _append_and_return(
            rollout_calls, (learner_goal_id, surface, trigger_source, source_ref)
        ),
        trigger_workflow_failure_reflection=lambda profile_id, goal_id, workflow_run_id, daily_task_id, study_plan_id: _append_and_return(
            reflection_calls,
            (profile_id, goal_id, workflow_run_id, daily_task_id, study_plan_id),
        ),
    )
    service._legacy_core = core  # sentinel: should remain unused

    response = await service.generate_plan(goal_id=goal.id, trigger_source="initial")

    assert response.id == study_plan.id
    assert getattr(core, "generate_called", False) is False
    assert session.committed == 1
    assert workflow_service.create_calls[0]["workflow_type"] == "plan_generation"
    assert workflow_service.complete_calls[0]["result_resource_ids"] == [study_plan.id, task.id]
    assert planner_service.calls[0]["goal"].id == goal.id
    assert memory_service.calls[0]["learner_goal_id"] == goal.id
    assert study_plan_repository.created == [study_plan]
    assert plan_stage_repository.created_batches == [[stage]]
    assert daily_task_repository.created_batches == [[task]]
    assert sync_calls == [(goal.id, study_plan.id, "initial")]
    assert len(rollout_calls) == 1
    assert reflection_calls == []
    assert any(event.event_type == "study_plan.generated" for event in audit_repository.events)
    assert any(event.event_type == "daily_task.created" for event in audit_repository.events)


async def _append_and_return(target: list, item) -> None:
    target.append(item)
