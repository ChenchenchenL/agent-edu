"""Task autonomy and scheduling service with real business logic.

This service handles autonomy state queries and scheduling operations,
migrated from AutonomousTaskService to reduce God Class complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.entities.autonomy import LearnerAvailability
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

if TYPE_CHECKING:
    from agent_core.application.services.audit import AuditService
    from agent_core.domain.entities.autonomy import ScheduledAutonomyJob


# Callback types for complex coordination
SyncGoalStateCallback = Callable[[str, str | None, str | None], Awaitable[None]]
EnsureMaterializationJobCallback = Callable[[str, str], Awaitable[None]]
ValidateTimezoneCallback = Callable[[str | None], str | None]


class TaskAutonomySchedulingService:
    """Manage autonomy state and scheduling operations.

    Responsibilities:
    - Autonomy state queries (read-only)
    - Learner availability CRUD operations
    - Topic mastery queries (read-only)
    - Autonomy control operations (pause/resume)
    - Autonomy jobs listing

    Note: Complex scheduling operations (materialize_today, manual_replan,
    run_periodic_reflection, run_due_jobs) use callbacks to avoid deep
    coupling with job scheduler and reflection systems.
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
        """Materialize today's work window for a goal.

        Note: This method requires deep integration with job scheduler.
        Not migrated due to complexity (recursive job execution, timezone handling).
        Recommend system-wide job scheduler refactor before migration.
        """
        raise NotImplementedError(
            "materialize_today requires job scheduler integration. "
            "Use core.materialize_today() or wait for job system refactor."
        )

    async def manual_replan_goal(
        self,
        goal_id: str,
        payload: ManualReplanRequest,
    ) -> GoalAutonomyStateResponse:
        """Manually request a replan for a goal.

        Note: This method requires deep integration with job scheduler and planner.
        Not migrated due to complexity (job scheduling, recursive execution, state sync).
        Recommend system-wide job scheduler refactor before migration.
        """
        raise NotImplementedError(
            "manual_replan_goal requires job scheduler and planner integration. "
            "Use core.manual_replan_goal() or wait for job system refactor."
        )

    async def run_periodic_goal_reflection(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Run periodic reflection for a goal.

        Note: This method requires deep integration with reflection system.
        Not migrated due to complexity (reflection service coupling, state sync).
        Recommend reflection system decoupling before migration.
        """
        raise NotImplementedError(
            "run_periodic_goal_reflection requires reflection system integration. "
            "Use core.run_periodic_goal_reflection() or wait for reflection decoupling."
        )

    async def run_due_autonomy_jobs(
        self,
        *,
        raise_on_error: bool = True,
        lease_owner: str = "inline",
        limit: int = 20,
    ) -> int:
        """Run due autonomy jobs.

        Note: This is the core job orchestration logic (100+ lines).
        Not migrated due to complexity (job execution, lease management, error handling).
        Recommend system-wide job scheduler refactor before migration.
        """
        raise NotImplementedError(
            "run_due_autonomy_jobs is core orchestration logic (100+ lines). "
            "Use core.run_due_autonomy_jobs() or wait for job system refactor."
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
