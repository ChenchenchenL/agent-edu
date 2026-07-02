"""Memory interpretation for planner / workspace / reflection consumers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from agent_core.application.services.memory_conflict_policy import CONFLICT_CONTRADICTION_THRESHOLD
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
    MemoryConflictSet,
)

if TYPE_CHECKING:
    from agent_core.application.services.learner_memory.result_types import (
        MemoryInterpretationFact,
        MemoryInterpretationResult,
    )
    from agent_core.infrastructure.db.repositories import (
        BehaviorMemoryRepository,
        KnowledgeMemoryRepository,
        MemoryConflictRepository,
    )


class InterpretationService:
    """Build interpretation results from raw memories."""

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

    async def build_interpretation(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        limit_per_type: int = 8,
    ) -> MemoryInterpretationResult:
        from agent_core.application.services.learner_memory.result_types import (
            MemoryInterpretationFact,
            MemoryInterpretationResult,
        )
        knowledge = (
            await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id, learner_goal_id=learner_goal_id,
                statuses={"active", "stable", "candidate"}, limit=limit_per_type * 2,
            ) if self._knowledge_memory_repository is not None else []
        )
        behavior = (
            await self._behavior_memory_repository.list_by_profile(
                learner_profile_id, learner_goal_id=learner_goal_id,
                statuses={"active", "stable", "candidate"}, limit=limit_per_type * 2,
            ) if self._behavior_memory_repository is not None else []
        )
        conflicts = await self._list_conflicts(learner_profile_id, learner_goal_id)
        facts = [
            interpret_knowledge_memory(item) for item in knowledge
            if item.validation_status in {"validated", "locally_valid", "unverified"}
            and item.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD
        ][:limit_per_type]
        behavior_patterns = [
            interpret_behavior_memory(item) for item in behavior
            if item.validation_status in {"validated", "locally_valid", "unverified"}
            and item.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD
        ][:limit_per_type]
        contested_items = [
            interpret_knowledge_memory(item) for item in knowledge
            if item.validation_status == "contested" or item.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD
        ] + [
            interpret_behavior_memory(item) for item in behavior
            if item.validation_status == "contested" or item.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD
        ]
        constraints = interpretation_constraints(
            facts=facts, behavior_patterns=behavior_patterns,
            contested_items=contested_items, conflicts=conflicts,
        )
        return MemoryInterpretationResult(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            generated_at=datetime.now(timezone.utc), facts=facts,
            behavior_patterns=behavior_patterns, contested_items=contested_items[:limit_per_type],
            recommended_constraints=constraints, conflict_count=len(conflicts),
        )

    async def _list_conflicts(self, learner_profile_id: str, learner_goal_id: str | None) -> list[MemoryConflictSet]:
        if self._conflict_repository is None:
            return []
        return await self._conflict_repository.list_sets_by_profile(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            status="open", limit=20,
        )


def interpret_knowledge_memory(memory: KnowledgeMemory) -> MemoryInterpretationFact:
    from agent_core.application.services.learner_memory.result_types import MemoryInterpretationFact
    return MemoryInterpretationFact(
        memory_type="knowledge", memory_id=memory.id, memory_key=memory.knowledge_key,
        semantic_category=memory.semantic_category, validation_status=memory.validation_status,
        title=memory.title, summary=memory.summary,
        confidence_score=memory.confidence_score, importance_score=memory.importance_score,
        recommended_use=recommended_memory_use(memory),
    )


def interpret_behavior_memory(memory: BehaviorMemory) -> MemoryInterpretationFact:
    from agent_core.application.services.learner_memory.result_types import MemoryInterpretationFact
    return MemoryInterpretationFact(
        memory_type="behavior", memory_id=memory.id, memory_key=memory.behavior_key,
        semantic_category=memory.semantic_category, validation_status=memory.validation_status,
        title=memory.title, summary=memory.summary,
        confidence_score=memory.confidence_score, importance_score=memory.importance_score,
        recommended_use=recommended_memory_use(memory),
    )


def interpretation_constraints(
    *,
    facts: list,
    behavior_patterns: list,
    contested_items: list,
    conflicts: list,
) -> list[str]:
    constraints: list[str] = []
    if contested_items or conflicts:
        constraints.append("Do not treat contested memories as stable learner facts; ask for verification or gather evidence.")
    if any(item.validation_status == "unverified" for item in facts + behavior_patterns):
        constraints.append("Use unverified memories as weak context only and avoid strong claims.")
    if any(item.semantic_category == "misconception" for item in facts):
        constraints.append("Prioritize misconception checks before adding new material.")
    if any(item.semantic_category in {"preference", "strategy"} for item in behavior_patterns):
        constraints.append("Adapt teaching style to validated behavior patterns when planning tasks.")
    return constraints or ["Use validated and locally valid memories as contextual guidance, not absolute truth."]


def recommended_memory_use(memory: KnowledgeMemory | BehaviorMemory) -> str:
    if memory.validation_status == "contested" or memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
        return "verify_before_use"
    if memory.validation_status == "stale" or memory.freshness_score < 0.3:
        return "refresh_before_use"
    if memory.validation_status == "validated":
        return "safe_context"
    if memory.validation_status == "locally_valid":
        return "goal_scoped_context"
    return "weak_context"
