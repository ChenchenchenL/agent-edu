"""Autonomy job dispatcher service."""

from __future__ import annotations

import logging

from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.application.services.autonomy_jobs.processors import AutonomyJobHandler
from typing import Protocol

logger = logging.getLogger(__name__)


class AutonomyJobDispatcherService:
    """Dispatches autonomy jobs to specific handlers based on job type."""

    def __init__(self) -> None:
        self._handlers: dict[str, AutonomyJobHandler] = {}

    def register_handler(self, job_type: str, handler: AutonomyJobHandler) -> None:
        """Register a handler for a specific job type."""
        self._handlers[job_type] = handler

    async def dispatch(self, job: ScheduledAutonomyJob) -> str | None:
        """Dispatch a job to its registered handler."""
        handler = self._handlers.get(job.job_type)
        if not handler:
            from agent_core.domain.errors import ValidationError
            raise ValidationError(f"Unsupported autonomy job type: {job.job_type}")
            
        try:
            return await handler.execute(job)
        except Exception as e:
            logger.exception(f"Handler failed for job {job.id} of type {job.job_type}: {e}")
            raise
