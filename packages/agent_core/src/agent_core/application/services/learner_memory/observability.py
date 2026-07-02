"""Memory observability metric refresh."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.infrastructure.db.repositories import (
        BehaviorMemoryRepository,
        KnowledgeMemoryRepository,
        MemoryConflictRepository,
    )

from agent_core.infrastructure.observability.metrics import (
    set_memory_candidate_backlog,
    set_memory_open_conflicts,
)


class ObservabilityService:
    """Refresh Memory-related observability metrics."""

    def __init__(
        self,
        *,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        conflict_repository: MemoryConflictRepository | None = None,
    ) -> None:
        self._knowledge_memory_repository = knowledge_memory_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._conflict_repository = conflict_repository

    async def refresh_observability_metrics(self) -> None:
        if self._knowledge_memory_repository is not None and hasattr(self._knowledge_memory_repository, "count_by_status"):
            knowledge_counts = await self._knowledge_memory_repository.count_by_status()
            set_memory_candidate_backlog(memory_type="knowledge", count=knowledge_counts.get("candidate", 0))
        if self._behavior_memory_repository is not None and hasattr(self._behavior_memory_repository, "count_by_status"):
            behavior_counts = await self._behavior_memory_repository.count_by_status()
            set_memory_candidate_backlog(memory_type="behavior", count=behavior_counts.get("candidate", 0))
        if self._conflict_repository is not None:
            if hasattr(self._conflict_repository, "count_open_by_type"):
                open_counts = await self._conflict_repository.count_open_by_type()
            else:
                open_counts: dict[str, int] = {}
                if hasattr(self._conflict_repository, "list_open_sets"):
                    for conflict_set in await self._conflict_repository.list_open_sets():
                        open_counts[conflict_set.conflict_type] = open_counts.get(conflict_set.conflict_type, 0) + 1
            set_memory_open_conflicts(
                conflict_type="contradictory_evidence",
                count=open_counts.get("contradictory_evidence", 0),
            )
