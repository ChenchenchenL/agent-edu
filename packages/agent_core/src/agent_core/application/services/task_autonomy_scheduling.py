"""Task autonomy and scheduling facade service."""

from __future__ import annotations

from agent_core.application.services.task import AutonomousTaskService
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.domain.schemas.autonomy import (
    GoalAutonomyStateResponse,
    LearnerAvailabilityResponse,
    LearnerTopicMasteryResponse,
    ManualReplanRequest,
    UpdateLearnerAvailabilityRequest,
)


class TaskAutonomySchedulingService:
    """Expose autonomy state and scheduling operations through a focused service."""

    def __init__(self, *, core: AutonomousTaskService) -> None:
        """Initialize the scheduling service.

        Args:
            core: Shared task core implementation.
        """
        self._core = core

    async def get_goal_autonomy_state(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Get the autonomy state for a goal."""
        return await self._core.get_goal_autonomy_state(goal_id)

    async def update_goal_availability(
        self,
        *,
        goal_id: str,
        payload: UpdateLearnerAvailabilityRequest,
    ) -> LearnerAvailabilityResponse:
        """Update learner availability for a goal."""
        return await self._core.update_goal_availability(goal_id=goal_id, payload=payload)

    async def get_goal_availability(self, goal_id: str) -> LearnerAvailabilityResponse:
        """Fetch learner availability for a goal."""
        return await self._core.get_goal_availability(goal_id)

    async def list_goal_mastery(self, goal_id: str) -> list[LearnerTopicMasteryResponse]:
        """List learner mastery snapshots for a goal."""
        return await self._core.list_goal_mastery(goal_id)

    async def pause_goal_autonomy(self, goal_id: str, reason: str | None = None) -> GoalAutonomyStateResponse:
        """Pause autonomy for a goal."""
        return await self._core.pause_goal_autonomy(goal_id, reason=reason)

    async def resume_goal_autonomy(self, goal_id: str, reason: str | None = None) -> GoalAutonomyStateResponse:
        """Resume autonomy for a goal."""
        return await self._core.resume_goal_autonomy(goal_id, reason=reason)

    async def list_autonomy_jobs(self, goal_id: str) -> list[ScheduledAutonomyJob]:
        """List autonomy jobs for a goal."""
        return await self._core.list_autonomy_jobs(goal_id)

    async def materialize_today(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Materialize today's work window for a goal."""
        return await self._core.materialize_today(goal_id)

    async def manual_replan_goal(
        self,
        goal_id: str,
        payload: ManualReplanRequest,
    ) -> GoalAutonomyStateResponse:
        """Manually request a replan for a goal."""
        return await self._core.manual_replan_goal(goal_id, payload)

    async def run_periodic_goal_reflection(self, goal_id: str) -> GoalAutonomyStateResponse:
        """Run periodic reflection for a goal."""
        return await self._core.run_periodic_goal_reflection(goal_id)

    async def run_due_autonomy_jobs(
        self,
        *,
        raise_on_error: bool = True,
        lease_owner: str = "inline",
        limit: int = 20,
    ) -> int:
        """Run due autonomy jobs."""
        return await self._core.run_due_autonomy_jobs(
            raise_on_error=raise_on_error,
            lease_owner=lease_owner,
            limit=limit,
        )
