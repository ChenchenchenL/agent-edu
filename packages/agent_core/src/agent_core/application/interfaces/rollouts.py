"""Rollout-related service interface definitions."""

from __future__ import annotations

from typing import Protocol


class RolloutResolverProtocol(Protocol):
    """Contract for rollout overlay resolution."""

    async def get_active_overlay(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        include_staged: bool = False,
    ):
        """Resolve the active rollout overlay."""


class RolloutObservationSchedulerProtocol(Protocol):
    """Contract for rollout observation scheduling."""

    async def schedule_active(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> None:
        """Schedule observation for an active rollout."""
