"""Task autonomy state coordinator.

Centralises post-plan and post-event autonomy state synchronisation,
daily materialization job scheduling, and periodic goal reflection
scheduling.  Replaces the ``GoalStateSyncCallback`` that was previously
threaded through ``TaskPlanLifecycleService`` and
``AutonomousTaskService``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.entities.autonomy import (
    GoalAutonomyState,
    LearnerAvailability,
    ScheduledAutonomyJob,
    _UNSET,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.infrastructure.db.repositories import (
    GoalAutonomyStateRepository,
    LearnerAvailabilityRepository,
    LearnerGoalRepository,
    LearnerTopicMasteryRepository,
    ScheduledAutonomyJobRepository,
)

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.application.services.audit import AuditService
    from agent_core.application.services.autonomy_jobs import AutonomyJobService


class TaskAutonomyStateCoordinator:
    """Coordinate autonomy state transitions and scheduled-job bookkeeping."""

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None = None,
        learner_availability_repository: LearnerAvailabilityRepository | None = None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
        autonomy_job_repository: ScheduledAutonomyJobRepository | None = None,
        autonomy_job_service: AutonomyJobService | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._learner_availability_repository = learner_availability_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._autonomy_job_repository = autonomy_job_repository
        self._autonomy_job_service = autonomy_job_service
        self._audit_service = audit_service

    async def sync_after_plan_generation(
        self,
        *,
        goal_id: str,
        plan_id: str,
        trigger_source: str,
    ) -> None:
        await self.sync_goal_state(goal_id, phase="active", current_plan_id=plan_id, reason=trigger_source)
        await self.ensure_daily_materialization_job(goal_id, trigger_source=trigger_source)
        await self.schedule_periodic_goal_reflection_job(goal_id, trigger_source=trigger_source)

    async def sync_goal_state(
        self,
        goal_id: str,
        *,
        phase: str | None = None,
        current_plan_id: str | None | object = _UNSET,
        next_due_at: datetime | None | object = _UNSET,
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
                mastery_snapshot=await self.build_mastery_snapshot(goal_id),
                reason=reason,
            )
        )

    async def ensure_daily_materialization_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
        days_offset: int = 0,
    ) -> ScheduledAutonomyJob | None:
        if self._autonomy_job_repository is None:
            return None
        availability = await self._get_goal_availability(learner_goal_id)
        timezone_name = self.validate_timezone(availability.timezone if availability is not None else None) or "UTC"
        zone = ZoneInfo(timezone_name)
        now_local = datetime.now(zone)
        target_day = now_local.date() + timedelta(days=days_offset)
        idempotency_key = f"{learner_goal_id}:daily_task_materialization:{target_day.isoformat()}:{timezone_name}"
        existing = await self._autonomy_job_repository.list_active_by_goal(
            learner_goal_id, job_types={"daily_task_materialization"},
        )
        for job in existing:
            if job.idempotency_key == idempotency_key:
                return job
        for job in existing:
            cancelled = job.cancel(error_code="rescheduled")
            await self._autonomy_job_repository.update(cancelled)
            if self._audit_service is not None:
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
        due_at, scheduled_local_time = self.compute_materialization_due_at(
            availability=availability, timezone_name=timezone_name, target_day=target_day,
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

    async def schedule_periodic_goal_reflection_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
    ) -> ScheduledAutonomyJob | None:
        if self._autonomy_job_repository is None:
            return None
        existing = await self._autonomy_job_repository.list_active_by_goal(
            learner_goal_id, job_types={"goal_reflection_periodic"},
        )
        if existing:
            return existing[0]
        due_at = datetime.now(timezone.utc) + timedelta(days=2)
        return await self._schedule_autonomy_job(
            learner_goal_id=learner_goal_id,
            job_type="goal_reflection_periodic",
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=f"{learner_goal_id}:goal_reflection_periodic:{due_at.date().isoformat()}",
            payload={"cooldown_days": 2},
        )

    async def build_mastery_snapshot(self, goal_id: str) -> dict[str, Any]:
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

    async def _get_goal_availability(self, goal_id: str) -> LearnerAvailability | None:
        if self._learner_availability_repository is None:
            return None
        return await self._learner_availability_repository.get_by_goal(goal_id)

    async def _schedule_autonomy_job(
        self,
        *,
        learner_goal_id: str,
        job_type: str,
        trigger_source: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
    ) -> ScheduledAutonomyJob | None:
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
            if self._audit_service is not None:
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

    @staticmethod
    def validate_timezone(value: str | None) -> str | None:
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
    def compute_materialization_due_at(
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
                        hour=hour, minute=minute,
                    ) - timedelta(minutes=30)
                    scheduled_local_time = f"{hour:02d}:{minute:02d}"
                    break
        now_local = datetime.now(zone)
        if target_day == now_local.date() and local_due < now_local:
            local_due = now_local
        return local_due.astimezone(timezone.utc), scheduled_local_time

    @staticmethod
    def to_datetime(value: date) -> datetime:
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)

    async def require_goal(self, goal_id: str):
        goal = await self._goal_repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        return goal

    async def schedule_autonomy_job(
        self,
        *,
        learner_goal_id: str,
        job_type: str,
        trigger_source: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
    ) -> ScheduledAutonomyJob | None:
        return await self._schedule_autonomy_job(
            learner_goal_id=learner_goal_id,
            job_type=job_type,
            trigger_source=trigger_source,
            due_at=due_at,
            idempotency_key=idempotency_key,
            payload=payload,
        )

    async def get_goal_availability_entity(self, goal_id: str) -> LearnerAvailability | None:
        if self._learner_availability_repository is None:
            return None
        return await self._learner_availability_repository.get_by_goal(goal_id)

    async def refresh_goal_mastery_snapshot(self, goal_id: str) -> None:
        if self._goal_autonomy_state_repository is None:
            return
        snapshot = await self.build_mastery_snapshot(goal_id)
        state = await self._goal_autonomy_state_repository.get_by_goal(goal_id)
        if state is None:
            return
        await self._goal_autonomy_state_repository.update(
            state.with_transition(mastery_snapshot=snapshot, reason=state.last_transition_reason)
        )

    async def ensure_milestone_jobs(self, learner_goal_id: str, study_plan_id: str, *, plan_stage_repository: Any, daily_task_repository: Any, audit_service: Any | None = None) -> None:
        if self._autonomy_job_repository is None:
            return
        from math import ceil

        stages = await plan_stage_repository.list_by_plan(study_plan_id)
        tasks = await daily_task_repository.list_by_goal(learner_goal_id)
        for stage in stages:
            stage_tasks = [
                task for task in tasks
                if task.plan_stage_id == stage.id and task.task_type in {"lesson", "practice", "repair"}
            ]
            if not stage_tasks:
                continue
            completed_count = len([task for task in stage_tasks if task.status == "completed"])
            if completed_count < max(1, ceil(len(stage_tasks) / 2)) and date.today() < stage.end_date:
                continue
            if any(task.task_type == "milestone" and task.plan_stage_id == stage.id and task.status != "superseded" for task in tasks):
                continue
            existing_attempts = len([task for task in tasks if task.task_type == "milestone" and task.plan_stage_id == stage.id])
            due_day = date.today() if completed_count >= max(1, ceil(len(stage_tasks) / 2)) else max(date.today(), stage.end_date)
            await self._schedule_autonomy_job(
                learner_goal_id=learner_goal_id,
                job_type="milestone_generation",
                trigger_source="stage_progress",
                due_at=datetime.combine(due_day, datetime.min.time(), tzinfo=timezone.utc),
                idempotency_key=f"{learner_goal_id}:milestone:{stage.id}:attempt:{existing_attempts + 1}",
                payload={"stage_id": stage.id, "attempt_index": existing_attempts + 1},
            )

    async def schedule_outcome_evaluation_job(
        self,
        learner_goal_id: str,
        *,
        trigger_source: str,
    ) -> ScheduledAutonomyJob | None:
        if self._autonomy_job_repository is None:
            return None
        existing = await self._autonomy_job_repository.list_active_by_goal(
            learner_goal_id, job_types={"reflection_outcome_evaluation"},
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
