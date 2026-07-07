from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.long_term_memory_materialization import (
    LongTermMemoryMaterializationResult,
    LongTermMemoryMaterializationService,
)
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    LearnerGoalRepository,
    MemoryEventRepository,
    ReflectionOutcomeEvaluationRepository,
    ReflectionRecordRepository,
    SessionMessageRepository,
    SessionRepository,
    TaskAttemptRepository,
    SessionQuizAnswerAttemptRepository,
)

LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE = "long_term_memory_materialization_replay"
LONG_TERM_MEMORY_REPLAY_TRIGGER_SOURCE = "long_term_memory_materialization_failed"
LONG_TERM_MEMORY_REPLAY_SOURCE_TYPES = {"chat_turn", "task_outcome", "reflection_outcome", "quiz_answer_attempt"}
INITIAL_REPLAY_DELAY = timedelta(minutes=5)
REPLAY_BACKOFF_STEPS = (
    timedelta(minutes=5),
    timedelta(minutes=15),
    timedelta(minutes=45),
)


@dataclass(frozen=True)
class LongTermMemoryReplayScheduleResult:
    enqueued: bool
    job_id: str | None
    idempotency_key: str | None
    due_at: datetime | None
    skip_reason: str | None = None
    error_code: str | None = None
    error: str | None = None

    def audit_payload(self) -> dict[str, Any]:
        return {
            "replay_enqueued": self.enqueued,
            "replay_job_id": self.job_id,
            "replay_idempotency_key": self.idempotency_key,
            "replay_due_at": self.due_at.isoformat() if self.due_at is not None else None,
            "replay_skip_reason": self.skip_reason,
            "replay_enqueue_error_code": self.error_code,
            "replay_enqueue_error": self.error,
        }


def long_term_memory_replay_backoff(attempt_count: int) -> timedelta:
    index = max(0, min(attempt_count - 1, len(REPLAY_BACKOFF_STEPS) - 1))
    return REPLAY_BACKOFF_STEPS[index]


class LongTermMemoryMaterializationReplayScheduler:
    def __init__(self, *, autonomy_job_service: AutonomyJobService | None) -> None:
        self._autonomy_job_service = autonomy_job_service

    async def schedule_chat_turn(
        self,
        *,
        learner_goal_id: str | None,
        session_id: str,
        user_message_id: str,
        assistant_message_id: str,
    ) -> LongTermMemoryReplayScheduleResult:
        idempotency_key = f"ltm-replay:chat_turn:{session_id}:{user_message_id}:{assistant_message_id}"
        if learner_goal_id is None:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=idempotency_key,
                due_at=None,
                skip_reason="missing_learner_goal_id",
            )
        return await self._schedule(
            learner_goal_id=learner_goal_id,
            idempotency_key=idempotency_key,
            payload={
                "source_type": "chat_turn",
                "session_id": session_id,
                "user_message_id": user_message_id,
                "assistant_message_id": assistant_message_id,
            },
        )

    async def schedule_task_outcome(
        self,
        *,
        learner_goal_id: str,
        task_id: str,
        attempt_id: str,
    ) -> LongTermMemoryReplayScheduleResult:
        return await self._schedule(
            learner_goal_id=learner_goal_id,
            idempotency_key=f"ltm-replay:task_outcome:{task_id}:{attempt_id}",
            payload={
                "source_type": "task_outcome",
                "task_id": task_id,
                "attempt_id": attempt_id,
            },
        )

    async def schedule_reflection_outcome(
        self,
        *,
        learner_goal_id: str,
        reflection_id: str,
        evaluation_id: str,
    ) -> LongTermMemoryReplayScheduleResult:
        return await self._schedule(
            learner_goal_id=learner_goal_id,
            idempotency_key=f"ltm-replay:reflection_outcome:{reflection_id}:{evaluation_id}",
            payload={
                "source_type": "reflection_outcome",
                "reflection_id": reflection_id,
                "evaluation_id": evaluation_id,
            },
        )

    async def schedule_quiz_answer_attempt(
        self,
        *,
        learner_goal_id: str | None,
        attempt_id: str,
    ) -> LongTermMemoryReplayScheduleResult:
        idempotency_key = f"ltm-replay:quiz_answer_attempt:{attempt_id}"
        if learner_goal_id is None:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=idempotency_key,
                due_at=None,
                skip_reason="missing_learner_goal_id",
            )
        return await self._schedule(
            learner_goal_id=learner_goal_id,
            idempotency_key=idempotency_key,
            payload={
                "source_type": "quiz_answer_attempt",
                "attempt_id": attempt_id,
            },
        )

    async def _schedule(
        self,
        *,
        learner_goal_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> LongTermMemoryReplayScheduleResult:
        due_at = datetime.now(timezone.utc) + INITIAL_REPLAY_DELAY
        if self._autonomy_job_service is None:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=idempotency_key,
                due_at=due_at,
                skip_reason="autonomy_job_service_unconfigured",
            )
        job = await self._autonomy_job_service.create_job(
            learner_goal_id=learner_goal_id,
            job_type=LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE,
            trigger_source=LONG_TERM_MEMORY_REPLAY_TRIGGER_SOURCE,
            due_at=due_at,
            idempotency_key=idempotency_key,
            payload=payload,
        )
        if job is None:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=idempotency_key,
                due_at=due_at,
                skip_reason="autonomy_job_repository_unconfigured",
            )
        return LongTermMemoryReplayScheduleResult(
            enqueued=True,
            job_id=job.id,
            idempotency_key=idempotency_key,
            due_at=job.due_at,
        )


class LongTermMemoryMaterializationReplayExecutor:
    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        message_repository: SessionMessageRepository,
        memory_event_repository: MemoryEventRepository,
        goal_repository: LearnerGoalRepository,
        daily_task_repository: DailyTaskRepository,
        task_attempt_repository: TaskAttemptRepository,
        reflection_record_repository: ReflectionRecordRepository,
        reflection_outcome_evaluation_repository: ReflectionOutcomeEvaluationRepository,
        materialization_service: LongTermMemoryMaterializationService,
        audit_service: AuditService,
        quiz_answer_attempt_repository: SessionQuizAnswerAttemptRepository | None = None,
    ) -> None:
        self._session_repository = session_repository
        self._message_repository = message_repository
        self._memory_event_repository = memory_event_repository
        self._goal_repository = goal_repository
        self._daily_task_repository = daily_task_repository
        self._task_attempt_repository = task_attempt_repository
        self._reflection_record_repository = reflection_record_repository
        self._reflection_outcome_evaluation_repository = reflection_outcome_evaluation_repository
        self._materialization_service = materialization_service
        self._audit_service = audit_service
        self._quiz_answer_attempt_repository = quiz_answer_attempt_repository

    async def replay(self, job: ScheduledAutonomyJob) -> None:
        source_type = str(job.payload.get("source_type") or "")
        if source_type not in LONG_TERM_MEMORY_REPLAY_SOURCE_TYPES:
            raise ValidationError("Unsupported long-term memory materialization replay source type.")
        if source_type == "chat_turn":
            result = await self._replay_chat_turn(job)
        elif source_type == "task_outcome":
            result = await self._replay_task_outcome(job)
        elif source_type == "quiz_answer_attempt":
            result = await self._replay_quiz_answer_attempt(job)
        else:
            result = await self._replay_reflection_outcome(job)
        await self._audit_service.record(
            event_type="long_term_memory.materialization.replayed",
            resource_type="autonomy_job",
            resource_id=job.id,
            actor="system",
            event_data={
                "autonomy_job_id": job.id,
                "learner_goal_id": job.learner_goal_id,
                "source_type": source_type,
                "payload": dict(job.payload),
                "knowledge_result_count": len(result.knowledge),
                "behavior_result_count": len(result.behavior),
                "skipped_reason": result.skipped_reason,
            },
        )

    async def _replay_chat_turn(self, job: ScheduledAutonomyJob) -> LongTermMemoryMaterializationResult:
        session_id = str(job.payload.get("session_id") or "")
        user_message_id = str(job.payload.get("user_message_id") or "")
        assistant_message_id = str(job.payload.get("assistant_message_id") or "")
        if not session_id or not user_message_id or not assistant_message_id:
            raise ValidationError("Missing chat turn identifiers for long-term memory materialization replay.")

        session = await self._session_repository.get_by_id(session_id)
        user_message = await self._message_repository.get_by_id(user_message_id)
        assistant_message = await self._message_repository.get_by_id(assistant_message_id)
        if session is None or user_message is None or assistant_message is None:
            raise ValidationError("Missing chat turn source records for long-term memory materialization replay.")
        if user_message.session_id != session.id or assistant_message.session_id != session.id:
            raise ValidationError("Chat turn replay source messages do not belong to the requested session.")
        if user_message.role != "user" or assistant_message.role != "assistant":
            raise ValidationError("Chat turn replay source message roles are invalid.")
        if session.learner_goal_id != job.learner_goal_id:
            raise ValidationError("Chat turn replay job goal does not match the source session.")

        memory_events = await self._memory_event_repository.list_by_session(session.id, limit=50)
        turn_events = [item for item in memory_events if item.source_message_id == user_message.id]
        return await self._materialization_service.materialize_from_chat_turn(
            session_id=session.id,
            learner_profile_id=session.learner_profile_id,
            learner_goal_id=session.learner_goal_id,
            learner_message=user_message.content,
            assistant_message=assistant_message.content,
            source_message_id=user_message.id,
            mode=user_message.mode or assistant_message.mode,
            subject=session.subject,
            session_title=session.title,
            memory_events=turn_events,
            persist_embeddings=True,
        )

    async def _replay_task_outcome(self, job: ScheduledAutonomyJob) -> LongTermMemoryMaterializationResult:
        task_id = str(job.payload.get("task_id") or "")
        attempt_id = str(job.payload.get("attempt_id") or "")
        if not task_id or not attempt_id:
            raise ValidationError("Missing task outcome identifiers for long-term memory materialization replay.")

        task = await self._daily_task_repository.get_by_id(task_id)
        attempt = await self._task_attempt_repository.get_by_id(attempt_id)
        if task is None or attempt is None:
            raise ValidationError("Missing task outcome source records for long-term memory materialization replay.")
        if attempt.daily_task_id != task.id or task.learner_goal_id != job.learner_goal_id:
            raise ValidationError("Task outcome replay job does not match the source records.")

        goal = await self._goal_repository.get_by_id(task.learner_goal_id)
        if goal is None:
            raise ValidationError("Missing learner goal for long-term memory materialization replay.")
        return await self._materialization_service.materialize_from_task_outcome(
            learner_profile_id=goal.learner_profile_id,
            task=task,
            attempt=attempt,
            persist_embeddings=True,
        )

    async def _replay_reflection_outcome(self, job: ScheduledAutonomyJob) -> LongTermMemoryMaterializationResult:
        reflection_id = str(job.payload.get("reflection_id") or "")
        evaluation_id = str(job.payload.get("evaluation_id") or "")
        if not reflection_id or not evaluation_id:
            raise ValidationError("Missing reflection outcome identifiers for long-term memory materialization replay.")

        reflection = await self._reflection_record_repository.get_by_id(reflection_id)
        evaluation = await self._reflection_outcome_evaluation_repository.get_by_id(evaluation_id)
        if reflection is None or evaluation is None:
            raise ValidationError("Missing reflection outcome source records for long-term memory materialization replay.")
        if evaluation.reflection_record_id != reflection.id or reflection.learner_goal_id != job.learner_goal_id:
            raise ValidationError("Reflection outcome replay job does not match the source records.")
        return await self._materialization_service.materialize_from_reflection_outcome(
            reflection=reflection,
            evaluation=evaluation,
            persist_embeddings=True,
        )

    async def _replay_quiz_answer_attempt(self, job: ScheduledAutonomyJob) -> LongTermMemoryMaterializationResult:
        attempt_id = str(job.payload.get("attempt_id") or "")
        if not attempt_id:
            raise ValidationError("Missing attempt_id for quiz answer attempt long-term memory materialization replay.")
        if self._quiz_answer_attempt_repository is None:
            raise ValidationError("SessionQuizAnswerAttemptRepository is unconfigured for replay.")
        attempt = await self._quiz_answer_attempt_repository.get_by_id(attempt_id)
        if attempt is None:
            raise ValidationError("Missing quiz answer attempt source record for long-term memory materialization replay.")
        if attempt.learner_goal_id != job.learner_goal_id:
            raise ValidationError("Quiz answer attempt replay job goal does not match the source records.")
        return await self._materialization_service.materialize_from_answer_attempt(
            attempt=attempt,
            persist_embeddings=True,
        )
