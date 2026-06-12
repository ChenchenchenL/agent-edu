"""Autonomy job service interface definitions."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from agent_core.domain.entities.autonomy import ScheduledAutonomyJob


class AutonomyJobServiceProtocol(Protocol):
    """Contract for scheduling autonomy jobs."""

    async def create_job(
        self,
        *,
        learner_goal_id: str,
        job_type: str,
        trigger_source: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, object] | None = None,
    ) -> ScheduledAutonomyJob | None:
        """Schedule an autonomy job."""
