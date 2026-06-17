from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from typing import TYPE_CHECKING, Awaitable, Callable, Any

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.entities.autonomy import LearnerAvailability, ScheduledAutonomyJob, AUTONOMY_REPLAN_MODES
from agent_core.domain.schemas.autonomy import (
    GoalAutonomyStateResponse,
    LearnerAvailabilityResponse,
    LearnerTopicMasteryResponse,
    ManualReplanRequest,
    UpdateLearnerAvailabilityRequest,
)
from agent_core.infrastructure.db.repositories import (
    GoalAutonomyStateRepository,
    LearnerAvailabilityRepository,
    LearnerGoalRepository,
    LearnerTopicMasteryRepository,
    ScheduledAutonomyJobRepository,
)
from agent_core.application.services.long_term_memory_materialization_replay import (
    LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE,
    long_term_memory_replay_backoff,
)

if TYPE_CHECKING:
    from agent_core.application.services.audit import AuditService
    from agent_core.application.services.autonomy_jobs import AutonomyJobService
    from agent_core.application.services.autonomy_jobs.dispatcher import AutonomyJobDispatcherService


# Callback types for complex coordination
SyncGoalStateCallback = Callable[[str, str | None, str | None, datetime | None], Awaitable[None]]
EnsureMaterializationJobCallback = Callable[[str, str], Awaitable[None]]
ValidateTimezoneCallback = Callable[[str | None], str | None]
TriggerReflectionCallback = Callable[[str, str], Awaitable[None]]
ProcessAutonomyJobCallback = Callable[[ScheduledAutonomyJob], Awaitable[str | None]]


class TaskAutonomySchedulingService:
    """Manage autonomy state and scheduling operations.

    Responsibilities:
    - Autonomy state queries (read-only)
    - Learner availability CRUD operations
    - Topic mastery queries (read-only)
    - Autonomy control operations (pause/resume)
    - Autonomy jobs listing
    - Autonomy scheduling operations (materialize_today, manual_replan,
      run_periodic_reflection, run_due_jobs) via callbacks.
    """

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None = None,
        learner_availability_repository: LearnerAvailabilityRepository | None = None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
        autonomy_job_repository: ScheduledAutonomyJobRepository | None = None,
        audit_service: AuditService | None = None,
        sync_goal_state_callback: SyncGoalStateCallback | None = None,
        ensure_materialization_job_callback: EnsureMaterializationJobCallback | None = None,
        validate_timezone_callback: ValidateTimezoneCallback | None = None,
        autonomy_job_service: AutonomyJobService | None = None,
        trigger_reflection_callback: TriggerReflectionCallback | None = None,
        process_autonomy_job_callback: ProcessAutonomyJobCallback | None = None,
        autonomy_job_dispatcher: AutonomyJobDispatcherService | None = None,
    ) -> None:
        """Initialize the scheduling service with real dependencies.

        Args:
            db_session: Database session for transaction management.
            goal_repository: Repository for learner goals.
            goal_autonomy_state_repository: Optional repository for autonomy state.
            learner_availability_repository: Optional repository for availability.
            learner_topic_mastery_repository: Optional repository for mastery.
            autonomy_job_repository: Optional repository for autonomy jobs.
            audit_service: Optional audit service for state changes.
            sync_goal_state_callback: Optional callback for goal state synchronization.
            ensure_materialization_job_callback: Optional callback for job scheduling.
            validate_timezone_callback: Optional callback for timezone validation.
            autonomy_job_service: Optional service for scheduling jobs.
            trigger_reflection_callback: Optional callback for triggering reflection.
            process_autonomy_job_callback: Optional callback for job processing.
            autonomy_job_dispatcher: Dispatcher for autonomy jobs.
        """
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._learner_availability_repository = learner_availability_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._autonomy_job_repository = autonomy_job_repository
        self._audit_service = audit_service
        self._sync_goal_state_callback = sync_goal_state_callback
        self._ensure_materialization_job_callback = ensure_materialization_job_callback
        self._validate_timezone_callback = validate_timezone_callback
        self._autonomy_job_service = autonomy_job_service
        self._trigger_reflection_callback = trigger_reflection_callback
        self._process_autonomy_job_callback = process_autonomy_job_callback
        self._autonomy_job_dispatcher = autonomy_job_dispatcher
        self._autonomy_jobs_running = False

    async def get_goal_autonomy_state(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Get the autonomy state for a goal.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            Autonomy state response.

        Raises:
            NotFoundError: If goal or autonomy state does not exist.
        """
        state = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(state)

    async def update_goal_availability(
        self,
        *,
        goal_id: str,
        payload: UpdateLearnerAvailabilityRequest,
    ) -> LearnerAvailabilityResponse:
        """Update learner availability for a goal.

        Args:
            goal_id: Learner goal identifier.
            payload: Availability update request.

        Returns:
            Updated availability response.

        Raises:
            ValidationError: If availability storage is not configured.
            NotFoundError: If goal does not exist.
        """
        if self._audit_service is None:
            raise RuntimeError("Standalone availability updates require an audit service.")
        if self._learner_availability_repository is None:
            raise ValidationError("Learner availability storage is not configured.")

        goal = await self._require_goal(goal_id)

        # Validate timezone
        validated_timezone = payload.timezone
        if self._validate_timezone_callback is not None:
            validated_timezone = self._validate_timezone_callback(payload.timezone) or payload.timezone

        # Build and persist availability
        availability = LearnerAvailability.build(
            learner_goal_id=goal.id,
            timezone=validated_timezone,
            available_days=payload.available_days,
            time_windows=payload.time_windows,
            max_daily_minutes=payload.max_daily_minutes,
            preferred_session_length_minutes=payload.preferred_session_length_minutes,
        )
        await self._learner_availability_repository.upsert(availability)

        # Audit
        await self._audit_service.record(
            event_type="learner_availability.updated",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="learner",
            event_data={
                "learner_goal_id": goal.id,
                "timezone": validated_timezone,
                "available_days": payload.available_days,
                "max_daily_minutes": payload.max_daily_minutes,
                "preferred_session_length_minutes": payload.preferred_session_length_minutes,
            },
        )

        # Coordinate: sync state and ensure materialization job
        if self._sync_goal_state_callback is not None:
            await self._sync_goal_state_callback(goal.id, None, "availability_updated")
        if self._ensure_materialization_job_callback is not None:
            await self._ensure_materialization_job_callback(goal.id, "availability_updated")

        await self._db_session.commit()

        # Refresh and return
        stored = await self._learner_availability_repository.get_by_goal(goal.id)
        if stored is None:
            raise NotFoundError(f"Learner availability for goal '{goal.id}' was not found.")
        return LearnerAvailabilityResponse.model_validate(stored)

    async def get_goal_availability(self, goal_id: str) -> LearnerAvailabilityResponse:
        """Fetch learner availability for a goal.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            Availability response.

        Raises:
            NotFoundError: If goal or availability does not exist.
        """
        await self._require_goal(goal_id)
        if self._learner_availability_repository is None:
            raise NotFoundError(f"Learner availability for goal '{goal_id}' was not found.")
        availability = await self._learner_availability_repository.get_by_goal(goal_id)
        if availability is None:
            raise NotFoundError(f"Learner availability for goal '{goal_id}' was not found.")
        return LearnerAvailabilityResponse.model_validate(availability)

    async def list_goal_mastery(self, goal_id: str) -> list[LearnerTopicMasteryResponse]:
        """List learner mastery snapshots for a goal.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            List of topic mastery responses (empty if mastery not configured).

        Raises:
            NotFoundError: If goal does not exist.
        """
        await self._require_goal(goal_id)
        if self._learner_topic_mastery_repository is None:
            return []
        masteries = await self._learner_topic_mastery_repository.list_by_goal(goal_id)
        return [LearnerTopicMasteryResponse.model_validate(item) for item in masteries]

    async def pause_goal_autonomy(self, goal_id: str, reason: str | None = None) -> GoalAutonomyStateResponse:
        """Pause autonomy for a goal.

        Args:
            goal_id: Learner goal identifier.
            reason: Optional reason for pausing.

        Returns:
            Updated autonomy state response.

        Raises:
            NotFoundError: If goal does not exist.
        """
        if self._audit_service is None:
            raise RuntimeError("Standalone autonomy control requires an audit service.")

        goal = await self._require_goal(goal_id)

        # Sync state to paused
        if self._sync_goal_state_callback is not None:
            await self._sync_goal_state_callback(goal_id, "paused", reason or "paused")

        # Audit
        await self._audit_service.record(
            event_type="autonomy.state.paused",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="learner",
            event_data={"learner_goal_id": goal.id, "reason": reason},
        )

        await self._db_session.commit()

        # Refresh and return
        refreshed = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def resume_goal_autonomy(self, goal_id: str, reason: str | None = None) -> GoalAutonomyStateResponse:
        """Resume autonomy for a goal.

        Args:
            goal_id: Learner goal identifier.
            reason: Optional reason for resuming.

        Returns:
            Updated autonomy state response.

        Raises:
            NotFoundError: If goal does not exist.
        """
        if self._audit_service is None:
            raise RuntimeError("Standalone autonomy control requires an audit service.")

        goal = await self._require_goal(goal_id)

        # Sync state to active
        if self._sync_goal_state_callback is not None:
            await self._sync_goal_state_callback(goal.id, "active", reason or "resumed")

        # Ensure materialization job
        if self._ensure_materialization_job_callback is not None:
            await self._ensure_materialization_job_callback(goal.id, "autonomy_resumed")

        # Audit
        await self._audit_service.record(
            event_type="autonomy.state.resumed",
            resource_type="learner_goal",
            resource_id=goal.id,
            actor="learner",
            event_data={"learner_goal_id": goal.id, "reason": reason},
        )

        await self._db_session.commit()

        # Refresh and return
        refreshed = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def list_autonomy_jobs(self, goal_id: str) -> list[ScheduledAutonomyJob]:
        """List autonomy jobs for a goal.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            List of scheduled autonomy jobs (empty if repository not configured).

        Raises:
            NotFoundError: If goal does not exist.
        """
        await self._require_goal(goal_id)
        if self._autonomy_job_repository is None:
            return []
        return await self._autonomy_job_repository.list_by_goal(goal_id)

    async def materialize_today(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Materialize today's work window for a goal."""
        await self._require_goal(goal_id)
        if self._learner_availability_repository is None:
            availability = None
        else:
            availability = await self._learner_availability_repository.get_by_goal(goal_id)

        timezone_name = None
        if self._validate_timezone_callback is not None:
            timezone_name = self._validate_timezone_callback(availability.timezone if availability is not None else None)
        if not timezone_name:
            timezone_name = "UTC"
        zone = ZoneInfo(timezone_name)
        target_day = datetime.now(zone).date()
        await self._schedule_autonomy_job(
            learner_goal_id=goal_id,
            job_type="daily_task_materialization",
            trigger_source="manual_materialize_today",
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"{goal_id}:manual_materialize_today:{datetime.now(timezone.utc).isoformat()}",
            payload={
                "window_days": 3,
                "target_local_date": target_day.isoformat(),
                "target_timezone": timezone_name,
                "scheduled_local_time": "manual",
            },
        )
        await self._db_session.commit()
        await self.run_due_autonomy_jobs(raise_on_error=True, lease_owner="manual-materialize")
        refreshed = await self._require_goal_autonomy_state(goal_id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def manual_replan_goal(
        self,
        goal_id: str,
        payload: ManualReplanRequest,
    ) -> GoalAutonomyStateResponse:
        """Manually request a replan for a goal."""
        goal = await self._require_goal(goal_id)
        if payload.mode not in AUTONOMY_REPLAN_MODES:
            raise ValidationError("Unsupported autonomy replan mode.")
        job = await self._schedule_autonomy_job(
            learner_goal_id=goal.id,
            job_type="replan",
            trigger_source=payload.trigger_source,
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"{goal.id}:manual_replan:{payload.mode}:{payload.source_task_id or 'latest'}",
            payload={
                "mode": payload.mode,
                "source_task_id": payload.source_task_id or "",
            },
        )
        if self._sync_goal_state_callback is not None:
            await self._sync_goal_state_callback(goal.id, "replanning", "manual_replan_requested", datetime.now(timezone.utc))
        if self._audit_service is not None:
            await self._audit_service.record(
                event_type="autonomy.replan.requested",
                resource_type="learner_goal",
                resource_id=goal.id,
                actor="learner",
                event_data={
                    "learner_goal_id": goal.id,
                    "trigger_source": payload.trigger_source,
                    "mode": payload.mode,
                    "source_task_id": payload.source_task_id,
                },
            )
        await self._db_session.commit()
        await self.run_due_autonomy_jobs(raise_on_error=True, lease_owner="manual-replan")
        refreshed = await self._require_goal_autonomy_state(goal.id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def run_periodic_goal_reflection(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Run periodic reflection for a goal."""
        goal = await self._require_goal(goal_id)
        if self._trigger_reflection_callback is not None:
            await self._trigger_reflection_callback(goal.learner_profile_id, goal.id)
        if self._sync_goal_state_callback is not None:
            await self._sync_goal_state_callback(goal.id, "active", "periodic_goal_reflection", None)
        await self._db_session.commit()
        refreshed = await self._require_goal_autonomy_state(goal.id)
        return GoalAutonomyStateResponse.model_validate(refreshed)

    async def run_due_autonomy_jobs(
        self,
        *,
        raise_on_error: bool = True,
        lease_owner: str = "inline",
        limit: int = 20,
    ) -> int:
        """Run due autonomy jobs."""
        if self._autonomy_job_repository is None:
            return 0
        if self._autonomy_jobs_running:
            return 0
        self._autonomy_jobs_running = True
        try:
            processed = 0
            while processed < limit:
                due_jobs = await self._autonomy_job_repository.list_due(
                    now=datetime.now(timezone.utc),
                    limit=limit - processed,
                )
                if not due_jobs:
                    break
                for job in due_jobs:
                    claimed = await self._autonomy_job_repository.claim(job, lease_owner=lease_owner, lease_seconds=300)
                    if self._audit_service is not None:
                        await self._audit_service.record(
                            event_type="autonomy.job.claimed",
                            resource_type="autonomy_job",
                            resource_id=claimed.id,
                            actor="system",
                            event_data={
                                "autonomy_job_id": claimed.id,
                                "learner_goal_id": claimed.learner_goal_id,
                                "job_type": claimed.job_type,
                                "trigger_source": claimed.trigger_source,
                                "attempt_count": claimed.attempt_count,
                            },
                        )
                    await self._db_session.commit()
                    try:
                        workflow_run_id = None
                        if self._autonomy_job_dispatcher is not None and claimed.job_type in self._autonomy_job_dispatcher._handlers:
                            workflow_run_id = await self._autonomy_job_dispatcher.dispatch(claimed)
                        elif self._process_autonomy_job_callback is not None:
                            workflow_run_id = await self._process_autonomy_job_callback(claimed)
                        completed = claimed.complete(workflow_run_id=workflow_run_id)
                        await self._autonomy_job_repository.update(completed)
                        if self._audit_service is not None:
                            await self._audit_service.record(
                                event_type="autonomy.job.completed",
                                resource_type="autonomy_job",
                                resource_id=completed.id,
                                actor="system",
                                event_data={
                                    "autonomy_job_id": completed.id,
                                    "learner_goal_id": completed.learner_goal_id,
                                    "job_type": completed.job_type,
                                    "workflow_run_id": workflow_run_id,
                                },
                            )
                        await self._db_session.commit()
                        processed += 1
                    except Exception as exc:
                        if claimed.job_type == LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE and claimed.attempt_count < claimed.max_attempts:
                            retry_due_at = datetime.now(timezone.utc) + long_term_memory_replay_backoff(claimed.attempt_count)
                            retry = claimed.retry(due_at=retry_due_at)
                            await self._autonomy_job_repository.update(retry)
                            if self._audit_service is not None:
                                await self._audit_service.record_durable(
                                    event_type="long_term_memory.materialization.replay_retry_scheduled",
                                    resource_type="autonomy_job",
                                    resource_id=retry.id,
                                    actor="system",
                                    event_data={
                                        "autonomy_job_id": retry.id,
                                        "learner_goal_id": retry.learner_goal_id,
                                        "job_type": retry.job_type,
                                        "attempt_count": retry.attempt_count,
                                        "max_attempts": retry.max_attempts,
                                        "retry_due_at": retry.due_at.isoformat(),
                                        "error_code": type(exc).__name__,
                                        "error": str(exc),
                                    },
                                )
                            await self._db_session.commit()
                            processed += 1
                            continue
                        failed = claimed.fail(error_code=type(exc).__name__)
                        await self._autonomy_job_repository.update(failed)
                        if self._audit_service is not None:
                            if claimed.job_type == LONG_TERM_MEMORY_MATERIALIZATION_REPLAY_JOB_TYPE:
                                await self._audit_service.record_durable(
                                    event_type="long_term_memory.materialization.replay_exhausted",
                                    resource_type="autonomy_job",
                                    resource_id=failed.id,
                                    actor="system",
                                    event_data={
                                        "autonomy_job_id": failed.id,
                                        "learner_goal_id": failed.learner_goal_id,
                                        "job_type": failed.job_type,
                                        "attempt_count": failed.attempt_count,
                                        "max_attempts": failed.max_attempts,
                                        "error_code": type(exc).__name__,
                                        "error": str(exc),
                                    },
                                )
                            await self._audit_service.record_durable(
                                event_type="autonomy.job.failed",
                                resource_type="autonomy_job",
                                resource_id=failed.id,
                                actor="system",
                                event_data={
                                    "autonomy_job_id": failed.id,
                                    "learner_goal_id": failed.learner_goal_id,
                                    "job_type": failed.job_type,
                                    "error_code": type(exc).__name__,
                                    "error": str(exc),
                                },
                            )
                        await self._db_session.commit()
                        if raise_on_error:
                            raise
            return processed
        finally:
            self._autonomy_jobs_running = False

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

    # Private helper methods

    async def _require_goal(self, goal_id: str):
        """Require goal to exist, raising NotFoundError otherwise.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            The learner goal entity.

        Raises:
            NotFoundError: If goal does not exist.
        """
        goal = await self._goal_repository.get_by_id(goal_id)
        if goal is None:
            raise NotFoundError(f"Learner goal '{goal_id}' was not found.")
        return goal

    async def _require_goal_autonomy_state(self, goal_id: str):
        """Require autonomy state to exist, raising NotFoundError otherwise.

        Args:
            goal_id: Learner goal identifier.

        Returns:
            The autonomy state entity.

        Raises:
            NotFoundError: If autonomy state does not exist.
        """
        if self._goal_autonomy_state_repository is None:
            raise NotFoundError(f"Autonomy state for goal '{goal_id}' was not found.")
        state = await self._goal_autonomy_state_repository.get_by_goal(goal_id)
        if state is None:
            raise NotFoundError(f"Autonomy state for goal '{goal_id}' was not found.")
        return state
