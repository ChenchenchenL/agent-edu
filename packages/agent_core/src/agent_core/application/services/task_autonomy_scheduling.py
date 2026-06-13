"""Task autonomy and scheduling service with real business logic.

This service handles autonomy state queries and scheduling operations,
migrated from AutonomousTaskService to reduce God Class complexity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.errors import NotFoundError
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
)

if TYPE_CHECKING:
    from agent_core.application.services.task import AutonomousTaskService
    from agent_core.domain.entities.autonomy import ScheduledAutonomyJob


class TaskAutonomySchedulingService:
    """Manage autonomy state and scheduling operations.

    Responsibilities:
    - Autonomy state queries (read-only)
    - Learner availability queries (read-only)
    - Topic mastery queries (read-only)
    - Autonomy control operations (pause/resume)
    - Scheduling operations (materialization, replan)

    Note: Complex scheduling logic remains in AutonomousTaskService until
    full migration is complete.
    """

    def __init__(
        self,
        *,
        db_session: AsyncSession,
        goal_repository: LearnerGoalRepository,
        goal_autonomy_state_repository: GoalAutonomyStateRepository | None = None,
        learner_availability_repository: LearnerAvailabilityRepository | None = None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
        core: AutonomousTaskService | None = None,
    ) -> None:
        """Initialize the scheduling service with real dependencies.

        Args:
            db_session: Database session for transaction management.
            goal_repository: Repository for learner goals.
            goal_autonomy_state_repository: Optional repository for autonomy state.
            learner_availability_repository: Optional repository for availability.
            learner_topic_mastery_repository: Optional repository for mastery.
            core: Optional legacy task core for compatibility delegation.
        """
        self._db_session = db_session
        self._goal_repository = goal_repository
        self._goal_autonomy_state_repository = goal_autonomy_state_repository
        self._learner_availability_repository = learner_availability_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._core = core

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

        Note: This method delegates to core due to complex side effects.

        Args:
            goal_id: Learner goal identifier.
            payload: Availability update request.

        Returns:
            Updated availability response.
        """
        if self._core is None:
            raise NotImplementedError("update_goal_availability migration pending")
        return await self._core.update_goal_availability(goal_id=goal_id, payload=payload)

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

        Note: This method delegates to core due to complex state coordination.
        """
        if self._core is None:
            raise NotImplementedError("pause_goal_autonomy migration pending")
        return await self._core.pause_goal_autonomy(goal_id, reason=reason)

    async def resume_goal_autonomy(self, goal_id: str, reason: str | None = None) -> GoalAutonomyStateResponse:
        """Resume autonomy for a goal.

        Note: This method delegates to core due to complex state coordination.
        """
        if self._core is None:
            raise NotImplementedError("resume_goal_autonomy migration pending")
        return await self._core.resume_goal_autonomy(goal_id, reason=reason)

    async def list_autonomy_jobs(self, goal_id: str) -> list[ScheduledAutonomyJob]:
        """List autonomy jobs for a goal.

        Note: This method delegates to core due to complex job management.
        """
        if self._core is None:
            raise NotImplementedError("list_autonomy_jobs migration pending")
        return await self._core.list_autonomy_jobs(goal_id)

    async def materialize_today(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Materialize today's work window for a goal.

        Note: This method delegates to core due to complex materialization logic.
        """
        if self._core is None:
            raise NotImplementedError("materialize_today migration pending")
        return await self._core.materialize_today(goal_id)

    async def manual_replan_goal(
        self,
        goal_id: str,
        payload: ManualReplanRequest,
    ) -> GoalAutonomyStateResponse:
        """Manually request a replan for a goal.

        Note: This method delegates to core due to complex planning integration.
        """
        if self._core is None:
            raise NotImplementedError("manual_replan_goal migration pending")
        return await self._core.manual_replan_goal(goal_id, payload)

    async def run_periodic_goal_reflection(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Run periodic reflection for a goal.

        Note: This method delegates to core due to complex reflection integration.
        """
        if self._core is None:
            raise NotImplementedError("run_periodic_goal_reflection migration pending")
        return await self._core.run_periodic_goal_reflection(goal_id)

    async def run_due_autonomy_jobs(
        self,
        *,
        raise_on_error: bool = True,
        lease_owner: str = "inline",
        limit: int = 20,
    ) -> int:
        """Run due autonomy jobs.

        Note: This method delegates to core due to complex job orchestration.
        """
        if self._core is None:
            raise NotImplementedError("run_due_autonomy_jobs migration pending")
        return await self._core.run_due_autonomy_jobs(
            raise_on_error=raise_on_error,
            lease_owner=lease_owner,
            limit=limit,
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
