"""Memory service interface definitions."""

from __future__ import annotations

from typing import Protocol

from agent_core.application.services.memory import MemoryInterpretationResult
from agent_core.domain.schemas.memory import BehaviorMemoryBrowseResponse, KnowledgeMemoryBrowseResponse


class MemoryServiceProtocol(Protocol):
    """Contract for memory operations consumed by orchestration services."""

    async def build_interpretation(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        limit_per_type: int = 4,
    ) -> MemoryInterpretationResult:
        """Build memory interpretation for planning/runtime use."""

    async def browse_knowledge_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> KnowledgeMemoryBrowseResponse:
        """Browse knowledge memories."""

    async def browse_behavior_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> BehaviorMemoryBrowseResponse:
        """Browse behavior memories."""

    async def describe_knowledge_memory(self, memory) -> dict[str, object]:
        """Describe a knowledge memory."""

    async def describe_behavior_memory(self, memory) -> dict[str, object]:
        """Describe a behavior memory."""
