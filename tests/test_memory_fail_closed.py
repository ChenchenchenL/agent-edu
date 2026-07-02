"""Memory fail-closed lifecycle tests.

These tests verify that suppressed / archived / contested memories
are not automatically restored or promoted through various code paths.

This is a critical safety property of the memory system.
"""
from __future__ import annotations

import pytest

from agent_core.application.services.memory import MemoryService
from agent_core.domain.entities.memory import BehaviorMemory, KnowledgeMemory


class StubKnowledgeRepository:
    """Stub knowledge repository for testing."""

    def __init__(self):
        self.memories: dict[str, KnowledgeMemory] = {}

    async def get(self, memory_id: str) -> KnowledgeMemory:
        if memory_id not in self.memories:
            from agent_core.domain.errors import NotFoundError
            raise NotFoundError(f"Knowledge memory {memory_id} not found")
        return self.memories[memory_id]

    async def create(self, memory: KnowledgeMemory) -> KnowledgeMemory:
        self.memories[memory.id] = memory
        return memory

    async def update(self, memory: KnowledgeMemory) -> KnowledgeMemory:
        self.memories[memory.id] = memory
        return memory

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        knowledge_key: str,
        semantic_category: str,
        statuses: set[str],
    ) -> KnowledgeMemory | None:
        for memory in self.memories.values():
            if (
                memory.learner_profile_id == learner_profile_id
                and memory.knowledge_key == knowledge_key
                and memory.semantic_category == semantic_category
                and memory.status in statuses
            ):
                return memory
        return None


class StubBehaviorRepository:
    """Stub behavior repository for testing."""

    def __init__(self):
        self.memories: dict[str, BehaviorMemory] = {}

    async def get(self, memory_id: str) -> BehaviorMemory:
        if memory_id not in self.memories:
            from agent_core.domain.errors import NotFoundError
            raise NotFoundError(f"Behavior memory {memory_id} not found")
        return self.memories[memory_id]

    async def create(self, memory: BehaviorMemory) -> BehaviorMemory:
        self.memories[memory.id] = memory
        return memory

    async def update(self, memory: BehaviorMemory) -> BehaviorMemory:
        self.memories[memory.id] = memory
        return memory

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        behavior_key: str,
        behavior_category: str,
        statuses: set[str],
        semantic_category: str | None = None,
    ) -> BehaviorMemory | None:
        for memory in self.memories.values():
            if (
                memory.learner_profile_id == learner_profile_id
                and memory.behavior_key == behavior_key
                and memory.behavior_category == behavior_category
                and memory.status in statuses
            ):
                return memory
        return None


class TestSuppressedMemoryNotRestored:
    """Verify suppressed memories are not automatically restored."""

    @pytest.fixture
    def service(self):
        """Create a MemoryService with stub repositories."""
        knowledge_repo = StubKnowledgeRepository()
        behavior_repo = StubBehaviorRepository()
        return MemoryService(
            repository=None,
            knowledge_memory_repository=knowledge_repo,
            behavior_memory_repository=behavior_repo,
        ), knowledge_repo, behavior_repo

    @pytest.mark.asyncio
    async def test_suppressed_knowledge_not_restored_by_upsert(self, service):
        """Verify suppressed knowledge memory is not restored by upsert."""
        memory_service, knowledge_repo, _ = service

        suppressed_memory = KnowledgeMemory(
            id="k-suppressed-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            knowledge_key="suppressed topic",
            title="Suppressed knowledge",
            summary="This was suppressed",
            details=None,
            knowledge_level="foundation",
            time_horizon="early",
            importance_score=0.5,
            confidence_score=0.5,
            freshness_score=0.5,
            status="suppressed",
            suppressed_reason_code="low_quality",
            suppressed_reason_note="Too many contradictions",
            suppressed_by="operator",
            semantic_category="concept",
        )
        knowledge_repo.memories[suppressed_memory.id] = suppressed_memory

        incoming = KnowledgeMemory(
            id="k-incoming-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            knowledge_key="suppressed topic",
            title="Updated title",
            summary="Updated summary",
            details=None,
            knowledge_level="foundation",
            time_horizon="early",
            importance_score=0.6,
            confidence_score=0.6,
            freshness_score=0.7,
            source_event_ids=["evt-new"],
            semantic_category="concept",
        )

        result = await memory_service.upsert_knowledge_memory(incoming)

        assert result.action == "skipped_suppressed", (
            f"Expected 'skipped_suppressed' but got '{result.action}'"
        )
        assert result.memory.status == "suppressed", (
            "Suppressed memory status changed during upsert"
        )

    @pytest.mark.asyncio
    async def test_suppressed_behavior_not_restored_by_upsert(self, service):
        """Verify suppressed behavior memory is not restored by upsert."""
        memory_service, _, behavior_repo = service

        suppressed_memory = BehaviorMemory(
            id="b-suppressed-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            behavior_key="suppressed behavior",
            behavior_category="support_request",
            title="Suppressed behavior",
            summary="This was suppressed",
            details=None,
            behavior_level="surface",
            time_horizon="early",
            importance_score=0.5,
            confidence_score=0.5,
            freshness_score=0.5,
            status="suppressed",
            suppressed_reason_code="low_quality",
            suppressed_reason_note="Not relevant",
            suppressed_by="operator",
            semantic_category="strategy",
        )
        behavior_repo.memories[suppressed_memory.id] = suppressed_memory

        incoming = BehaviorMemory(
            id="b-incoming-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            behavior_key="suppressed behavior",
            behavior_category="support_request",
            title="Updated title",
            summary="Updated summary",
            details=None,
            behavior_level="surface",
            time_horizon="early",
            importance_score=0.6,
            confidence_score=0.6,
            freshness_score=0.7,
            source_event_ids=["evt-new"],
            semantic_category="strategy",
        )

        result = await memory_service.upsert_behavior_memory(incoming)

        assert result.action == "skipped_suppressed", (
            f"Expected 'skipped_suppressed' but got '{result.action}'"
        )
        assert result.memory.status == "suppressed", (
            "Suppressed memory status changed during upsert"
        )


class TestContestedMemoryNotPromoted:
    """Verify contested memories are not promoted."""

    @pytest.fixture
    def service(self):
        """Create a MemoryService with minimal dependencies."""
        return MemoryService(repository=None)

    def test_contested_knowledge_not_promotion_candidate(self, service):
        """Verify contested knowledge is not a promotion candidate."""
        contested_memory = KnowledgeMemory(
            id="k-contested-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            knowledge_key="contested topic",
            title="Contested knowledge",
            summary="Has contradictions",
            details=None,
            knowledge_level="core",
            time_horizon="mid",
            importance_score=0.7,
            confidence_score=0.6,
            freshness_score=0.8,
            stability_score=0.6,
            goal_relevance_score=0.7,
            support_score=0.5,
            contradiction_score=0.4,
            evidence_count=4,
            contradiction_count=3,
            assessment_evidence_count=2,
            task_evidence_count=2,
            status="candidate",
            validation_status="contested",
        )

        is_candidate = service._is_knowledge_promotion_candidate(contested_memory)

        assert not is_candidate, (
            "Contested knowledge should not be a promotion candidate"
        )

    def test_contested_behavior_not_promotion_candidate(self, service):
        """Verify behavior with low quality is not a promotion candidate.

        Note: Unlike knowledge, behavior promotion readiness does not check
        contradiction_score directly. This test verifies that low-quality
        contested behaviors are correctly blocked.
        """
        low_quality_contested = BehaviorMemory(
            id="b-contested-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            behavior_key="contested behavior",
            behavior_category="error_pattern",
            title="Contested behavior",
            summary="Has contradictions and low quality",
            details=None,
            behavior_level="surface",
            time_horizon="early",
            importance_score=0.3,
            confidence_score=0.3,
            freshness_score=0.4,
            stability_score=0.2,
            goal_relevance_score=0.3,
            support_score=0.2,
            contradiction_score=0.4,
            evidence_count=1,
            contradiction_count=1,
            cross_session_recurrence_count=0,
            status="candidate",
            validation_status="contested",
        )

        is_candidate = service._is_behavior_promotion_candidate(low_quality_contested)

        assert not is_candidate, (
            "Low quality contested behavior should not be a promotion candidate"
        )


class TestCandidateWithoutEligibilityNotPromoted:
    """Verify candidates without eligibility are not promoted."""

    @pytest.fixture
    def service(self):
        """Create a MemoryService with minimal dependencies."""
        return MemoryService(repository=None)

    def test_low_quality_knowledge_not_promotion_candidate(self, service):
        """Verify low quality knowledge is not a promotion candidate."""
        low_quality_memory = KnowledgeMemory(
            id="k-low-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            knowledge_key="low quality topic",
            title="Low quality knowledge",
            summary="Not enough evidence",
            details=None,
            knowledge_level="foundation",
            time_horizon="early",
            importance_score=0.3,
            confidence_score=0.3,
            freshness_score=0.5,
            stability_score=0.3,
            goal_relevance_score=0.3,
            support_score=0.2,
            contradiction_score=0.1,
            evidence_count=1,
            assessment_evidence_count=0,
            task_evidence_count=0,
            status="candidate",
        )

        is_candidate = service._is_knowledge_promotion_candidate(low_quality_memory)

        assert not is_candidate, (
            "Low quality knowledge should not be a promotion candidate"
        )

    def test_low_recurrence_behavior_not_promotion_candidate(self, service):
        """Verify low recurrence behavior is not a promotion candidate."""
        low_recurrence_memory = BehaviorMemory(
            id="b-low-001",
            learner_profile_id="profile-001",
            learner_goal_id="goal-001",
            behavior_key="low recurrence behavior",
            behavior_category="response_preference",
            title="Low recurrence behavior",
            summary="Not enough recurrence",
            details=None,
            behavior_level="surface",
            time_horizon="early",
            importance_score=0.5,
            confidence_score=0.5,
            freshness_score=0.7,
            stability_score=0.4,
            goal_relevance_score=0.5,
            support_score=0.4,
            contradiction_score=0.1,
            evidence_count=2,
            cross_session_recurrence_count=1,
            status="candidate",
        )

        is_candidate = service._is_behavior_promotion_candidate(low_recurrence_memory)

        assert not is_candidate, (
            "Low recurrence behavior should not be a promotion candidate"
        )
