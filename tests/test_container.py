from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.task_plan_lifecycle import TaskPlanLifecycleService
from agent_core.application.services.task_status_update_support import TaskStatusUpdateSupportService
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.autonomy import TaskAttempt
from agent_core.domain.entities.planning import DailyTask
from agent_core.domain.schemas.planning import UpdateDailyTaskStatusRequest
from agent_core.infrastructure.container import ApplicationContainer


class _FakeAutonomyJobDispatcher:
    def __init__(self) -> None:
        self._handlers: dict = {}

    def register_handler(self, job_type: str, handler: object) -> None:
        self._handlers[job_type] = handler


class _FakeAutonomyScheduling:
    def __init__(self) -> None:
        self._autonomy_job_dispatcher = _FakeAutonomyJobDispatcher()


@dataclass
class _FakeTaskCore:
    session_id: int
    _planner_service: object | None = None
    _audit_service: object | None = None
    _session_service: object | None = None
    _chat_service: object | None = None
    _quiz_service: object | None = None
    _workflow_run_service: object | None = None
    _memory_service: object | None = None
    _goal_autonomy_state_repository: object | None = None
    _autonomy_job_repository: object | None = None
    _learner_availability_repository: object | None = None
    _learner_topic_mastery_repository: object | None = None
    _task_attempt_repository: object | None = None
    _autonomy_job_service: object | None = None
    _reflection_service: object | None = None
    _reflection_evidence_service: object | None = None
    _reflection_outcome_service: object | None = None
    _rollout_observation_scheduler: object | None = None
    _long_term_memory_materialization_service: object | None = None
    _should_schedule_assessment: object | None = None
    _derive_replan_mode: object | None = None
    _run_inline_status_followups: object | None = None
    _process_autonomy_job: object | None = None
    _runtime_registry: object | None = None
    _skill_usage_service: object | None = None
    _goal_skill_binding_resolver: object | None = None
    _tool_plan_runtime_executor: object | None = None
    _internal_tool_registry: object | None = None
    _rollout_resolver: object | None = None
    _autonomy_scheduling: object = _FakeAutonomyScheduling()
    _plan_lifecycle: object | None = None
    _execution: object | None = None

    @property
    def plan_lifecycle(self):
        return self._plan_lifecycle

    @property
    def execution(self):
        return self._execution

    @property
    def autonomy_scheduling(self):
        return self._autonomy_scheduling

    @property
    def autonomy_job_dispatcher(self):
        return self._autonomy_scheduling._autonomy_job_dispatcher

    @property
    def runtime_registry(self):
        return self._runtime_registry

    @property
    def skill_usage_service(self):
        return self._skill_usage_service

    @property
    def goal_skill_binding_resolver(self):
        return self._goal_skill_binding_resolver

    @property
    def tool_plan_runtime_executor(self):
        return self._tool_plan_runtime_executor

    @property
    def internal_tool_registry(self):
        return self._internal_tool_registry

    @property
    def rollout_resolver(self):
        return self._rollout_resolver

    @property
    def rollout_observation_scheduler(self):
        return self._rollout_observation_scheduler

    @property
    def task_attempt_repository(self):
        return self._task_attempt_repository

    async def _sync_goal_state_after_plan(self, goal_id: str, plan_id: str, trigger_source: str) -> None:
        return None

    async def _schedule_surface_rollout_observation(
        self,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> None:
        return None

    async def _trigger_workflow_failure_reflection(
        self,
        goal_learner_profile_id: str,
        goal_id: str,
        workflow_run_id: str,
        daily_task_id: str | None = None,
        study_plan_id: str | None = None,
    ) -> None:
        return None


@dataclass
class _FakeMemoryService:
    session_id: int


class _StubAuditRepository:
    def __init__(self) -> None:
        self.events = []

    async def create(self, entity):
        self.events.append(entity)


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


class _StubTaskRepository:
    def __init__(self, task: DailyTask) -> None:
        self.task = task

    async def get_by_id(self, task_id: str):
        if self.task.id == task_id:
            return self.task
        return None

    async def update(self, task: DailyTask) -> None:
        self.task = task


class _UnusedRepository:
    def __getattr__(self, name: str):
        raise AssertionError(f"Unexpected repository call: {name}")


class _NoopSupport(TaskStatusUpdateSupportService):
    def __init__(self) -> None:
        pass

    async def record_attempt_and_update_mastery(self, task: DailyTask) -> TaskAttempt | None:
        return None

    async def coordinate_post_update(self, task: DailyTask, attempt: TaskAttempt | None) -> None:
        return None


def test_request_scope_caches_task_services():
    calls: list[int] = []

    def build_task_core(session):
        calls.append(id(session))
        return _FakeTaskCore(session_id=id(session))

    container = ApplicationContainer(
        task_core_builder=build_task_core,
        memory_service_builder=lambda session: _FakeMemoryService(session_id=id(session)),
    )
    session = object()
    scope = container.scope(session)

    first = scope.task_services()
    second = scope.task_services()

    assert first is second
    assert first.core.session_id == id(session)
    assert calls == [id(session)]


def test_request_scope_caches_memory_service():
    container = ApplicationContainer(
        task_core_builder=lambda session: _FakeTaskCore(session_id=id(session)),
        memory_service_builder=lambda session: _FakeMemoryService(session_id=id(session)),
    )
    session = object()
    scope = container.scope(session)

    first = scope.memory_service()
    second = scope.memory_service()

    assert first is second
    assert first.session_id == id(session)


@pytest.mark.asyncio
async def test_task_plan_lifecycle_updates_status_without_default_core_delegation():
    session = _FakeAsyncSession()
    audit_repository = _StubAuditRepository()
    audit_service = AuditService(audit_repository)

    profile = LearnerProfile.build()
    goal = LearnerGoal.build(
        learner_profile_id=profile.id,
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix drills independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=14),
        weekly_study_minutes=180,
    )
    task = DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id="plan-1",
        plan_stage_id=None,
        task_origin="planner",
        task_type="practice",
        execution_mode="chat",
        title="Matrix basics",
        instructions="Practice row operations",
        topic_focus="Row operations",
        difficulty="medium",
        question_count=None,
        estimated_minutes=20,
        scheduled_for=date.today(),
        due_on=date.today(),
    )
    goal_repository = _StubGoalRepository(goal)
    task_repository = _StubTaskRepository(task)

    class _ExplodingCore:
        def __init__(self) -> None:
            self.update_called = False
            self.record_calls = []
            self.mastery_calls = []

        async def update_task_status(self, *, task_id: str, payload: UpdateDailyTaskStatusRequest):
            self.update_called = True
            raise AssertionError("TaskPlanLifecycleService should not delegate update_task_status to core")

        async def _record_task_attempt(self, updated_task: DailyTask):
            self.record_calls.append(updated_task.id)
            return None

        async def _update_topic_mastery(self, updated_task: DailyTask):
            self.mastery_calls.append(updated_task.id)

    class _TrackingSupport(_NoopSupport):
        def __init__(self) -> None:
            self.record_calls: list[str] = []
            self.coordination_calls: list[tuple[str, None]] = []

        async def record_attempt_and_update_mastery(self, task: DailyTask) -> TaskAttempt | None:
            self.record_calls.append(task.id)
            return None

        async def coordinate_post_update(self, task: DailyTask, attempt: TaskAttempt | None) -> None:
            self.coordination_calls.append((task.id, attempt))

    core = _ExplodingCore()
    support = _TrackingSupport()
    service = TaskPlanLifecycleService(
        db_session=session,
        goal_repository=goal_repository,
        study_plan_repository=_UnusedRepository(),
        plan_stage_repository=_UnusedRepository(),
        daily_task_repository=task_repository,
        workflow_run_repository=_UnusedRepository(),
        planner_service=_UnusedRepository(),
        workflow_run_service=_UnusedRepository(),
        audit_service=audit_service,
        status_update_support=support,
    )

    updated = await service.update_task_status(
        task_id=task.id,
        payload=UpdateDailyTaskStatusRequest(status="completed", result_note="Done"),
    )

    assert updated.status == "completed"
    assert core.update_called is False
    assert core.record_calls == []
    assert core.mastery_calls == []
    assert support.record_calls == [task.id]
    assert support.coordination_calls == [(task.id, None)]
    assert session.committed == 1
    assert any(event.event_type == "daily_task.status.updated" for event in audit_repository.events)
