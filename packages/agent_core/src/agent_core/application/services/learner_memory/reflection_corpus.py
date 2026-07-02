"""Reflection corpus and governance summary construction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from agent_core.application.services.memory_conflict_policy import CONFLICT_CONTRADICTION_THRESHOLD
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    KnowledgeMemory,
    MemoryConflictSet,
)

if TYPE_CHECKING:
    from agent_core.application.services.audit import AuditService
    from agent_core.application.services.learner_memory.result_types import (
        MemoryGovernanceSummary,
        ReflectionCorpusMemoryItem,
        ReflectionCorpusResult,
        ReflectionCorpusSummary,
    )
    from agent_core.infrastructure.db.repositories import (
        BehaviorMemoryRepository,
        KnowledgeMemoryRepository,
        MemoryEvidenceLinkRepository,
        MemoryGovernanceDecisionRepository,
    )


class ReflectionCorpusService:
    """Build reflection corpus and governance summary from raw memories."""

    def __init__(
        self,
        *,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        governance_decision_repository: MemoryGovernanceDecisionRepository | None = None,
        evidence_link_repository: MemoryEvidenceLinkRepository | None = None,
        audit_service: AuditService | None = None,
        governance_config: dict[str, float | int] | None = None,
        evidence_mix_fn: Any = None,
        quality_snapshot_fn: Any = None,
        quality_snapshot_sync_fn: Any = None,
        topic_alignment_fn: Any = None,
    ) -> None:
        self._knowledge_memory_repository = knowledge_memory_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._governance_decision_repository = governance_decision_repository
        self._evidence_link_repository = evidence_link_repository
        self._audit_service = audit_service
        self._governance_config = governance_config or {}
        self._evidence_mix_fn = evidence_mix_fn
        self._quality_snapshot_fn = quality_snapshot_fn
        self._quality_snapshot_sync_fn = quality_snapshot_sync_fn
        self._topic_alignment_fn = topic_alignment_fn

    async def build_reflection_corpus(
        self, *, learner_profile_id: str, learner_goal_id: str | None = None, limit_per_type: int = 8,
    ) -> ReflectionCorpusResult:
        from agent_core.application.services.learner_memory.result_types import (
            ReflectionCorpusResult, ReflectionCorpusSummary,
        )
        knowledge_items: list[ReflectionCorpusMemoryItem] = []
        behavior_items: list[ReflectionCorpusMemoryItem] = []
        if self._knowledge_memory_repository is not None:
            knowledge_memories = await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id, learner_goal_id=learner_goal_id,
                statuses={"candidate", "active", "stable", "archived"},
            )
            knowledge_items = [
                await self._build_item("knowledge", m) for m in knowledge_memories
                if learner_goal_id is None or m.learner_goal_id == learner_goal_id
            ]
        if self._behavior_memory_repository is not None:
            behavior_memories = await self._behavior_memory_repository.list_by_profile(
                learner_profile_id, learner_goal_id=learner_goal_id,
                statuses={"candidate", "active", "stable", "archived"},
            )
            behavior_items = [
                await self._build_item("behavior", m) for m in behavior_memories
                if learner_goal_id is None or m.learner_goal_id == learner_goal_id
            ]
        ranked_knowledge = sorted(knowledge_items, key=lambda i: (i.reflection_priority_score, i.updated_at), reverse=True)[:limit_per_type]
        ranked_behavior = sorted(behavior_items, key=lambda i: (i.reflection_priority_score, i.updated_at), reverse=True)[:limit_per_type]
        merged_items = sorted(ranked_knowledge + ranked_behavior, key=lambda i: (i.reflection_priority_score, i.updated_at), reverse=True)
        summary = ReflectionCorpusSummary(
            total_items=len(merged_items), knowledge_items=len(ranked_knowledge), behavior_items=len(ranked_behavior),
            candidate_items=sum(1 for i in merged_items if i.status == "candidate"),
            stable_items=sum(1 for i in merged_items if i.status == "stable"),
            contradiction_focus_items=sum(1 for i in merged_items if i.recommended_action == "validate"),
            stale_focus_items=sum(1 for i in merged_items if i.recommended_action == "refresh"),
            validate_items=sum(1 for i in merged_items if i.recommended_action == "validate"),
            reinforce_items=sum(1 for i in merged_items if i.recommended_action == "reinforce"),
        )
        if self._audit_service is not None:
            await self._audit_service.record(
                event_type="memory.reflection_corpus.generated", resource_type="learner_profile",
                resource_id=learner_profile_id, actor="system",
                event_data={
                    "learner_profile_id": learner_profile_id, "learner_goal_id": learner_goal_id,
                    "limit_per_type": limit_per_type, "total_items": summary.total_items,
                    "knowledge_items": summary.knowledge_items, "behavior_items": summary.behavior_items,
                    "validate_items": summary.validate_items, "reinforce_items": summary.reinforce_items,
                },
            )
        return ReflectionCorpusResult(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            generated_at=datetime.now(timezone.utc), items=merged_items, summary=summary,
        )

    async def build_governance_summary(
        self, *, learner_profile_id: str, learner_goal_id: str | None = None,
    ) -> MemoryGovernanceSummary:
        from agent_core.application.services.learner_memory.result_types import MemoryGovernanceSummary
        from agent_core.domain.entities.memory import MEMORY_STATUSES
        knowledge = (
            await self._knowledge_memory_repository.list_by_profile(learner_profile_id, learner_goal_id=learner_goal_id, statuses=set(MEMORY_STATUSES))
            if self._knowledge_memory_repository is not None else []
        )
        behavior = (
            await self._behavior_memory_repository.list_by_profile(learner_profile_id, learner_goal_id=learner_goal_id, statuses=set(MEMORY_STATUSES))
            if self._behavior_memory_repository is not None else []
        )
        decisions = (
            await self._governance_decision_repository.list_by_profile(learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id, limit=100)
            if self._governance_decision_repository is not None else []
        )
        all_memories = [*knowledge, *behavior]
        evidence_links = (
            await self._evidence_link_repository.list_by_profile(learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id, limit=200)
            if self._evidence_link_repository is not None else []
        )
        quality_snapshots = [self._quality_snapshot_sync_fn(item) for item in all_memories] if self._quality_snapshot_sync_fn else [{} for _ in all_memories]
        return MemoryGovernanceSummary(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            knowledge_total=len(knowledge), behavior_total=len(behavior),
            candidate_total=sum(1 for i in all_memories if i.status == "candidate"),
            active_total=sum(1 for i in all_memories if i.status == "active"),
            stable_total=sum(1 for i in all_memories if i.status == "stable"),
            archived_total=sum(1 for i in all_memories if i.status == "archived"),
            suppressed_total=sum(1 for i in all_memories if i.status == "suppressed"),
            contradiction_focus_total=sum(1 for i in all_memories if i.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD),
            stale_candidate_total=sum(1 for i in all_memories if i.status == "candidate" and i.freshness_score < 0.35),
            high_priority_total=sum(1 for i in all_memories if reflection_priority_score(memory=i) >= 0.65),
            recent_promotions=sum(1 for i in decisions if i.decision_type == "promote"),
            recent_demotions=sum(1 for i in decisions if i.decision_type == "demote"),
            recent_archives=sum(1 for i in decisions if i.decision_type == "archive"),
            recent_compressions=sum(1 for i in decisions if i.decision_type == "compress"),
            promotion_candidate_total=self._count_promotion_candidates(knowledge, behavior),
            demotion_risk_total=sum(1 for i in all_memories if governance_pressure_val(i) >= 0.65),
            operator_review_recommended_total=sum(1 for i in all_memories if review_recommended_val(i)),
            reflection_bridge_total=sum(1 for i in evidence_links if i.evidence_source_type == "reflection_outcome"),
            high_quality_total=sum(1 for i in quality_snapshots if i.get("quality_tier") == "high"),
            medium_quality_total=sum(1 for i in quality_snapshots if i.get("quality_tier") == "medium"),
            ready_promotion_total=sum(1 for i in quality_snapshots if i.get("promotion_readiness") == "ready"),
            weak_candidate_total=sum(
                1 for m, s in zip(all_memories, quality_snapshots, strict=False)
                if m.status == "candidate" and s.get("quality_tier") == "low"
            ),
            quality_tier_totals={
                "low": sum(1 for i in quality_snapshots if i.get("quality_tier") == "low"),
                "medium": sum(1 for i in quality_snapshots if i.get("quality_tier") == "medium"),
                "high": sum(1 for i in quality_snapshots if i.get("quality_tier") == "high"),
            },
            topic_bucket_summary=topic_bucket_summary(all_memories),
        )

    def _count_promotion_candidates(self, knowledge: list, behavior: list) -> int:
        count = 0
        for m in knowledge:
            if m.status == "candidate":
                from agent_core.application.services.learner_memory.quality import knowledge_quality_score, knowledge_promotion_readiness
                qs = knowledge_quality_score(m)
                if knowledge_promotion_readiness(m, qs, self._governance_config) == "ready":
                    count += 1
        for m in behavior:
            if m.status == "candidate":
                from agent_core.application.services.learner_memory.quality import behavior_quality_score, behavior_promotion_readiness
                qs = behavior_quality_score(m)
                if behavior_promotion_readiness(m, qs, self._governance_config) == "ready":
                    count += 1
        return count

    async def _build_item(self, memory_type: str, memory: KnowledgeMemory | BehaviorMemory) -> ReflectionCorpusMemoryItem:
        from agent_core.application.services.learner_memory.result_types import ReflectionCorpusMemoryItem
        memory_key = getattr(memory, "knowledge_key", "") if memory_type == "knowledge" else getattr(memory, "behavior_key", "")
        memory_level = getattr(memory, "knowledge_level", "") if memory_type == "knowledge" else getattr(memory, "behavior_level", "")
        rps = reflection_priority_score(memory=memory)
        ra = reflection_recommended_action(memory=memory, reflection_priority_score=rps)
        gp = governance_pressure_val(memory)
        quality_snapshot = await self._quality_snapshot_fn(memory_type, memory) if self._quality_snapshot_fn else {"quality_score": 0, "quality_tier": "low", "promotion_readiness": "not_ready", "quality_reasons": [], "evidence_mix": {}}
        tas = self._topic_alignment_fn(memory_key, memory_key, title=memory.title, tags=memory.tags, extras=getattr(memory, "prerequisite_keys", None)) if self._topic_alignment_fn else 1.0
        return ReflectionCorpusMemoryItem(
            memory_type=memory_type, memory_id=memory.id, learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id, memory_key=memory_key, memory_level=memory_level,
            title=memory.title, summary=memory.summary, status=memory.status, time_horizon=memory.time_horizon,
            importance_score=memory.importance_score, confidence_score=memory.confidence_score,
            freshness_score=memory.freshness_score, stability_score=memory.stability_score,
            goal_relevance_score=memory.goal_relevance_score, support_score=memory.support_score,
            contradiction_score=memory.contradiction_score, evidence_count=memory.evidence_count,
            contradiction_count=memory.contradiction_count, reflection_priority_score=rps,
            recommended_action=ra,
            rationale=reflection_rationale(memory=memory, recommended_action=ra),
            recommended_action_reason=recommended_action_reason(memory=memory, recommended_action=ra),
            topic_alignment_score=tas, governance_pressure=gp,
            review_recommended=review_recommended_val(memory),
            quality_score=float(quality_snapshot.get("quality_score", 0)),
            quality_tier=str(quality_snapshot.get("quality_tier", "low")),
            promotion_readiness=str(quality_snapshot.get("promotion_readiness", "not_ready")),
            quality_reasons=list(quality_snapshot.get("quality_reasons", [])),
            evidence_mix=dict(quality_snapshot.get("evidence_mix", {})),
            semantic_category=memory.semantic_category, validation_status=memory.validation_status,
            provenance_type=memory.provenance_type, provenance_source_id=memory.provenance_source_id,
            scope_ref=dict(memory.scope_ref), promotion_rationale=memory.promotion_rationale,
            contested=memory.validation_status == "contested" or memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD,
            source_event_ids=list(memory.source_event_ids), source_memory_ids=list(memory.source_memory_ids),
            tags=list(memory.tags), created_at=memory.created_at, updated_at=memory.updated_at,
        )


def reflection_priority_score(*, memory: KnowledgeMemory | BehaviorMemory) -> float:
    from agent_core.application.services.learner_memory.quality import clamp_score
    contradiction_pressure = 1.0 - memory.contradiction_score
    freshness_pressure = 1.0 - memory.freshness_score
    evidence_pressure = clamp_score(memory.evidence_count / 6)
    stability_pressure = memory.stability_score
    status_bonus = {"candidate": 0.12, "active": 0.18, "stable": 0.14, "archived": 0.08, "compressed": 0.04, "suppressed": 0.0}.get(memory.status, 0.05)
    return clamp_score(
        0.25 * memory.importance_score + 0.15 * memory.confidence_score + 0.15 * memory.support_score
        + 0.15 * contradiction_pressure + 0.15 * freshness_pressure + 0.1 * evidence_pressure
        + 0.05 * stability_pressure + status_bonus
    )


def reflection_recommended_action(*, memory: KnowledgeMemory | BehaviorMemory, reflection_priority_score: float) -> str:
    if memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
        return "validate"
    if memory.freshness_score < 0.3 and memory.status in {"active", "stable"}:
        return "refresh"
    if memory.status == "candidate" and reflection_priority_score >= 0.55:
        return "reinforce"
    if memory.status == "stable" and memory.support_score >= 0.45:
        return "reinforce"
    if memory.status == "archived" and memory.importance_score >= 0.5:
        return "review"
    return "observe"


def reflection_rationale(*, memory: KnowledgeMemory | BehaviorMemory, recommended_action: str) -> str:
    return (
        f"status={memory.status}; support={memory.support_score:.2f}; "
        f"contradiction={memory.contradiction_score:.2f}; freshness={memory.freshness_score:.2f}; "
        f"stability={memory.stability_score:.2f}; action={recommended_action}"
    )


def recommended_action_reason(*, memory: KnowledgeMemory | BehaviorMemory, recommended_action: str) -> str:
    if recommended_action == "validate":
        return "contradiction_pressure"
    if recommended_action == "refresh":
        return "staleness_pressure"
    if recommended_action == "reinforce":
        return "promotion_candidate"
    if recommended_action == "review":
        return "archived_high_value"
    return "balanced"


def governance_pressure_val(memory: KnowledgeMemory | BehaviorMemory) -> float:
    from agent_core.application.services.learner_memory.quality import governance_pressure
    return governance_pressure(memory)


def review_recommended_val(memory: KnowledgeMemory | BehaviorMemory) -> bool:
    from agent_core.application.services.learner_memory.quality import review_recommended
    return review_recommended(memory)


def topic_bucket_summary(memories: list[KnowledgeMemory | BehaviorMemory]) -> list[dict[str, object]]:
    from agent_core.application.services.learner_memory.quality import review_recommended as _rr
    buckets: dict[str, dict[str, object]] = {}
    for memory in memories:
        topic_key = getattr(memory, "knowledge_key", "") or getattr(memory, "behavior_key", "")
        bucket = buckets.setdefault(topic_key, {"topic_key": topic_key, "memory_count": 0, "candidate_count": 0, "review_recommended": 0})
        bucket["memory_count"] = int(bucket["memory_count"]) + 1
        if memory.status == "candidate":
            bucket["candidate_count"] = int(bucket["candidate_count"]) + 1
        if _rr(memory):
            bucket["review_recommended"] = int(bucket["review_recommended"]) + 1
    return sorted(buckets.values(), key=lambda i: (int(i["review_recommended"]), int(i["memory_count"])), reverse=True)[:10]


def build_compressed_summary(*, prefix: str, titles: list[str], summaries: list[str]) -> str:
    title_snippet = "; ".join(titles[:3])
    summary_snippet = " / ".join(summary[:120] for summary in summaries[:3])
    return f"{prefix} cluster from {title_snippet}. {summary_snippet}"
