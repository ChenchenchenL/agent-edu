"""Shared support for task status update side effects.

This service isolates attempt recording, mastery updates, and post-update
coordination from the legacy AutonomousTaskService so newer task lifecycle
services can reuse the same behavior without depending on core private helpers.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayScheduler,
    LongTermMemoryReplayScheduleResult,
)
from agent_core.application.services.reflection import ReflectionService, ReflectionTriggerRequest
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection_outcomes import ReflectionOutcomeService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.domain.entities.autonomy import (
    GoalAutonomyState,
    LearnerAvailability,
    LearnerTopicMastery,
    ScheduledAutonomyJob,
    TaskAttempt,
)
from agent_core.domain.entities.autonomy import _UNSET as AUTONOMY_UNSET
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.planning import DailyTask
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    GoalAutonomyStateRepository,
    LearnerAvailabilityRepository,
    LearnerGoalRepository,
    LearnerTopicMasteryRepository,
    ScheduledAutonomyJobRepository,
    TaskAttemptRepository,
)
from agent_core.infrastructure.observability.metrics import observe_long_term_memory_materialization

ShouldScheduleAssessment = Callable[[DailyTask], Awaitable[bool]]
DeriveReplanMode = Callable[[DailyTask], Awaitable[str]]
InlineStatusFollowupHandler = Callable[[DailyTask], Awaitable[None]]


class TaskStatusUpdateSupportService:
    """Support task status updates with shared persistence and side effects."""

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        daily_task_repository: DailyTaskRepository,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None,
        autonomy_job_repository: ScheduledAutonomyJobRepository | None,
        learner_availability_repository: LearnerAvailabilityRepository | None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None,
        task_attempt_repository: TaskAttemptRepository | None,
        autonomy_job_service: AutonomyJobService | None,
        reflection_service: ReflectionService | None,
        reflection_evidence_service: ReflectionEvidenceService | None,
        reflection_outcome_service: ReflectionOutcomeService | None,
        rollout_observation_scheduler: ReflectionProposalRolloutObservationScheduler | None,
        long_term_memory_materialization_service: LongTermMemoryMaterializationService | None,
        audit_service: AuditService,
        should_schedule_assessment: ShouldScheduleAssessment | None = None,
        derive_replan_mode: DeriveReplanMode | None = None,
        inline_status_followup_handler: InlineStatusFollowupHandler | None = None,
    ) -> None:
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._daily_task_repository = daily_task_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._autonomy_job_repository = autonomy_job_repository
        self._learner_availability_repository = learner_availability_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._task_attempt_repository = task_attempt_repository
        self._autonomy_job_service = autonomy_job_service
        self._reflection_service = reflection_service
        self._reflection_evidence_service = reflection_evidence_service
        self._reflection_outcome_service = reflection_outcome_service
        self._rollout_observation_scheduler = rollout_observation_scheduler
        self._long_term_memory_materialization_service = long_term_memory_materialization_service
        self._long_term_memory_replay_scheduler = LongTermMemoryMaterializationReplayScheduler(
            autonomy_job_service=autonomy_job_service,
        )
        self._audit_service = audit_service
        self._should_schedule_assessment = should_schedule_assessment
        self._derive_replan_mode = derive_replan_mode
        self._inline_status_followup_handler = inline_status_followup_handler

    async def record_attempt_and_update_mastery(self, task: DailyTask) -> TaskAttempt | None:
        """Persist the attempt record and update topic mastery."""
        attempt = await self.record_task_attempt(task)
        await self.update_topic_mastery(task)
        return attempt

    async def record_task_attempt(self, task: DailyTask) -> TaskAttempt | None:
        """Persist a task attempt if attempt storage is configured."""
        if self._task_attempt_repository is None:
            return None
        attempt = TaskAttempt.build(
            learner_goal_id=task.learner_goal_id,
            daily_task_id=task.id,
            workflow_run_id=task.last_workflow_run_id,
            execution_session_id=task.execution_session_id,
            task_type=task.task_type,
            topic_focus=task.topic_focus,
            outcome_status=task.status,
            score=self._attempt_score(task.status),
            result_note=task.result_note,
        )
        await self._task_attempt_repository.create(attempt)
        return attempt

    async def update_topic_mastery(self, task: DailyTask) -> None:
        """Update mastery aggregates from a task outcome."""
        if self._learner_topic_mastery_repository is None:
            return
        current = await self._learner_topic_mastery_repository.get_by_goal_and_topic(
            task.learner_goal_id,
            task.topic_focus,
        )
        mastery = current or LearnerTopicMastery.build(
            learner_goal_id=task.learner_goal_id,
            topic_key=task.topic_focus,
        )
        updated = mastery.update_from_attempt(outcome_status=task.status, task_type=task.task_type)
        await self._learner_topic_mastery_repository.upsert(updated)
        await self.refresh_goal_mastery_snapshot(task.learner_goal_id)

    async def refresh_goal_mastery_snapshot(self, goal_id: str) -> None:
        """Refresh the denormalized mastery snapshot on goal autonomy state."""
        if self._goal_autonomy_state_repository is None:
            return
        snapshot = await self._build_mastery_snapshot(goal_id)
        state = await self._goal_autonomy_state_repository.get_by_goal(goal_id)
        if state is None:
            return
        await self._goal_autonomy_state_repository.update(
            state.with_transition(
                mastery_snapshot=snapshot,
                reason=state.last_transition_reason,
            )
        )

    async def coordinate_post_update(
        self,
        task: DailyTask,
        attempt: TaskAttempt | None,
    ) -> None:
        """Run post-write side effects for a task status update."""
        inline_followups = self._autonomy_job_repository is None
        if self._long_term_memory_materialization_service is not None and attempt is not None:
            goal = await self._require_goal(task.learner_goal_id)
            await self._materialize_task_outcome_isolated(
                learner_profile_id=goal.learner_profile_id,
                task=task,
                attempt=attempt,
            )
        await self._derive_task_evidence(task, attempt=attempt)
        if self._reflection_service is not None:
            await self._trigger_post_task_reflection(task)
            await self._evaluate_recent_reflection_outcomes(task)
            goal = await self._require_goal(task.learner_goal_id)
            await self._reflection_service.evaluate_and_trigger_proactive_reflections(
                learner_profile_id=goal.learner_profile_id,
                learner_goal_id=goal.id,
                task=task,
            )
        await self._enqueue_autonomy_followups(task)
        if self._rollout_observation_scheduler is not None:
            await self._rollout_observation_scheduler.schedule_active(
                learner_goal_id=task.learner_goal_id,
                surface="plan_generation",
                trigger_source="task_status_updated",
                source_ref=task.id,
            )
        if inline_followups and self._inline_status_followup_handler is not None:
            await self._inline_status_followup_handler(task)

    async def _build_mastery_snapshot(self, goal_id: str) -> dict[str, object]:
        if self._learner_topic_mastery_repository is None:
            return {}
        masteries = await self._learner_topic_mastery_repository.list_by_goal(goal_id)
        return {
            "topics": [
                {
                    "topic_key": mastery.topic_key,
                    "mastery_score": mastery.mastery_score,
                    "confidence": mastery.confidence,
                    "evidence_count": mastery.evidence_count,
                }
                for mastery in masteries
            ]
        }

    async def _materialize_task_outcome_isolated(
        self,
        *,
        learner_profile_id: str,
        task: DailyTask,
        attempt: TaskAttempt,
    ) -> None:
        try:
            begin_nested = getattr(self._db_session, "begin_nested", None)
            if begin_nested is None:
                await self._long_term_memory_materialization_service.materialize_from_task_outcome(
                    learner_profile_id=learner_profile_id,
                    task=task,
                    attempt=attempt,
                    persist_embeddings=True,
                )
            else:
                async with begin_nested():
                    await self._long_term_memory_materialization_service.materialize_from_task_outcome(
                        learner_profile_id=learner_profile_id,
                        task=task,
                        attempt=attempt,
                        persist_embeddings=True,
                    )
        except Exception as exc:
            observe_long_term_memory_materialization(
                source_type="task_outcome",
                status="failed",
                reason_code=type(exc).__name__,
            )
            replay = await self._schedule_task_materialization_replay(task=task, attempt=attempt)
            event_data = {
                "source_type": "task_outcome",
                "learner_profile_id": learner_profile_id,
                "learner_goal_id": task.learner_goal_id,
                "task_id": task.id,
                "attempt_id": attempt.id,
                "workflow_run_id": attempt.workflow_run_id,
                "session_id": attempt.execution_session_id,
                "outcome_status": attempt.outcome_status,
                "error_code": type(exc).__name__,
                "error": str(exc),
            }
            event_data.update(replay.audit_payload())
            await self._audit_service.record_durable(
                event_type="long_term_memory.materialization.failed",
                resource_type="daily_task",
                resource_id=task.id,
                actor="system",
                event_data=event_data,
            )

    async def _schedule_task_materialization_replay(
        self,
        *,
        task: DailyTask,
        attempt: TaskAttempt,
    ) -> LongTermMemoryReplayScheduleResult:
        try:
            return await self._long_term_memory_replay_scheduler.schedule_task_outcome(
                learner_goal_id=task.learner_goal_id,
                task_id=task.id,
                attempt_id=attempt.id,
            )
        except Exception as replay_exc:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=f"ltm-replay:task_outcome:{task.id}:{attempt.id}",
                due_at=None,
                skip_reason="replay_enqueue_failed",
                error_code=type(replay_exc).__name__,
                error=str(replay_exc),
            )

    async def _derive_task_evidence(self, task: DailyTask, *, attempt: TaskAttempt | None) -> None:
        if self._reflection_evidence_service is None:
            return
        goal = await self._require_goal(task.learner_goal_id)
        evidence_attempt = attempt
        if evidence_attempt is None and self._task_attempt_repository is not None:
            attempts = await self._task_attempt_repository.list_recent_by_goal(task.learner_goal_id, limit=3)
            evidence_attempt = next((item for item in attempts if item.daily_task_id == task.id), None)
        await self._reflection_evidence_service.derive_from_task(
            learner_profile_id=goal.learner_profile_id,
            learner_goal_id=goal.id,
            task=task,
            attempt=evidence_attempt,
        )

    async def _enqueue_autonomy_followups(self, task: DailyTask) -> None:
        if self._autonomy_job_repository is None:
            return
        now = datetime.now(timezone.utc)
        if task.status == "completed":
            if task.task_type == "milestone":
                await self._sync_goal_state(
                    task.learner_goal_id,
                    phase="active",
                    next_due_at=now,
                    reason="milestone_completed",
                )
                await self._ensure_daily_materialization_job(
                    task.learner_goal_id,
                    trigger_source="milestone_completed",
                )
                await self._schedule_outcome_evaluation_job(
                    task.learner_goal_id,
                    trigger_source="milestone_completed",
                )
                return
            await self._schedule_autonomy_job(
                learner_goal_id=task.learner_goal_id,
                job_type="review_scheduling",
                trigger_source="task_completed",
                due_at=now,
                idempotency_key=f"{task.id}:review_scheduling",
                payload={"source_task_id": task.id},
            )
            await self._schedule_autonomy_job(
                learner_goal_id=task.learner_goal_id,
                job_type="plan_extension",
                trigger_source="task_completed",
                due_at=now,
                idempotency_key=f"{task.id}:plan_extension",
                payload={"source_task_id": task.id},
            )
            await self._ensure_daily_materialization_job(
                task.learner_goal_id,
                trigger_source="task_completed",
            )
            if self._should_schedule_assessment is not None and await self._should_schedule_assessment(task):
                await self._schedule_autonomy_job(
                    learner_goal_id=task.learner_goal_id,
                    job_type="assessment_generation",
                    trigger_source="task_completed",
                    due_at=now,
                    idempotency_key=f"{task.id}:assessment_generation",
                    payload={"topic_focus": task.topic_focus, "source_task_id": task.id},
                )
            await self._schedule_outcome_evaluation_job(
                task.learner_goal_id,
                trigger_source="task_completed",
            )
            return
        if task.task_type == "milestone":
            await self._schedule_autonomy_job(
                learner_goal_id=task.learner_goal_id,
                job_type="replan",
                trigger_source="milestone_failed" if task.status == "failed" else "milestone_skipped",
                due_at=now,
                idempotency_key=f"{task.id}:replan:partial",
                payload={"mode": "partial", "source_task_id": task.id, "topic_focus": task.topic_focus},
            )
            await self._sync_goal_state(
                task.learner_goal_id,
                phase="assessment_due",
                next_due_at=now,
                reason=f"milestone_{task.status}",
            )
            await self._schedule_outcome_evaluation_job(
                task.learner_goal_id,
                trigger_source=f"milestone_{task.status}",
            )
            return
        mode = "full"
        if self._derive_replan_mode is not None:
            mode = await self._derive_replan_mode(task)
        await self._schedule_autonomy_job(
            learner_goal_id=task.learner_goal_id,
            job_type="replan",
            trigger_source="task_failed" if task.status == "failed" else "task_skipped",
            due_at=now,
            idempotency_key=f"{task.id}:replan:{mode}",
            payload={"mode": mode, "source_task_id": task.id, "topic_focus": task.topic_focus},
        )
        await self._sync_goal_state(
            task.learner_goal_id,
            phase="replanning",
            next_due_at=now,
            reason=f"task_{task.status}",
        )
        await self._schedule_outcome_evaluation_job(
            task.learner_goal_id,
            trigger_source=f"task_{task.status}",
        )

    async def _schedule_autonomy_job(
        self,
        *,
        learner_goal_id: str,
        job_type: str,
        trigger_source: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
    ):
        if self._autonomy_job_service is None:
            if self._autonomy_job_repository is None:
                return None
            job = await self._autonomy_job_repository.create(
                ScheduledAutonomyJob.build(
                    learner_goal_id=learner_goal_id,
                    job_type=job_type,
                    trigger_source=trigger_source,
                    due_at=due_at,
                    idempotency_key=idempotency_key,
                    payload=dict(payload or {}),
                )
            )
            await self._audit_service.record(
                event_type="autonomy.job.created",
                resource_type="autonomy_job",
                resource_id=job.id,
                actor="system",
                event_data={
                    "autonomy_job_id": job.id,
                    "learner_goal_id": learner_goal_id,
                    "job_type": job_type,
                    "trigger_source": trigger_source,
                    "due_at": due_at.isoformat(),
                    "idempotency_key": idempotency_key,
                },
            )
            return job
        return await self._autonomy_job_service.create_job(
            learner_goal_id=learner_goal_id,
            job_type=job_type,
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=idempotency_key,
            payload=dict(payload or {}),
        )

    async def _trigger_post_task_reflection(self, task: DailyTask) -> None:
        goal = await self._require_goal(task.learner_goal_id)
        trigger_source = None
        if task.status == "failed":
            trigger_source = "task_failed"
        elif task.status == "skipped":
            trigger_source = "task_skipped"
        elif task.status == "completed" and task.task_type == "assessment":
            trigger_source = "assessment_completed"

        if trigger_source is not None:
            await self._reflection_service.trigger_reflection(
                ReflectionTriggerRequest(
                    learner_profile_id=goal.learner_profile_id,
                    learner_goal_id=goal.id,
                    scope="task",
                    target_type="daily_task",
                    target_id=task.id,
                    trigger_source=trigger_source,
                    reflection_depth=1,
                    daily_task_id=task.id,
                    workflow_run_id=task.last_workflow_run_id,
                    study_plan_id=task.study_plan_id,
                    source_attempt_id=task.id,
                )
            )

    async def _has_consecutive_topic_failures(self, task: DailyTask) -> bool:
        if self._task_attempt_repository is None:
            return False
        attempts = await self._task_attempt_repository.list_recent_by_goal(task.learner_goal_id, limit=5)
        topic_attempts = [item for item in attempts if item.topic_focus == task.topic_focus][:3]
        return len([item for item in topic_attempts if item.outcome_status in {"failed", "skipped"}]) >= 2

    async def _evaluate_recent_reflection_outcomes(self, task: DailyTask) -> None:
        if self._reflection_service is None or self._reflection_outcome_service is None:
            return
        reflections = await self._reflection_service.list_task_reflections(task_id=task.id, limit=5, offset=0)
        for item in reflections.items:
            record = await self._reflection_service.get_record(item.id)
            topic_key = str((record.evidence_payload.get("task") or {}).get("topic_focus") or "") or None
            evaluation = await self._reflection_outcome_service.evaluate(
                reflection=record,
                topic_key=topic_key,
            )
            await self._reflection_service.apply_outcome_feedback(
                reflection=record,
                evaluation=evaluation,
            )

    async def _sync_goal_state(
        self,
        goal_id: str,
        *,
        phase: str | None = None,
        current_plan_id: str | None | object = AUTONOMY_UNSET,
        next_due_at: datetime | None | object = AUTONOMY_UNSET,
        reason: str | None = None,
    ) -> None:
        if self._goal_autonomy_state_repository is None:
            return
        state = await self._goal_autonomy_state_repository.get_by_goal(goal_id)
        if state is None:
            state = GoalAutonomyState.build(learner_goal_id=goal_id)
            await self._goal_autonomy_state_repository.create(state)
        await self._goal_autonomy_state_repository.update(
            state.with_transition(
                phase=phase,
                current_plan_id=current_plan_id,
                next_due_at=next_due_at,
                mastery_snapshot=await self._build_mastery_snapshot(goal_id),
                reason=reason,
            )
        )

    async def _ensure_daily_materialization_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
        days_offset: int = 0,
    ):
        if self._autonomy_job_repository is None:
            return None
        availability = await self._get_goal_availability_entity(learner_goal_id)
        timezone_name = self._validate_timezone(availability.timezone if availability is not None else None) or "UTC"
        zone = ZoneInfo(timezone_name)
        now_local = datetime.now(zone)
        target_day = now_local.date() + timedelta(days=days_offset)
        idempotency_key = f"{learner_goal_id}:daily_task_materialization:{target_day.isoformat()}:{timezone_name}"
        existing = await self._autonomy_job_repository.list_active_by_goal(
            learner_goal_id,
            job_types={"daily_task_materialization"},
        )
        for job in existing:
            if job.idempotency_key == idempotency_key:
                return job
        for job in existing:
            cancelled = job.cancel(error_code="rescheduled")
            await self._autonomy_job_repository.update(cancelled)
            await self._audit_service.record(
                event_type="autonomy.job.cancelled",
                resource_type="autonomy_job",
                resource_id=cancelled.id,
                actor="system",
                event_data={
                    "autonomy_job_id": cancelled.id,
                    "learner_goal_id": learner_goal_id,
                    "job_type": cancelled.job_type,
                    "reason": "rescheduled",
                },
            )
        due_at, scheduled_local_time = self._compute_materialization_due_at(
            availability=availability,
            timezone_name=timezone_name,
            target_day=target_day,
        )
        return await self._schedule_autonomy_job(
            learner_goal_id=learner_goal_id,
            job_type="daily_task_materialization",
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=idempotency_key,
            payload={
                "window_days": 3,
                "target_local_date": target_day.isoformat(),
                "target_timezone": timezone_name,
                "scheduled_local_time": scheduled_local_time,
            },
        )

    async def _get_goal_availability_entity(self, goal_id: str) -> LearnerAvailability | None:
        if self._learner_availability_repository is None:
            return None
        return await self._learner_availability_repository.get_by_goal(goal_id)

    def _compute_materialization_due_at(
        self,
        *,
        availability: LearnerAvailability | None,
        timezone_name: str,
        target_day: date,
    ) -> tuple[datetime, str]:
        zone = ZoneInfo(timezone_name)
        local_due = datetime.combine(target_day, datetime.min.time(), tzinfo=zone).replace(hour=0, minute=5)
        scheduled_local_time = "00:05"
        if availability is not None:
            for item in availability.time_windows:
                start = str(item.get("start") or "").strip()
                if len(start) == 5 and start[2] == ":":
                    hour = int(start[:2])
                    minute = int(start[3:])
                    local_due = datetime.combine(target_day, datetime.min.time(), tzinfo=zone).replace(
                        hour=hour,
                        minute=minute,
                    ) - timedelta(minutes=30)
                    scheduled_local_time = f"{hour:02d}:{minute:02d}"
                    break
        now_local = datetime.now(zone)
        if target_day == now_local.date() and local_due < now_local:
            local_due = now_local
        return local_due.astimezone(timezone.utc), scheduled_local_time

    async def _schedule_outcome_evaluation_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
    ):
        if self._autonomy_job_repository is None:
            return None
        existing = await self._autonomy_job_repository.list_active_by_goal(
            learner_goal_id,
            job_types={"reflection_outcome_evaluation"},
        )
        if existing:
            return existing[0]
        due_at = datetime.now(timezone.utc)
        return await self._schedule_autonomy_job(
            learner_goal_id=learner_goal_id,
            job_type="reflection_outcome_evaluation",
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=f"{learner_goal_id}:reflection_outcome_evaluation:{due_at.isoformat()}",
            payload={},
        )

    async def _require_goal(self, goal_id: str) -> LearnerGoal:
        goal = await self._goal_repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        return goal

    @staticmethod
    def _validate_timezone(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            ZoneInfo(normalized)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError("Unsupported learner timezone.") from exc
        return normalized

    @staticmethod
    def _attempt_score(status: str) -> float:
        if status == "completed":
            return 1.0
        if status == "skipped":
            return 0.4
        if status == "failed":
            return 0.0
        return 0.5
