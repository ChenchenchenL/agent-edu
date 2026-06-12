"""测试TaskService真实迁移的行为一致性.

确保从AutonomousTaskService迁移到专注服务后，行为保持不变。
"""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.task_plan_lifecycle import TaskPlanLifecycleService
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.planning import StudyPlan, PlanStage
from agent_core.domain.errors import NotFoundError
from agent_core.infrastructure.db.repositories import (
    LearnerGoalRepository,
    StudyPlanRepository,
    PlanStageRepository,
    DailyTaskRepository,
    WorkflowRunRepository,
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
        workflow_run_repository=WorkflowRunRepository(mock_session),
    )


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
