from __future__ import annotations

from agent_core.application.interfaces import (
    ChatServiceProtocol,
    DynamicRuntimeRegistryProtocol,
    GoalSkillBindingResolverProtocol,
    PlannerServiceProtocol,
    QuizServiceProtocol,
    ReflectionEvidenceServiceProtocol,
    ReflectionOutcomeServiceProtocol,
    ReflectionServiceProtocol,
    RolloutObservationSchedulerProtocol,
    RolloutResolverProtocol,
    SessionServiceProtocol,
    ToolPlanRuntimeExecutorProtocol,
    WorkflowRunServiceProtocol,
)


def test_protocols_accept_structural_stubs():
    class PlannerStub:
        async def build_plan(self, **kwargs):
            return kwargs

        async def extend_plan_window(self, **kwargs):
            return [], None

    class SessionStub:
        async def create_session(self, payload, daily_task_id=None, goal=None, commit=True):
            return payload

    class ChatStub:
        async def create_message(self, *, session_id, payload, commit=True):
            return payload

    class QuizStub:
        async def generate_quiz(self, payload, *, commit=True):
            return payload

    class WorkflowStub:
        async def create_run(self, **kwargs):
            return kwargs

        async def complete_run(self, *, run, result_resource_type, result_resource_ids):
            return run

        async def fail_run(self, *, run, error_code):
            return run

    class ReflectionStub:
        async def trigger_reflection(self, request):
            return request

        async def get_record(self, reflection_id):
            return reflection_id

        async def list_task_reflections(self, **kwargs):
            return kwargs

        async def apply_outcome_feedback(self, *, reflection, evaluation):
            return reflection

    class ReflectionEvidenceStub:
        async def derive_from_task(self, task):
            return None

    class ReflectionOutcomeStub:
        async def list_pending(self, *, learner_goal_id, limit=10):
            return []

        async def evaluate(self, *, reflection, topic_key):
            return {"reflection": reflection, "topic_key": topic_key}

    class RolloutResolverStub:
        async def get_active_overlay(self, **kwargs):
            return None

    class RolloutObservationStub:
        async def schedule_active(self, **kwargs):
            return None

    class BindingResolverStub:
        async def get_active_binding(self, **kwargs):
            return None

    class RuntimeRegistryStub:
        async def resolve_runtime_plan(self, **kwargs):
            return None

    class ToolPlanRuntimeStub:
        async def execute(self, *, tool_plan, context):
            return {"tool_plan": tool_plan, "context": context}

    planner: PlannerServiceProtocol = PlannerStub()
    session: SessionServiceProtocol = SessionStub()
    chat: ChatServiceProtocol = ChatStub()
    quiz: QuizServiceProtocol = QuizStub()
    workflow: WorkflowRunServiceProtocol = WorkflowStub()
    reflection: ReflectionServiceProtocol = ReflectionStub()
    reflection_evidence: ReflectionEvidenceServiceProtocol = ReflectionEvidenceStub()
    reflection_outcome: ReflectionOutcomeServiceProtocol = ReflectionOutcomeStub()
    rollout_resolver: RolloutResolverProtocol = RolloutResolverStub()
    rollout_observer: RolloutObservationSchedulerProtocol = RolloutObservationStub()
    binding_resolver: GoalSkillBindingResolverProtocol = BindingResolverStub()
    runtime_registry: DynamicRuntimeRegistryProtocol = RuntimeRegistryStub()
    tool_runtime: ToolPlanRuntimeExecutorProtocol = ToolPlanRuntimeStub()

    assert planner is not None
    assert session is not None
    assert chat is not None
    assert quiz is not None
    assert workflow is not None
    assert reflection is not None
    assert reflection_evidence is not None
    assert reflection_outcome is not None
    assert rollout_resolver is not None
    assert rollout_observer is not None
    assert binding_resolver is not None
    assert runtime_registry is not None
    assert tool_runtime is not None
