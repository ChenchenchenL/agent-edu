"""Reflection service interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.application.services.reflection import ReflectionTriggerRequest
from agent_core.domain.entities.planning import DailyTask
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.schemas.reflection import ReflectionListResponse


class ReflectionServiceProtocol(Protocol):
    """Contract for reflection orchestration."""

    async def trigger_reflection(self, request: ReflectionTriggerRequest) -> ReflectionRecord | None:
        """Trigger reflection processing."""

    async def get_record(self, reflection_id: str) -> ReflectionRecord:
        """Load a reflection record."""

    async def list_task_reflections(
        self,
        *,
        task_id: str,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> ReflectionListResponse:
        """List reflections for a task."""

    async def apply_outcome_feedback(
        self,
        *,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation | None,
    ) -> ReflectionRecord:
        """Apply evaluated outcome feedback to a reflection."""


class ReflectionEvidenceServiceProtocol(Protocol):
    """Contract for reflection evidence derivation."""

    async def derive_from_task(self, task: DailyTask) -> None:
        """Derive evidence from a completed task."""


class ReflectionOutcomeServiceProtocol(Protocol):
    """Contract for reflection outcome evaluation."""

    async def list_pending(
        self,
        *,
        learner_goal_id: str,
        limit: int = 10,
    ) -> list[ReflectionOutcomeEvaluation]:
        """List pending reflection outcome evaluations."""

    async def evaluate(
        self,
        *,
        reflection: ReflectionRecord,
        topic_key: str | None,
    ) -> ReflectionOutcomeEvaluation:
        """Evaluate a reflection outcome."""
