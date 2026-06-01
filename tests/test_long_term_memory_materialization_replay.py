from datetime import date, timedelta, timezone, datetime

from agent_core.application.services.audit import AuditService
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationResult
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayExecutor,
)
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob, TaskAttempt
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.memory import MemoryEvent
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.planning import DailyTask
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.entities.session import LearningSession


class StubAuditRepository:
    def __init__(self):
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent):
        self.events.append(entity)


class StubSessionRepository:
    def __init__(self, session: LearningSession):
        self.session = session

    async def get_by_id(self, session_id: str):
        return self.session if self.session.id == session_id else None


class StubMessageRepository:
    def __init__(self, messages: list[SessionMessage]):
        self.messages = {item.id: item for item in messages}

    async def get_by_id(self, message_id: str):
        return self.messages.get(message_id)


class StubMemoryEventRepository:
    def __init__(self, events: list[MemoryEvent]):
        self.events = list(events)

    async def list_by_session(self, session_id: str, *, limit: int = 50):
        return [item for item in self.events if item.session_id == session_id][:limit]


class StubGoalRepository:
    def __init__(self, goal: LearnerGoal):
        self.goal = goal

    async def get_by_id(self, goal_id: str):
        return self.goal if self.goal.id == goal_id else None


class StubDailyTaskRepository:
    def __init__(self, task: DailyTask):
        self.task = task

    async def get_by_id(self, task_id: str):
        return self.task if self.task.id == task_id else None


class StubTaskAttemptRepository:
    def __init__(self, attempt: TaskAttempt):
        self.attempt = attempt

    async def get_by_id(self, attempt_id: str):
        return self.attempt if self.attempt.id == attempt_id else None


class StubReflectionRecordRepository:
    def __init__(self, reflection: ReflectionRecord):
        self.reflection = reflection

    async def get_by_id(self, reflection_id: str):
        return self.reflection if self.reflection.id == reflection_id else None


class StubReflectionOutcomeEvaluationRepository:
    def __init__(self, evaluation: ReflectionOutcomeEvaluation):
        self.evaluation = evaluation

    async def get_by_id(self, evaluation_id: str):
        return self.evaluation if self.evaluation.id == evaluation_id else None


class CapturingMaterializationService:
    def __init__(self):
        self.chat_calls = []
        self.task_calls = []
        self.reflection_calls = []

    async def materialize_from_chat_turn(self, **kwargs):
        self.chat_calls.append(kwargs)
        return LongTermMemoryMaterializationResult(knowledge=[], behavior=[])

    async def materialize_from_task_outcome(self, **kwargs):
        self.task_calls.append(kwargs)
        return LongTermMemoryMaterializationResult(knowledge=[], behavior=[])

    async def materialize_from_reflection_outcome(self, **kwargs):
        self.reflection_calls.append(kwargs)
        return LongTermMemoryMaterializationResult(knowledge=[], behavior=[])


async def test_replay_executor_reconstructs_chat_turn_from_source_ids():
    goal = _goal()
    session = LearningSession.build(
        learner_profile_id=goal.learner_profile_id,
        learner_goal_id=goal.id,
        title="Linear Algebra",
        subject="Matrices",
    )
    user_message = SessionMessage.build(
        session_id=session.id,
        role="user",
        content="Explain determinants.",
        mode="chat",
        skill_trace=[],
    )
    assistant_message = SessionMessage.build(
        session_id=session.id,
        role="assistant",
        content="Let's connect determinants to area scaling.",
        mode="chat",
        skill_trace=["explain_concept"],
    )
    profile_event = MemoryEvent.build(
        session_id=session.id,
        learner_profile_id=goal.learner_profile_id,
        event_type="session.note",
        memory_scope="profile",
        memory_level="semantic",
        summary="Learner is reviewing determinants.",
        progress_note=None,
        struggle_note="determinants",
        concept_focus="determinants",
        source_message_id=user_message.id,
        tags=["profile"],
    )
    unrelated_event = MemoryEvent.build(
        session_id=session.id,
        learner_profile_id=goal.learner_profile_id,
        event_type="session.note",
        memory_scope="profile",
        memory_level="semantic",
        summary="Unrelated turn.",
        progress_note=None,
        struggle_note=None,
        concept_focus="matrices",
        source_message_id="other-message",
        tags=["profile"],
    )
    materialization_service = CapturingMaterializationService()
    audit_repository = StubAuditRepository()
    executor = LongTermMemoryMaterializationReplayExecutor(
        session_repository=StubSessionRepository(session),
        message_repository=StubMessageRepository([user_message, assistant_message]),
        memory_event_repository=StubMemoryEventRepository([profile_event, unrelated_event]),
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository(_task(goal)),
        task_attempt_repository=StubTaskAttemptRepository(_attempt(goal, "task-1")),
        reflection_record_repository=StubReflectionRecordRepository(_reflection(goal)),
        reflection_outcome_evaluation_repository=StubReflectionOutcomeEvaluationRepository(_evaluation(goal, "reflection-1")),
        materialization_service=materialization_service,
        audit_service=AuditService(audit_repository),
    )
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="long_term_memory_materialization_replay",
        trigger_source="test",
        due_at=datetime.now(timezone.utc),
        idempotency_key="ltm-replay:chat",
        payload={
            "source_type": "chat_turn",
            "session_id": session.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
        },
    )

    await executor.replay(job)

    assert len(materialization_service.chat_calls) == 1
    call = materialization_service.chat_calls[0]
    assert call["learner_message"] == user_message.content
    assert call["assistant_message"] == assistant_message.content
    assert call["source_message_id"] == user_message.id
    assert call["memory_events"] == [profile_event]
    assert any(item.event_type == "long_term_memory.materialization.replayed" for item in audit_repository.events)


async def test_replay_executor_reconstructs_task_outcome_from_source_ids():
    goal = _goal()
    task = _task(goal)
    attempt = _attempt(goal, task.id)
    materialization_service = CapturingMaterializationService()
    audit_repository = StubAuditRepository()
    executor = LongTermMemoryMaterializationReplayExecutor(
        session_repository=StubSessionRepository(
            LearningSession.build(
                learner_profile_id=goal.learner_profile_id,
                learner_goal_id=goal.id,
                title="Linear Algebra",
                subject="Matrices",
            )
        ),
        message_repository=StubMessageRepository([]),
        memory_event_repository=StubMemoryEventRepository([]),
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository(task),
        task_attempt_repository=StubTaskAttemptRepository(attempt),
        reflection_record_repository=StubReflectionRecordRepository(_reflection(goal)),
        reflection_outcome_evaluation_repository=StubReflectionOutcomeEvaluationRepository(_evaluation(goal, "reflection-1")),
        materialization_service=materialization_service,
        audit_service=AuditService(audit_repository),
    )
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="long_term_memory_materialization_replay",
        trigger_source="test",
        due_at=datetime.now(timezone.utc),
        idempotency_key="ltm-replay:task",
        payload={"source_type": "task_outcome", "task_id": task.id, "attempt_id": attempt.id},
    )

    await executor.replay(job)

    assert len(materialization_service.task_calls) == 1
    assert materialization_service.task_calls[0]["learner_profile_id"] == goal.learner_profile_id
    assert materialization_service.task_calls[0]["task"] == task
    assert materialization_service.task_calls[0]["attempt"] == attempt


async def test_replay_executor_reconstructs_reflection_outcome_from_source_ids():
    goal = _goal()
    reflection = _reflection(goal)
    evaluation = _evaluation(goal, reflection.id)
    materialization_service = CapturingMaterializationService()
    audit_repository = StubAuditRepository()
    executor = LongTermMemoryMaterializationReplayExecutor(
        session_repository=StubSessionRepository(
            LearningSession.build(
                learner_profile_id=goal.learner_profile_id,
                learner_goal_id=goal.id,
                title="Linear Algebra",
                subject="Matrices",
            )
        ),
        message_repository=StubMessageRepository([]),
        memory_event_repository=StubMemoryEventRepository([]),
        goal_repository=StubGoalRepository(goal),
        daily_task_repository=StubDailyTaskRepository(_task(goal)),
        task_attempt_repository=StubTaskAttemptRepository(_attempt(goal, "task-1")),
        reflection_record_repository=StubReflectionRecordRepository(reflection),
        reflection_outcome_evaluation_repository=StubReflectionOutcomeEvaluationRepository(evaluation),
        materialization_service=materialization_service,
        audit_service=AuditService(audit_repository),
    )
    job = ScheduledAutonomyJob.build(
        learner_goal_id=goal.id,
        job_type="long_term_memory_materialization_replay",
        trigger_source="test",
        due_at=datetime.now(timezone.utc),
        idempotency_key="ltm-replay:reflection",
        payload={
            "source_type": "reflection_outcome",
            "reflection_id": reflection.id,
            "evaluation_id": evaluation.id,
        },
    )

    await executor.replay(job)

    assert len(materialization_service.reflection_calls) == 1
    assert materialization_service.reflection_calls[0]["reflection"] == reflection
    assert materialization_service.reflection_calls[0]["evaluation"] == evaluation


def _goal() -> LearnerGoal:
    return LearnerGoal.build(
        learner_profile_id="profile-1",
        title="Master matrices",
        subject="Linear Algebra",
        target_outcome="Solve matrix exercises independently",
        baseline_note=None,
        deadline_date=date.today() + timedelta(days=21),
        weekly_study_minutes=180,
    )


def _task(goal: LearnerGoal) -> DailyTask:
    return DailyTask.build(
        learner_goal_id=goal.id,
        study_plan_id="plan-1",
        plan_stage_id=None,
        task_origin="planner",
        task_type="lesson",
        execution_mode="chat",
        title="Matrix basics",
        instructions="Learn matrix basics.",
        topic_focus="matrix multiplication",
        difficulty="medium",
        question_count=None,
        estimated_minutes=30,
        scheduled_for=date.today(),
        due_on=date.today(),
    ).with_status("completed", result_note="Done")


def _attempt(goal: LearnerGoal, task_id: str) -> TaskAttempt:
    return TaskAttempt.build(
        learner_goal_id=goal.id,
        daily_task_id=task_id,
        workflow_run_id="run-1",
        execution_session_id="session-1",
        task_type="lesson",
        topic_focus="matrix multiplication",
        outcome_status="completed",
        score=1.0,
        result_note="Done",
    )


def _reflection(goal: LearnerGoal) -> ReflectionRecord:
    return ReflectionRecord.build(
        learner_profile_id=goal.learner_profile_id,
        learner_goal_id=goal.id,
        daily_task_id="task-1",
        workflow_run_id="run-1",
        study_plan_id="plan-1",
        scope="task",
        target_type="daily_task",
        target_id="task-1",
        trigger_source="task_failed",
        reflection_depth=1,
        dedupe_key="reflection-1",
        aggregation_key="task:key",
        duplicate_count=0,
        priority_score=0.6,
        last_duplicate_at=None,
        cooldown_until=datetime.now(timezone.utc) + timedelta(hours=24),
        primary_root_cause="knowledge_gap",
        secondary_root_causes=[],
        severity="medium",
        confidence_score=0.8,
        summary="summary",
        evidence_summary="evidence",
        recommended_next_step="next",
        evidence_payload={"task": {"topic_focus": "matrix multiplication"}},
    )


def _evaluation(goal: LearnerGoal, reflection_id: str) -> ReflectionOutcomeEvaluation:
    return ReflectionOutcomeEvaluation.build(
        reflection_record_id=reflection_id,
        learner_goal_id=goal.id,
        topic_key="matrix multiplication",
        window_size=3,
        baseline_snapshot={},
    ).with_result(
        evaluation_status="effective",
        observed_attempt_count=3,
        outcome_snapshot={"success_count": 2},
        improvement_score=0.7,
        evaluation_note="improved",
        evaluated=True,
    )
