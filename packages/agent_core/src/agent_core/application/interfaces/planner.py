"""Planner service interface definitions."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from agent_core.application.services.memory import MemoryInterpretationResult
from agent_core.application.services.planner import MaterializedPlan
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.planning import DailyTask, StudyPlan


class PlannerServiceProtocol(Protocol):
    """Contract for planner orchestration used by task services."""

    async def build_plan(
        self,
        *,
        goal: LearnerGoal,
        version: int,
        trigger_source: str,
        supersedes_plan_id: str | None,
        rollout_overlay: dict[str, object] | None = None,
        rollout_context: dict[str, object] | None = None,
        memory_interpretation: MemoryInterpretationResult | None = None,
    ) -> MaterializedPlan:
        """Build a materialized study plan."""

    async def extend_plan_window(
        self,
        *,
        goal: LearnerGoal,
        active_plan: StudyPlan,
        existing_tasks: list[DailyTask],
        stage_id_by_position: dict[int, str],
    ) -> tuple[list[DailyTask], date | None]:
        """Extend the active plan materialization window."""
