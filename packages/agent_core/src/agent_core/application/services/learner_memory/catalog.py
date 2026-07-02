"""Read-only catalog queries for Memory browse / detail / operator views."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
    MemoryAnnotation,
    MemoryConflictMember,
    MemoryConflictSet,
    MemoryEvidenceLink,
    MemoryGovernanceDecision,
)
from agent_core.domain.errors import NotFoundError

if TYPE_CHECKING:
    from agent_core.application.services.learner_memory.result_types import (
        BrowseMemoriesResult,
        MemoryConflictMemberDetail,
    )
    from agent_core.infrastructure.db.repositories import (
        AnnotationRepository,
        BehaviorMemoryRepository,
        KnowledgeMemoryRepository,
        MemoryConflictRepository,
        MemoryEvidenceLinkRepository,
        MemoryGovernanceDecisionRepository,
    )


class CatalogService:
    """Read-only memory catalog queries."""

    def __init__(
        self,
        *,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        evidence_link_repository: MemoryEvidenceLinkRepository | None = None,
        governance_decision_repository: MemoryGovernanceDecisionRepository | None = None,
        annotation_repository: AnnotationRepository | None = None,
        conflict_repository: MemoryConflictRepository | None = None,
    ) -> None:
        self._knowledge_memory_repository = knowledge_memory_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._evidence_link_repository = evidence_link_repository
        self._governance_decision_repository = governance_decision_repository
        self._annotation_repository = annotation_repository
        self._conflict_repository = conflict_repository

    async def get_knowledge_memory(self, memory_id: str) -> KnowledgeMemory:
        if self._knowledge_memory_repository is None:
            raise NotFoundError(f"Knowledge memory '{memory_id}' was not found.")
        memory = await self._knowledge_memory_repository.get_by_id(memory_id)
        if memory is None:
            raise NotFoundError(f"Knowledge memory '{memory_id}' was not found.")
        return memory

    async def get_behavior_memory(self, memory_id: str) -> BehaviorMemory:
        if self._behavior_memory_repository is None:
            raise NotFoundError(f"Behavior memory '{memory_id}' was not found.")
        memory = await self._behavior_memory_repository.get_by_id(memory_id)
        if memory is None:
            raise NotFoundError(f"Behavior memory '{memory_id}' was not found.")
        return memory

    async def browse_knowledge_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> BrowseMemoriesResult:
        from agent_core.application.services.learner_memory.result_types import BrowseMemoriesResult
        if self._knowledge_memory_repository is None:
            return BrowseMemoriesResult(total=0, limit=limit, offset=offset, items=[])
        total = len(
            await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id, learner_goal_id=learner_goal_id, statuses=statuses,
            )
        )
        items = await self._knowledge_memory_repository.list_by_profile(
            learner_profile_id, learner_goal_id=learner_goal_id, statuses=statuses,
            limit=limit, offset=offset,
        )
        return BrowseMemoriesResult(total=total, limit=limit, offset=offset, items=items)

    async def browse_behavior_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> BrowseMemoriesResult:
        from agent_core.application.services.learner_memory.result_types import BrowseMemoriesResult
        if self._behavior_memory_repository is None:
            return BrowseMemoriesResult(total=0, limit=limit, offset=offset, items=[])
        total = len(
            await self._behavior_memory_repository.list_by_profile(
                learner_profile_id, learner_goal_id=learner_goal_id, statuses=statuses,
            )
        )
        items = await self._behavior_memory_repository.list_by_profile(
            learner_profile_id, learner_goal_id=learner_goal_id, statuses=statuses,
            limit=limit, offset=offset,
        )
        return BrowseMemoriesResult(total=total, limit=limit, offset=offset, items=items)

    async def list_evidence_links(self, *, memory_type: str, memory_id: str) -> list[MemoryEvidenceLink]:
        if self._evidence_link_repository is None:
            return []
        return await self._evidence_link_repository.list_by_memory(memory_type=memory_type, memory_id=memory_id)

    async def list_governance_decisions(self, *, memory_type: str, memory_id: str) -> list[MemoryGovernanceDecision]:
        if self._governance_decision_repository is None:
            return []
        return await self._governance_decision_repository.list_by_memory(memory_type=memory_type, memory_id=memory_id)

    async def list_annotations(self, *, memory_type: str, memory_id: str) -> list[MemoryAnnotation]:
        if self._annotation_repository is None:
            return []
        return await self._annotation_repository.list_by_memory(memory_type=memory_type, memory_id=memory_id)

    async def list_conflict_sets(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[MemoryConflictSet]:
        if self._conflict_repository is None:
            return []
        return await self._conflict_repository.list_sets_by_profile(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            status=status,
            limit=limit,
        )

    async def list_conflict_members(self, *, conflict_set_id: str) -> list[MemoryConflictMember]:
        if self._conflict_repository is None:
            return []
        return await self._conflict_repository.list_members(conflict_set_id=conflict_set_id)

    async def list_conflict_member_details(self, *, conflict_set_id: str) -> list[MemoryConflictMemberDetail]:
        from agent_core.application.services.learner_memory.result_types import MemoryConflictMemberDetail
        members = await self.list_conflict_members(conflict_set_id=conflict_set_id)
        if not members:
            return []
        knowledge_ids = [item.memory_id for item in members if item.memory_type == "knowledge"]
        behavior_ids = [item.memory_id for item in members if item.memory_type == "behavior"]
        memories: dict[tuple[str, str], KnowledgeMemory | BehaviorMemory] = {}
        if knowledge_ids and self._knowledge_memory_repository is not None:
            for memory in await self._knowledge_memory_repository.list_by_ids(knowledge_ids):
                memories[("knowledge", memory.id)] = memory
        if behavior_ids and self._behavior_memory_repository is not None:
            for memory in await self._behavior_memory_repository.list_by_ids(behavior_ids):
                memories[("behavior", memory.id)] = memory
        return [
            _conflict_member_detail(
                member=member,
                memory=memories.get((member.memory_type, member.memory_id)),
            )
            for member in members
        ]


def _conflict_member_detail(
    *,
    member: MemoryConflictMember,
    memory: KnowledgeMemory | BehaviorMemory | None,
) -> Any:
    from agent_core.application.services.learner_memory.result_types import MemoryConflictMemberDetail
    return MemoryConflictMemberDetail(
        id=member.id,
        conflict_set_id=member.conflict_set_id,
        memory_type=member.memory_type,
        memory_id=member.memory_id,
        memory_key=member.memory_key,
        stance=member.stance,
        support_score=member.support_score,
        contradiction_score=member.contradiction_score,
        member_title=memory.title if memory is not None else None,
        member_summary=memory.summary if memory is not None else None,
        member_status=memory.status if memory is not None else None,
        member_validation_status=memory.validation_status if memory is not None else None,
        created_at=member.created_at,
    )
