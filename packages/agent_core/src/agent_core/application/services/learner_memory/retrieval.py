"""Memory retrieval: session / profile / knowledge / behavior search."""

from __future__ import annotations

from datetime import datetime, timezone
from math import sqrt
from time import perf_counter
from typing import TYPE_CHECKING, Callable, Awaitable

from agent_core.domain.entities.memory import (
    BEHAVIOR_LEVELS,
    MEMORY_RETRIEVAL_STATUSES,
    BehaviorMemoryEmbeddingRecord,
    BehaviorMemoryRetrievalResult,
    KnowledgeMemoryEmbeddingRecord,
    KnowledgeMemoryRetrievalResult,
    MemoryEmbeddingRecord,
    MemoryRetrievalResult,
    RetrievedBehaviorMemory,
    RetrievedKnowledgeMemory,
    RetrievedMemory,
)
from agent_core.application.services.learner_memory.quality import review_recommended
from dataclasses import dataclass

if TYPE_CHECKING:
    from agent_core.infrastructure.db.repositories import (
        BehaviorMemoryEmbeddingRepository,
        KnowledgeMemoryEmbeddingRepository,
        MemoryEmbeddingRepository,
        MemoryPromotionEligibilityRepository,
        KnowledgeMemoryRepository,
        BehaviorMemoryRepository,
    )
    from agent_core.infrastructure.embedding.types import EmbeddingProvider

from agent_core.infrastructure.observability.metrics import observe_memory_retrieval, observe_embedding_dimension_mismatch
from agent_core.application.services.learner_memory.quality import clamp_score


@dataclass
class RetrievalWeightProfile:
    similarity: float
    importance: float
    confidence: float
    freshness: float
    stability: float
    goal_relevance: float

DEFAULT_RETRIEVAL_PROFILE = RetrievalWeightProfile(
    similarity=0.40, importance=0.20, confidence=0.15,
    freshness=0.10, stability=0.10, goal_relevance=0.05
)

RETRIEVAL_PROFILES: dict[str, RetrievalWeightProfile] = {
    "default": DEFAULT_RETRIEVAL_PROFILE,
    "chat": RetrievalWeightProfile(
        similarity=0.50, importance=0.10, confidence=0.10,
        freshness=0.20, stability=0.05, goal_relevance=0.05
    ),
    "hint": RetrievalWeightProfile(
        similarity=0.60, importance=0.05, confidence=0.05,
        freshness=0.10, stability=0.05, goal_relevance=0.15
    ),
    "planning": RetrievalWeightProfile(
        similarity=0.20, importance=0.25, confidence=0.15,
        freshness=0.10, stability=0.20, goal_relevance=0.10
    ),
    "reflection": RetrievalWeightProfile(
        similarity=0.30, importance=0.20, confidence=0.20,
        freshness=0.10, stability=0.10, goal_relevance=0.10
    ),
}

from agent_core.infrastructure.embedding.types import DimensionMismatchError


class RetrievalService:
    """Retrieve relevant memories by embedding similarity."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        embedding_repository: MemoryEmbeddingRepository | None = None,
        knowledge_memory_embedding_repository: KnowledgeMemoryEmbeddingRepository | None = None,
        behavior_memory_embedding_repository: BehaviorMemoryEmbeddingRepository | None = None,
        promotion_eligibility_repository: MemoryPromotionEligibilityRepository | None = None,
        governance_config: dict[str, float | int] | None = None,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._embedding_repository = embedding_repository
        self._knowledge_memory_embedding_repository = knowledge_memory_embedding_repository
        self._behavior_memory_embedding_repository = behavior_memory_embedding_repository
        self._promotion_eligibility_repository = promotion_eligibility_repository
        self._governance_config = governance_config or {}
        self._knowledge_memory_repository = knowledge_memory_repository
        self._behavior_memory_repository = behavior_memory_repository

    async def retrieve_relevant_session_memories(
        self, *, session_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
    ) -> MemoryRetrievalResult:
        return await self._retrieve_memory_events(
            query_text=query_text, candidate_limit=candidate_limit, min_score=min_score, limit=limit,
            fetch=lambda: self._embedding_repository.list_recent_by_session(session_id=session_id, limit=candidate_limit)
            if self._embedding_repository is not None else [],
            filter_scope=None,
        )

    async def retrieve_relevant_profile_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
    ) -> MemoryRetrievalResult:
        return await self._retrieve_memory_events(
            query_text=query_text, candidate_limit=candidate_limit, min_score=min_score, limit=limit,
            fetch=lambda: self._embedding_repository.list_recent_by_profile(
                learner_profile_id=learner_profile_id, limit=candidate_limit,
            ) if self._embedding_repository is not None else [],
            filter_scope="profile",
        )

    async def retrieve_relevant_knowledge_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
        surface: str = "default",
    ) -> KnowledgeMemoryRetrievalResult:
        if self._embedding_provider is None or self._knowledge_memory_embedding_repository is None:
            return KnowledgeMemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0, eligible_candidate_count=0)
        started_at = perf_counter()
        query_vectors = await self._embedding_provider.embed_texts([query_text])
        if not query_vectors:
            return KnowledgeMemoryRetrievalResult(
                memories=[], provider=self._embedding_provider.provider_name, model=self._embedding_provider.model_name,
                latency_ms=int((perf_counter() - started_at) * 1000), candidate_count=0, eligible_candidate_count=0,
            )
        query_vector = query_vectors[0]
        active_candidates = await self._knowledge_memory_embedding_repository.list_recent_by_profile(
            learner_profile_id=learner_profile_id, limit=candidate_limit,
        )
        eligible_embeddings: list = []
        if self._promotion_eligibility_repository is not None:
            eligible_records = await self._promotion_eligibility_repository.list_current_eligible_by_profile(
                learner_profile_id=learner_profile_id, limit=candidate_limit,
            )
            eligible_ids = {item.memory_id: item for item in eligible_records}
            eligible_embeddings = await self._knowledge_memory_embedding_repository.list_by_memory_ids(
                learner_profile_id=learner_profile_id, memory_ids=list(eligible_ids), statuses={"candidate"},
            )
        else:
            eligible_records = []
            eligible_ids = {}
        candidates = active_candidates + [item for item in eligible_embeddings if item.memory_id not in {c.memory_id for c in active_candidates}]

        is_learner_facing = surface in {"chat", "hint"}
        # Batch fetch full memory entities if learner_facing is enabled
        memories_by_id = {}
        if is_learner_facing and self._knowledge_memory_repository is not None and candidates:
            memory_ids = [item.memory_id for item in candidates]
            full_memories = await self._knowledge_memory_repository.list_by_ids(memory_ids)
            memories_by_id = {m.id: m for m in full_memories}

        scored: list[RetrievedKnowledgeMemory] = []
        eligible_candidate_count = 0
        retrieval_weight = float(self._governance_config.get("promotion_eligibility_retrieval_weight", 0.65))
        profile = RETRIEVAL_PROFILES.get(surface, DEFAULT_RETRIEVAL_PROFILE)
        dimension_mismatches = 0
        for item in candidates:
            eligible_record = eligible_ids.get(item.memory_id)
            if not item.vector:
                continue
            if item.status not in MEMORY_RETRIEVAL_STATUSES and eligible_record is None:
                continue
            try:
                score = score_long_term_memory(
                    vector=item.vector, query_vector=query_vector,
                    importance_score=item.importance_score, confidence_score=item.confidence_score,
                    freshness_score=item.freshness_score, stability_score=item.stability_score,
                    goal_relevance_score=item.goal_relevance_score, created_at=item.created_at,
                    profile=profile,
                )
            except DimensionMismatchError:
                dimension_mismatches += 1
                # Degrade: ignore similarity, fallback to 50% freshness + 50% importance
                score = 0.5 * (item.freshness_score * freshness_decay(item.created_at)) + 0.5 * item.importance_score

            governance_state = item.status
            if eligible_record is not None and item.status == "candidate":
                score *= retrieval_weight
                governance_state = "candidate_eligible"
                eligible_candidate_count += 1
                if is_learner_facing:
                    score = min(score, 0.5)

            if is_learner_facing and item.memory_id in memories_by_id:
                full_mem = memories_by_id[item.memory_id]
                if getattr(full_mem, "validation_status", None) == "contested":
                    score *= 0.1
                score -= 0.5 * getattr(full_mem, "contradiction_score", 0.0)
                if review_recommended(full_mem):
                    score -= 0.3
                score = max(0.0, score)

            scored.append(RetrievedKnowledgeMemory(
                memory_id=item.memory_id, knowledge_key=item.knowledge_key, title=item.title,
                summary=item.summary, knowledge_level=item.knowledge_level, time_horizon=item.time_horizon,
                importance_score=item.importance_score, confidence_score=item.confidence_score,
                freshness_score=item.freshness_score, stability_score=item.stability_score,
                goal_relevance_score=item.goal_relevance_score, status=item.status,
                governance_state=governance_state,
                eligibility_score=eligible_record.score if eligible_record is not None else None,
                score=score, created_at=item.created_at,
            ))
        scored.sort(key=lambda item: (item.score, item.importance_score, item.created_at), reverse=True)
        memories = [item for item in scored if item.score >= min_score][:limit]
        if dimension_mismatches > 0:
            observe_embedding_dimension_mismatch(memory_type="knowledge", surface=surface)
        observe_memory_retrieval(memory_type="knowledge", result_count=len(memories), candidate_count=len(candidates), eligible_candidate_count=eligible_candidate_count)
        return KnowledgeMemoryRetrievalResult(
            memories=memories, provider=self._embedding_provider.provider_name, model=self._embedding_provider.model_name,
            latency_ms=int((perf_counter() - started_at) * 1000), candidate_count=len(candidates), eligible_candidate_count=eligible_candidate_count,
        )

    async def retrieve_relevant_behavior_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
        surface: str = "default",
    ) -> BehaviorMemoryRetrievalResult:
        if self._embedding_provider is None or self._behavior_memory_embedding_repository is None:
            return BehaviorMemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0)
        started_at = perf_counter()
        query_vectors = await self._embedding_provider.embed_texts([query_text])
        if not query_vectors:
            return BehaviorMemoryRetrievalResult(
                memories=[], provider=self._embedding_provider.provider_name, model=self._embedding_provider.model_name,
                latency_ms=int((perf_counter() - started_at) * 1000), candidate_count=0,
            )
        query_vector = query_vectors[0]
        candidates = await self._behavior_memory_embedding_repository.list_recent_by_profile(
            learner_profile_id=learner_profile_id, limit=candidate_limit,
        )

        is_learner_facing = surface in {"chat", "hint"}
        # Batch fetch full memory entities if learner_facing is enabled
        memories_by_id = {}
        if is_learner_facing and self._behavior_memory_repository is not None and candidates:
            memory_ids = [item.memory_id for item in candidates]
            full_memories = await self._behavior_memory_repository.list_by_ids(memory_ids)
            memories_by_id = {m.id: m for m in full_memories}

        scored: list[RetrievedBehaviorMemory] = []
        profile = RETRIEVAL_PROFILES.get(surface, DEFAULT_RETRIEVAL_PROFILE)
        dimension_mismatches = 0
        for item in candidates:
            if not item.vector or item.status not in MEMORY_RETRIEVAL_STATUSES:
                continue
            try:
                score = score_long_term_memory(
                    vector=item.vector, query_vector=query_vector,
                    importance_score=item.importance_score, confidence_score=item.confidence_score,
                    freshness_score=item.freshness_score, stability_score=item.stability_score,
                    goal_relevance_score=item.goal_relevance_score, created_at=item.created_at,
                    profile=profile,
                )
            except DimensionMismatchError:
                dimension_mismatches += 1
                score = 0.5 * (item.freshness_score * freshness_decay(item.created_at)) + 0.5 * item.importance_score

            if is_learner_facing and item.memory_id in memories_by_id:
                full_mem = memories_by_id[item.memory_id]
                if getattr(full_mem, "validation_status", None) == "contested":
                    score *= 0.1
                score -= 0.5 * getattr(full_mem, "contradiction_score", 0.0)
                if review_recommended(full_mem):
                    score -= 0.3
                score = max(0.0, score)

            scored.append(RetrievedBehaviorMemory(
                memory_id=item.memory_id, behavior_key=item.behavior_key, behavior_category=item.behavior_category,
                title=item.title, summary=item.summary, behavior_level=item.behavior_level,
                time_horizon=item.time_horizon, importance_score=item.importance_score,
                confidence_score=item.confidence_score, freshness_score=item.freshness_score,
                stability_score=item.stability_score, goal_relevance_score=item.goal_relevance_score,
                status=item.status, score=score, created_at=item.created_at,
            ))
        scored.sort(key=lambda item: (item.score, item.importance_score, item.created_at), reverse=True)
        memories = [item for item in scored if item.score >= min_score][:limit]
        if dimension_mismatches > 0:
            observe_embedding_dimension_mismatch(memory_type="behavior", surface=surface)
        observe_memory_retrieval(memory_type="behavior", result_count=len(memories), candidate_count=len(candidates))
        return BehaviorMemoryRetrievalResult(
            memories=memories, provider=self._embedding_provider.provider_name, model=self._embedding_provider.model_name,
            latency_ms=int((perf_counter() - started_at) * 1000), candidate_count=len(candidates),
        )

    async def _retrieve_memory_events(
        self, *, query_text: str, candidate_limit: int, min_score: float, limit: int,
        fetch: Callable[[], Awaitable[list]], filter_scope: str | None,
    ) -> MemoryRetrievalResult:
        if self._embedding_provider is None or self._embedding_repository is None:
            return MemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0)
        started_at = perf_counter()
        query_vectors = await self._embedding_provider.embed_texts([query_text])
        if not query_vectors:
            return MemoryRetrievalResult(
                memories=[], provider=self._embedding_provider.provider_name, model=self._embedding_provider.model_name,
                latency_ms=int((perf_counter() - started_at) * 1000), candidate_count=0,
            )
        candidates = await fetch()
        query_vector = query_vectors[0]
        scored = [
            RetrievedMemory(
                memory_event_id=item.memory_event_id, summary=item.summary, memory_scope=item.memory_scope,
                memory_level=item.memory_level, progress_note=None, struggle_note=None, concept_focus=None,
                score=cosine_similarity(query_vector, item.vector), created_at=item.created_at,
            )
            for item in candidates
            if item.vector and (filter_scope is None or item.memory_scope == filter_scope)
        ]
        scored.sort(key=lambda item: (item.score, item.created_at), reverse=True)
        return MemoryRetrievalResult(
            memories=[item for item in scored if item.score >= min_score][:limit],
            provider=self._embedding_provider.provider_name, model=self._embedding_provider.model_name,
            latency_ms=int((perf_counter() - started_at) * 1000), candidate_count=len(candidates),
        )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    if len(left) != len(right):
        raise DimensionMismatchError(f"Embedding dimension mismatch: {len(left)} != {len(right)}")
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = sqrt(sum(a * a for a in left))
    right_norm = sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def score_long_term_memory(
    *, vector: list[float], query_vector: list[float],
    importance_score: float, confidence_score: float,
    freshness_score: float, stability_score: float,
    goal_relevance_score: float, created_at: datetime,
    profile: RetrievalWeightProfile,
) -> float:
    similarity = cosine_similarity(query_vector, vector)
    freshness = freshness_score * freshness_decay(created_at)
    return (
        profile.similarity * similarity +
        profile.importance * importance_score +
        profile.confidence * confidence_score +
        profile.freshness * freshness +
        profile.stability * stability_score +
        profile.goal_relevance * goal_relevance_score
    )


def freshness_decay(created_at: datetime) -> float:
    age = datetime.now(timezone.utc) - created_at
    age_days = max(age.total_seconds() / 86400.0, 0.0)
    return max(0.1, 1.0 - age_days / 30.0)


def decay_freshness(current: float, updated_at: datetime, time_horizon: str, level: str) -> float:
    days = max((datetime.now(timezone.utc) - updated_at).total_seconds() / 86400.0, 0.0)
    if time_horizon == "early":
        window = 14
    elif time_horizon == "mid":
        window = 45 if level not in BEHAVIOR_LEVELS else 21
    else:
        window = 120 if level not in BEHAVIOR_LEVELS else 60
    return max(0.0, min(current, 1.0 - min(days / max(window, 1), 1.0)))
