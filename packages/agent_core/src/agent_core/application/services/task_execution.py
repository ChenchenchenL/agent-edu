"""Task execution facade service."""

from __future__ import annotations

from agent_core.application.services.task import AutonomousTaskService
from agent_core.domain.schemas.planning import ExecuteDailyTaskResponse


class TaskExecutionService:
    """Expose task execution through a focused service."""

    def __init__(self, *, core: AutonomousTaskService) -> None:
        """Initialize the execution service.

        Args:
            core: Shared task core implementation.
        """
        self._core = core

    async def execute_task(self, task_id: str) -> ExecuteDailyTaskResponse:
        """Execute a task."""
        return await self._core.execute_task(task_id)
