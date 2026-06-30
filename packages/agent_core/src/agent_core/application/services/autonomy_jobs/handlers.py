"""Autonomy job execution handlers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from datetime import datetime, date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.entities.autonomy import ScheduledAutonomyJob, AUTONOMY_REPLAN_MODES
from agent_core.domain.entities.planning import DailyTask
from agent_core.domain.errors import ValidationError

if TYPE_CHECKING:
    from agent_core.application.services.task import AutonomousTaskService


logger = logging.getLogger(__name__)


class AutonomyJobHandler:
    """Protocol for autonomy job handlers."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        """Execute the job and return the result payload or None."""
        ...


class BaseAutonomyJobHandler:
    """Base class providing common dependencies for job handlers.
    
    This temporarily depends on the legacy core to allow piecemeal migration.
    """
    
    def __init__(
        self,
        *,
        db_session: AsyncSession,
        core: AutonomousTaskService,
    ) -> None:
        self._db_session = db_session
        self._core = core


class ReviewSchedulingJobHandler(BaseAutonomyJobHandler):
    """Handler for review_scheduling autonomy jobs."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._core._process_review_scheduling_job(job)  # noqa: SLF001


class ReplanJobHandler(BaseAutonomyJobHandler):
    """Handler for replan autonomy jobs."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._core._process_replan_job(job)  # noqa: SLF001


class AssessmentGenerationJobHandler(BaseAutonomyJobHandler):
    """Handler for assessment_generation autonomy jobs."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._core._process_assessment_generation_job(job)  # noqa: SLF001


class DailyTaskMaterializationJobHandler(BaseAutonomyJobHandler):
    """Handler for daily_task_materialization autonomy jobs."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._core._process_daily_task_materialization_job(job)  # noqa: SLF001


class ReflectionSkillEvolutionCuratorJobHandler(BaseAutonomyJobHandler):
    """Handler for reflection_skill_evolution_curator autonomy jobs."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._core._process_reflection_skill_evolution_curator_job(job)  # noqa: SLF001


class SkillReplacementAutoExecutionJobHandler(BaseAutonomyJobHandler):
    """Handler for skill_replacement_auto_execution autonomy jobs."""

    async def execute(self, job: ScheduledAutonomyJob) -> str | None:
        return await self._core._process_skill_replacement_auto_execution_job(job)  # noqa: SLF001
