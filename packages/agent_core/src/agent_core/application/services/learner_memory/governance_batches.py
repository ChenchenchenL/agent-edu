"""Batch governance, compression, refresh, and promotion eligibility orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import TypeVar

from agent_core.application.services.memory_conflict_policy import CONFLICT_CONTRADICTION_THRESHOLD
from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.application.services.learner_memory.candidate_builders import (
    build_behavior_intervention_effect,
    topic_alignment_score,
)
from agent_core.application.services.learner_memory.constants import (
    BEHAVIOR_EVIDENCE_WEIGHTS,
    KNOWLEDGE_EVIDENCE_WEIGHTS,
    default_governance_config,
)
from agent_core.application.services.learner_memory.evidence import EvidenceService
from agent_core.application.services.learner_memory.governance import (
    GovernanceService,
    decision_type_for_transition,
    metrics_snapshot,
    promotion_rationale,
    validation_status_for_memory,
)
from agent_core.application.services.learner_memory.quality import (
    behavior_promotion_readiness,
    behavior_quality_score,
    clamp_score,
    knowledge_promotion_readiness,
    knowledge_quality_score,
    memory_quality_snapshot_sync,
)
from agent_core.application.services.learner_memory.reflection_corpus import build_compressed_summary
from agent_core.application.services.learner_memory.result_types import (
    MemoryMaintenanceBatchResult,
    MemoryMaintenanceResult,
)
from agent_core.application.services.learner_memory.upsert import (
    UpsertService,
    has_material_refresh_change,
    merge_behavior_memory as _merge_behavior_fn,
    merge_knowledge_memory as _merge_knowledge_fn,
)
from agent_core.domain.entities.autonomy import LearnerTopicMastery, TaskAttempt
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    BehaviorMemoryEmbeddingRecord,
    KnowledgeMemory,
    KnowledgeMemoryEmbeddingRecord,
    MemoryEvidenceLink,
    MemoryPromotionEligibilityRecord,
)
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.infrastructure.db.repositories import (
    BehaviorMemoryEmbeddingRepository,
    BehaviorMemoryRepository,
    KnowledgeMemoryEmbeddingRepository,
    KnowledgeMemoryRepository,
    MemoryConflictRepository,
    MemoryPromotionEligibilityRepository,
)
from agent_core.infrastructure.embedding.types import EmbeddingProvider
from agent_core.infrastructure.observability.metrics import (
    observe_memory_maintenance_run,
    observe_memory_promotion_eligibility,
    observe_memory_reflection_bridge,
)

MemoryRecordT = TypeVar("MemoryRecordT", KnowledgeMemory, BehaviorMemory)
MemoryEmbeddingRecordT = TypeVar(
    "MemoryEmbeddingRecordT",
    KnowledgeMemoryEmbeddingRecord,
    BehaviorMemoryEmbeddingRecord,
)
KnowledgeEligibilityMap = dict[str, MemoryPromotionEligibilityRecord]


def _merge_unique(items: list[list[str]]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in items:
        for item in group:
            if item in seen:
                continue
            seen.add(item)
            merged.append(item)
    return merged


def _select_highest_level(levels: list[str], *, ordered_levels: list[str]) -> str:
    order_map = {level: index for index, level in enumerate(ordered_levels)}
    return max(levels, key=lambda level: order_map.get(level, -1))


def _decay_freshness(current: float, updated_at: datetime, time_horizon: str, level: str) -> float:
    from agent_core.domain.entities.memory import BEHAVIOR_LEVELS
    days = max((datetime.now(timezone.utc) - updated_at).total_seconds() / 86400.0, 0.0)
    if time_horizon == "early":
        window = 14
    elif time_horizon == "mid":
        window = 45 if level not in BEHAVIOR_LEVELS else 21
    else:
        window = 120 if level not in BEHAVIOR_LEVELS else 60
    return max(0.0, min(current, 1.0 - min(days / max(window, 1), 1.0)))


def knowledge_governance_multiplier(
    *,
    memory: KnowledgeMemory,
    mastery: LearnerTopicMastery | None,
    attempts: list[TaskAttempt],
) -> float:
    multiplier = 1.0
    if mastery is not None and mastery.mastery_score >= 0.8 and mastery.confidence >= 0.7:
        multiplier += 0.08
    if len([item for item in attempts[:3] if item.outcome_status == "completed"]) >= 2:
        multiplier += 0.05
    if memory.goal_relevance_score < 0.35:
        multiplier -= 0.08
    if memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
        multiplier -= 0.12
    return max(0.8, min(multiplier, 1.2))


def behavior_governance_multiplier(
    *,
    memory: BehaviorMemory,
    attempts: list[TaskAttempt],
) -> float:
    multiplier = 1.0
    if memory.cross_session_recurrence_count >= 2:
        multiplier += 0.05
    if len([item for item in attempts[:3] if item.outcome_status in {"failed", "skipped"}]) >= 2:
        multiplier += 0.03
    if memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
        multiplier -= 0.1
    return max(0.82, min(multiplier, 1.15))


def summarize_governance_batch_change(
    previous: MemoryRecordT,
    refreshed: MemoryRecordT,
) -> tuple[int, int, int, int]:
    if refreshed.status != previous.status:
        if refreshed.status in {"active", "stable"} and previous.status in {"candidate", "active"}:
            return (1, 0, 0, 0)
        if refreshed.status == "suppressed":
            return (0, 0, 1, 0)
        if previous.status == "stable" and refreshed.status == "active":
            return (0, 1, 0, 0)
        return (0, 0, 0, 0)
    if has_material_refresh_change(previous, refreshed):
        return (0, 0, 0, 1)
    return (0, 0, 0, 0)


def build_compressed_knowledge_memory(memories: list[KnowledgeMemory]) -> KnowledgeMemory:
    merged_source_event_ids = _merge_unique([item.source_event_ids for item in memories])
    merged_source_memory_ids = _merge_unique([[item.id] + item.source_memory_ids for item in memories])
    prerequisite_keys = _merge_unique([item.prerequisite_keys for item in memories])
    compressed = KnowledgeMemory.build(
        learner_profile_id=memories[0].learner_profile_id,
        learner_goal_id=memories[0].learner_goal_id,
        knowledge_key=memories[0].knowledge_key,
        title=f"Compressed knowledge: {memories[0].title}",
        summary=build_compressed_summary(
            prefix="Knowledge",
            titles=[item.title for item in memories],
            summaries=[item.summary for item in memories],
        ),
        details=f"Compressed from {len(memories)} knowledge memories.",
        knowledge_level=_select_highest_level(
            [item.knowledge_level for item in memories],
            ordered_levels=["foundation", "core", "advanced", "application"],
        ),
        time_horizon="long",
        importance_score=clamp_score(max(item.importance_score for item in memories)),
        confidence_score=clamp_score(sum(item.confidence_score for item in memories) / len(memories)),
        freshness_score=1.0,
        prerequisite_keys=prerequisite_keys,
        source_event_ids=merged_source_event_ids,
        source_memory_ids=merged_source_memory_ids,
        tags=_merge_unique([item.tags for item in memories]) + ["compressed"],
    )
    return compressed.with_status(
        "active",
        stability_score=max(item.stability_score for item in memories),
        goal_relevance_score=max(item.goal_relevance_score for item in memories),
        evidence_count=sum(item.evidence_count for item in memories),
        contradiction_count=sum(item.contradiction_count for item in memories),
        support_score=max(item.support_score for item in memories),
        contradiction_score=max(item.contradiction_score for item in memories),
        assessment_evidence_count=sum(item.assessment_evidence_count for item in memories),
        task_evidence_count=sum(item.task_evidence_count for item in memories),
    )


def build_compressed_behavior_memory(memories: list[BehaviorMemory]) -> BehaviorMemory:
    merged_source_event_ids = _merge_unique([item.source_event_ids for item in memories])
    merged_source_memory_ids = _merge_unique([[item.id] + item.source_memory_ids for item in memories])
    compressed = BehaviorMemory.build(
        learner_profile_id=memories[0].learner_profile_id,
        learner_goal_id=memories[0].learner_goal_id,
        behavior_key=memories[0].behavior_key,
        behavior_category=memories[0].behavior_category,
        title=f"Compressed behavior: {memories[0].title}",
        summary=build_compressed_summary(
            prefix="Behavior",
            titles=[item.title for item in memories],
            summaries=[item.summary for item in memories],
        ),
        details=f"Compressed from {len(memories)} behavior memories.",
        behavior_level=_select_highest_level(
            [item.behavior_level for item in memories],
            ordered_levels=["surface", "recurrent", "persistent", "critical"],
        ),
        time_horizon="long",
        importance_score=clamp_score(max(item.importance_score for item in memories)),
        confidence_score=clamp_score(sum(item.confidence_score for item in memories) / len(memories)),
        freshness_score=1.0,
        source_event_ids=merged_source_event_ids,
        source_memory_ids=merged_source_memory_ids,
        tags=_merge_unique([item.tags for item in memories]) + ["compressed"],
        intervention_effect=build_behavior_intervention_effect(
            mode="chat",
            progress_note="Compressed from repeated learner behavior patterns.",
            struggle_note="Repeated behavior pattern aggregated.",
        ),
    )
    return compressed.with_status(
        "active",
        stability_score=max(item.stability_score for item in memories),
        goal_relevance_score=max(item.goal_relevance_score for item in memories),
        evidence_count=sum(item.evidence_count for item in memories),
        contradiction_count=sum(item.contradiction_count for item in memories),
        support_score=max(item.support_score for item in memories),
        contradiction_score=max(item.contradiction_score for item in memories),
        intervention_success_count=sum(item.intervention_success_count for item in memories),
        intervention_failure_count=sum(item.intervention_failure_count for item in memories),
        cross_session_recurrence_count=max(item.cross_session_recurrence_count for item in memories),
    )


def cluster_knowledge_memories(memories: list[KnowledgeMemory]) -> list[list[KnowledgeMemory]]:
    grouped: dict[tuple[str, str], list[KnowledgeMemory]] = {}
    for memory in memories:
        grouped.setdefault((memory.scope_type, memory.knowledge_key), []).append(memory)
    return [group for group in grouped.values() if len(group) > 1]


def cluster_behavior_memories(memories: list[BehaviorMemory]) -> list[list[BehaviorMemory]]:
    grouped: dict[tuple[str, str], list[BehaviorMemory]] = {}
    for memory in memories:
        grouped.setdefault((memory.scope_type, memory.behavior_key), []).append(memory)
    return [group for group in grouped.values() if len(group) > 1]


def topic_key_from_reflection(reflection: ReflectionRecord) -> str | None:
    task = reflection.evidence_payload.get("task") or {}
    workflow = reflection.evidence_payload.get("workflow") or {}
    topic_key = str(task.get("topic_focus") or workflow.get("topic_focus") or "").strip()
    return topic_key or None


class GovernanceBatchService:
    """Orchestrates batch governance, compression, refresh, and promotion eligibility."""

    def __init__(
        self,
        *,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        knowledge_memory_embedding_repository: KnowledgeMemoryEmbeddingRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        behavior_memory_embedding_repository: BehaviorMemoryEmbeddingRepository | None = None,
        conflict_repository: MemoryConflictRepository | None = None,
        promotion_eligibility_repository: MemoryPromotionEligibilityRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        evidence_service: EvidenceService | None = None,
        governance_service: GovernanceService | None = None,
        upsert_service: UpsertService | None = None,
        refresh_observability_metrics: object = None,
        governance_config: dict[str, float | int] | None = None,
    ) -> None:
        self._knowledge_memory_repository = knowledge_memory_repository
        self._knowledge_memory_embedding_repository = knowledge_memory_embedding_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._behavior_memory_embedding_repository = behavior_memory_embedding_repository
        self._conflict_repository = conflict_repository
        self._promotion_eligibility_repository = promotion_eligibility_repository
        self._embedding_provider = embedding_provider
        self._evidence_service = evidence_service
        self._governance_service = governance_service
        self._upsert_service = upsert_service
        self._refresh_observability_metrics = refresh_observability_metrics
        self._governance_config = governance_config or default_governance_config()

    async def run_memory_maintenance(
        self,
        *,
        batch_size: int = 5,
        refresh_conflict_sets: object = None,
        compress_knowledge: object = None,
        compress_behavior: object = None,
    ) -> MemoryMaintenanceResult:
        started_at = perf_counter()
        promoted_knowledge, demoted_knowledge = await self._refresh_and_govern_knowledge()
        promoted_behavior, demoted_behavior = await self._refresh_and_govern_behavior()
        if refresh_conflict_sets is not None:
            await refresh_conflict_sets()
        compressed_knowledge_groups = await self.compress_knowledge_memories(batch_size=batch_size)
        compressed_behavior_groups = await self.compress_behavior_memories(batch_size=batch_size)
        if self._refresh_observability_metrics is not None:
            await self._refresh_observability_metrics()
        observe_memory_maintenance_run(duration_seconds=perf_counter() - started_at)
        return MemoryMaintenanceResult(
            compressed_knowledge_groups=compressed_knowledge_groups,
            compressed_behavior_groups=compressed_behavior_groups,
            promoted_knowledge=promoted_knowledge,
            promoted_behavior=promoted_behavior,
            demoted_knowledge=demoted_knowledge,
            demoted_behavior=demoted_behavior,
        )

    async def list_maintenance_profile_ids(self) -> list[str]:
        profile_ids: set[str] = set()
        current_statuses = {"candidate", "active", "stable"}
        if self._knowledge_memory_repository is not None:
            profile_ids.update(
                await self._knowledge_memory_repository.list_profile_ids_with_statuses(current_statuses)
            )
        if self._behavior_memory_repository is not None:
            profile_ids.update(
                await self._behavior_memory_repository.list_profile_ids_with_statuses(current_statuses)
            )
        if self._conflict_repository is not None and hasattr(self._conflict_repository, "list_profile_ids_with_open_sets"):
            profile_ids.update(await self._conflict_repository.list_profile_ids_with_open_sets())
        return sorted(profile_ids)

    async def _run_governance_batch(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
        list_batch: Callable[[str, str | None, int], Awaitable[list[MemoryRecordT]]],
        refresh_memory: Callable[[MemoryRecordT], Awaitable[MemoryRecordT]],
    ) -> MemoryMaintenanceBatchResult:
        normalized_batch_size = max(batch_size, 1)
        fetched = await list_batch(learner_profile_id, cursor, normalized_batch_size + 1)
        batch = fetched[:normalized_batch_size]
        promoted = 0
        demoted = 0
        suppressed = 0
        refreshed_count = 0
        for memory in batch:
            refreshed = await refresh_memory(memory)
            promoted_delta, demoted_delta, suppressed_delta, refreshed_delta = summarize_governance_batch_change(memory, refreshed)
            promoted += promoted_delta
            demoted += demoted_delta
            suppressed += suppressed_delta
            refreshed_count += refreshed_delta
        next_cursor = batch[-1].id if batch else cursor
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=promoted + demoted + suppressed + refreshed_count,
            next_cursor=next_cursor,
            completed=len(fetched) <= normalized_batch_size,
            metadata={
                "promoted": promoted,
                "demoted": demoted,
                "suppressed": suppressed,
                "refreshed": refreshed_count,
            },
        )

    async def _refresh_and_govern_memories(
        self,
        *,
        list_profile_ids: Callable[[], Awaitable[list[str]]],
        list_memories: Callable[[str], Awaitable[list[MemoryRecordT]]],
        refresh_memory: Callable[[MemoryRecordT], Awaitable[MemoryRecordT]],
    ) -> tuple[int, int]:
        promoted = 0
        demoted = 0
        for profile_id in await list_profile_ids():
            memories = await list_memories(profile_id)
            for memory in memories:
                refreshed = await refresh_memory(memory)
                promoted_delta, demoted_delta, _, _ = summarize_governance_batch_change(memory, refreshed)
                promoted += promoted_delta
                demoted += demoted_delta
        return (promoted, demoted)

    async def _refresh_and_govern_knowledge(self) -> tuple[int, int]:
        repository = self._knowledge_memory_repository
        if repository is None:
            return (0, 0)
        return await self._refresh_and_govern_memories(
            list_profile_ids=lambda: repository.list_profile_ids_with_statuses({"candidate", "active", "stable"}),
            list_memories=lambda profile_id: repository.list_by_profile(
                profile_id,
                statuses={"candidate", "active", "stable"},
            ),
            refresh_memory=self.refresh_knowledge_memory,
        )

    async def _refresh_and_govern_behavior(self) -> tuple[int, int]:
        repository = self._behavior_memory_repository
        if repository is None:
            return (0, 0)
        return await self._refresh_and_govern_memories(
            list_profile_ids=lambda: repository.list_profile_ids_with_statuses({"candidate", "active", "stable"}),
            list_memories=lambda profile_id: repository.list_by_profile(
                profile_id,
                statuses={"candidate", "active", "stable"},
            ),
            refresh_memory=self.refresh_behavior_memory,
        )

    async def refresh_knowledge_memory(
        self,
        memory: KnowledgeMemory,
        *,
        eligibility: MemoryPromotionEligibilityRecord | None = None,
        eligibility_prefetched: bool = False,
    ) -> KnowledgeMemory:
        if self._evidence_service is None:
            return memory
        attempts = await self._evidence_service.list_relevant_attempts(memory.learner_goal_id, memory.knowledge_key)
        mastery = await self._evidence_service.get_relevant_mastery(memory.learner_goal_id, memory.knowledge_key)
        events = await self._evidence_service.list_relevant_events(memory.learner_profile_id, memory.knowledge_key)
        await self._evidence_service.sync_knowledge_evidence_links(memory=memory, attempts=attempts, mastery=mastery, events=events)
        support_score, contradiction_score, evidence_count, contradiction_count, assessment_count, task_count = (
            self._evidence_service.compute_knowledge_evidence(memory, attempts, mastery, events)
        )
        refreshed_importance = EvidenceService.adjust_knowledge_importance(
            memory=memory, support_score=support_score, contradiction_score=contradiction_score, assessment_count=assessment_count,
        )
        refreshed_confidence = EvidenceService.adjust_knowledge_confidence(
            memory=memory, evidence_count=evidence_count, contradiction_count=contradiction_count, mastery=mastery,
        )
        multiplier = knowledge_governance_multiplier(memory=memory, mastery=mastery, attempts=attempts)
        refreshed_importance = clamp_score(refreshed_importance * multiplier)
        refreshed_confidence = clamp_score(refreshed_confidence * multiplier)
        stability_score = EvidenceService.compute_knowledge_stability(
            confidence_score=refreshed_confidence, support_score=support_score, contradiction_score=contradiction_score,
            freshness_score=memory.freshness_score, goal_relevance_score=memory.goal_relevance_score, assessment_count=assessment_count,
        )
        refreshed = memory.with_status(
            memory.status,
            support_score=support_score, contradiction_score=contradiction_score,
            evidence_count=evidence_count, contradiction_count=contradiction_count,
            stability_score=stability_score, assessment_evidence_count=assessment_count, task_evidence_count=task_count,
            importance_score=refreshed_importance, confidence_score=refreshed_confidence,
            last_reviewed_at=datetime.now(timezone.utc),
            last_supported_at=datetime.now(timezone.utc) if evidence_count > 0 else memory.last_supported_at,
            last_contradicted_at=datetime.now(timezone.utc) if contradiction_count > 0 else memory.last_contradicted_at,
            freshness_score=_decay_freshness(memory.freshness_score, memory.updated_at, memory.time_horizon, memory.knowledge_level),
            validation_status=validation_status_for_memory(
                contradiction_score=contradiction_score, freshness_score=memory.freshness_score,
                evidence_count=evidence_count, support_score=support_score, scope_type=memory.scope_type,
            ),
        )
        if self._governance_service is None:
            return refreshed
        next_status = await self._governance_service.govern_knowledge_status(
            refreshed, eligibility=eligibility, eligibility_prefetched=eligibility_prefetched,
        )
        if next_status != refreshed.status:
            updated = await self._governance_service.apply_knowledge_status_transition(
                original=memory, refreshed=refreshed, next_status=next_status,
                eligibility=eligibility, eligibility_prefetched=eligibility_prefetched,
            )
            return updated
        if self._knowledge_memory_repository is not None:
            await self._knowledge_memory_repository.update(refreshed)
        if self._upsert_service is not None:
            await self._upsert_service.sync_knowledge_embedding(refreshed)
        if has_material_refresh_change(memory, refreshed) and self._governance_service is not None:
            await self._governance_service.record_governance_decision(
                memory_type="knowledge", memory_id=refreshed.id,
                previous_status=memory.status, new_status=refreshed.status,
                decision_type="refresh",
                trigger_source="evidence_refresh" if refreshed.evidence_count > 0 or refreshed.contradiction_count > 0 else "decay_cycle",
                actor_type="system", actor_id="worker",
                reason_code="knowledge_governance_refresh", reason_note=None,
                metrics_snapshot=metrics_snapshot(memory=refreshed),
            )
        return refreshed

    async def refresh_behavior_memory(self, memory: BehaviorMemory) -> BehaviorMemory:
        if self._evidence_service is None:
            return memory
        attempts = await self._evidence_service.list_relevant_attempts(memory.learner_goal_id, memory.behavior_key)
        events = await self._evidence_service.list_relevant_events(memory.learner_profile_id, memory.behavior_key)
        await self._evidence_service.sync_behavior_evidence_links(memory=memory, attempts=attempts, events=events)
        support_score, contradiction_score, evidence_count, contradiction_count, recurrence_count = (
            self._evidence_service.compute_behavior_evidence(memory, attempts, events)
        )
        refreshed_importance = EvidenceService.adjust_behavior_importance(
            memory=memory, support_score=support_score, contradiction_score=contradiction_score, recurrence_count=recurrence_count,
        )
        refreshed_confidence = EvidenceService.adjust_behavior_confidence(
            memory=memory, evidence_count=evidence_count, contradiction_count=contradiction_count, recurrence_count=recurrence_count,
        )
        multiplier = behavior_governance_multiplier(memory=memory, attempts=attempts)
        refreshed_importance = clamp_score(refreshed_importance * multiplier)
        refreshed_confidence = clamp_score(refreshed_confidence * multiplier)
        stability_score = EvidenceService.compute_behavior_stability(
            confidence_score=refreshed_confidence, support_score=support_score, contradiction_score=contradiction_score,
            freshness_score=memory.freshness_score, goal_relevance_score=memory.goal_relevance_score,
            recurrence_count=recurrence_count,
            intervention_success_count=memory.intervention_success_count,
            intervention_failure_count=memory.intervention_failure_count,
        )
        refreshed = memory.with_status(
            memory.status,
            support_score=support_score, contradiction_score=contradiction_score,
            evidence_count=evidence_count, contradiction_count=contradiction_count,
            stability_score=stability_score, cross_session_recurrence_count=recurrence_count,
            importance_score=refreshed_importance, confidence_score=refreshed_confidence,
            last_reviewed_at=datetime.now(timezone.utc),
            last_supported_at=datetime.now(timezone.utc) if evidence_count > 0 else memory.last_supported_at,
            last_contradicted_at=datetime.now(timezone.utc) if contradiction_count > 0 else memory.last_contradicted_at,
            freshness_score=_decay_freshness(memory.freshness_score, memory.updated_at, memory.time_horizon, memory.behavior_level),
            validation_status=validation_status_for_memory(
                contradiction_score=contradiction_score, freshness_score=memory.freshness_score,
                evidence_count=evidence_count, support_score=support_score, scope_type=memory.scope_type,
            ),
        )
        if self._governance_service is None:
            return refreshed
        next_status = self._governance_service.govern_behavior_status(refreshed)
        if next_status != refreshed.status:
            updated = refreshed.with_status(
                next_status,
                promotion_state_changed_at=datetime.now(timezone.utc),
                promotion_rationale=promotion_rationale(updated_status=next_status, memory=refreshed),
            )
            if self._behavior_memory_repository is not None:
                await self._behavior_memory_repository.update(updated)
            if self._upsert_service is not None:
                await self._upsert_service.sync_behavior_embedding(updated)
            await self._governance_service.record_governance_decision(
                memory_type="behavior", memory_id=updated.id,
                previous_status=memory.status, new_status=updated.status,
                decision_type=decision_type_for_transition(memory.status, updated.status),
                trigger_source="promotion_cycle" if updated.status in {"active", "stable"} else "decay_cycle",
                actor_type="system", actor_id="worker",
                reason_code="behavior_governance_cycle", reason_note=None,
                metrics_snapshot=metrics_snapshot(memory=updated),
            )
            return updated
        if self._behavior_memory_repository is not None:
            await self._behavior_memory_repository.update(refreshed)
        if self._upsert_service is not None:
            await self._upsert_service.sync_behavior_embedding(refreshed)
        if has_material_refresh_change(memory, refreshed):
            await self._governance_service.record_governance_decision(
                memory_type="behavior", memory_id=refreshed.id,
                previous_status=memory.status, new_status=refreshed.status,
                decision_type="refresh",
                trigger_source="evidence_refresh" if refreshed.evidence_count > 0 or refreshed.contradiction_count > 0 else "decay_cycle",
                actor_type="system", actor_id="worker",
                reason_code="behavior_governance_refresh", reason_note=None,
                metrics_snapshot=metrics_snapshot(memory=refreshed),
            )
        return refreshed

    async def run_knowledge_governance_batch(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        repository = self._knowledge_memory_repository
        if repository is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        normalized_batch_size = max(batch_size, 1)
        fetched = await repository.list_by_profile_after_id(
            learner_profile_id=learner_profile_id,
            statuses={"candidate", "active", "stable"},
            after_id=cursor, limit=normalized_batch_size + 1,
        )
        batch = fetched[:normalized_batch_size]
        eligibility_by_memory_id: KnowledgeEligibilityMap = {}
        if self._promotion_eligibility_repository is not None and batch:
            eligibility_by_memory_id = await self._promotion_eligibility_repository.list_current_by_memory_ids(
                memory_ids=[memory.id for memory in batch if memory.status == "candidate"],
            )
        promoted = demoted = suppressed = refreshed_count = 0
        for memory in batch:
            refreshed = await self.refresh_knowledge_memory(
                memory, eligibility=eligibility_by_memory_id.get(memory.id), eligibility_prefetched=True,
            )
            p, d, s, r = summarize_governance_batch_change(memory, refreshed)
            promoted += p; demoted += d; suppressed += s; refreshed_count += r
        next_cursor = batch[-1].id if batch else cursor
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=promoted + demoted + suppressed + refreshed_count,
            next_cursor=next_cursor,
            completed=len(fetched) <= normalized_batch_size,
            metadata={"promoted": promoted, "demoted": demoted, "suppressed": suppressed, "refreshed": refreshed_count},
        )

    async def run_behavior_governance_batch(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        repository = self._behavior_memory_repository
        if repository is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        return await self._run_governance_batch(
            learner_profile_id=learner_profile_id, cursor=cursor, batch_size=batch_size,
            list_batch=lambda profile_id, after_id, limit: repository.list_by_profile_after_id(
                learner_profile_id=profile_id, statuses={"candidate", "active", "stable"}, after_id=after_id, limit=limit,
            ),
            refresh_memory=self.refresh_behavior_memory,
        )

    async def run_knowledge_promotion_eligibility_batch(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        if self._knowledge_memory_repository is None or self._promotion_eligibility_repository is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        fetched = await self._knowledge_memory_repository.list_by_profile_after_id(
            learner_profile_id=learner_profile_id, statuses={"candidate"},
            after_id=cursor, limit=max(batch_size, 1) + 1,
        )
        batch = fetched[: max(batch_size, 1)]
        changed_count = 0
        for memory in batch:
            record = await self._evaluate_knowledge_promotion_eligibility(memory)
            changed_count += 1 if record is not None else 0
        next_cursor = batch[-1].id if batch else cursor
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch), changed_count=changed_count,
            next_cursor=next_cursor, completed=len(fetched) <= max(batch_size, 1),
            metadata={"evaluated": changed_count},
        )

    async def _evaluate_knowledge_promotion_eligibility(
        self, memory: KnowledgeMemory,
    ) -> MemoryPromotionEligibilityRecord | None:
        if self._promotion_eligibility_repository is None or self._knowledge_memory_repository is None:
            return None
        reasons: list[str] = []
        if memory.status == "suppressed":
            reasons.append("suppressed_blocked")
            record = MemoryPromotionEligibilityRecord.build(
                memory_id=memory.id, learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id, status="suppressed_blocked", score=0.0,
                independent_source_count=0, high_signal_source_count=0, evidence_span_hours=0.0,
                conflict_blocked=False, blocked_conflict_set_id=None, blocked_memory_id=None,
                reason_codes=reasons,
                metrics_snapshot={"quality_score": knowledge_quality_score(memory)},
                evaluated_at=datetime.now(timezone.utc),
            )
            await self._promotion_eligibility_repository.upsert_current(record)
            observe_memory_promotion_eligibility(memory_type="knowledge", status="suppressed_blocked")
            return record
        links = await self._evidence_service.list_evidence_links(memory_type="knowledge", memory_id=memory.id) if self._evidence_service else []
        independent_sources = {(item.evidence_source_type, item.evidence_source_id) for item in links}
        high_signal_sources = [
            item for item in links
            if (item.evidence_source_type == "task_attempt" and str(item.payload.get("task_type")) in {"assessment", "quiz", "test"})
            or item.evidence_source_type == "reflection_outcome"
        ]
        observed_times = sorted(item.observed_at for item in links)
        span_hours = 0.0
        if len(observed_times) >= 2:
            span_hours = max((observed_times[-1] - observed_times[0]).total_seconds() / 3600.0, 0.0)
        evidence_strength = clamp_score(
            (len(independent_sources) / max(int(self._governance_config.get("promotion_eligibility_independent_source_min", 3)), 1)) * 0.5
            + (min(len(high_signal_sources), 2) / 2.0) * 0.3
            + min(span_hours / max(float(self._governance_config.get("promotion_eligibility_span_hours_min", 24.0)), 1.0), 1.0) * 0.2
        )
        score = clamp_score(0.35 * evidence_strength + 0.30 * memory.confidence_score + 0.20 * memory.freshness_score + 0.15 * memory.stability_score)
        conflict_memory = await self._knowledge_memory_repository.get_active_or_stable_conflict(
            learner_profile_id=memory.learner_profile_id, learner_goal_id=memory.learner_goal_id,
            knowledge_key=memory.knowledge_key, exclude_memory_id=memory.id,
        )
        if len(independent_sources) < int(self._governance_config.get("promotion_eligibility_independent_source_min", 3)):
            reasons.append("independent_source_count_below_min")
        if len(high_signal_sources) < int(self._governance_config.get("promotion_eligibility_high_signal_min", 1)):
            reasons.append("high_signal_count_below_min")
        if span_hours < float(self._governance_config.get("promotion_eligibility_span_hours_min", 24.0)):
            reasons.append("evidence_span_below_min")
        if score < float(self._governance_config.get("promotion_eligibility_score_min", 0.75)):
            reasons.append("score_below_min")
        if conflict_memory is not None:
            reasons.append("active_or_stable_conflict_exists")
        if conflict_memory is not None:
            status = "conflict_blocked"
        elif any(code in reasons for code in {"independent_source_count_below_min", "high_signal_count_below_min", "evidence_span_below_min"}):
            status = "insufficient_evidence"
        elif "score_below_min" in reasons:
            status = "below_score"
        else:
            status = "eligible"
        record = MemoryPromotionEligibilityRecord.build(
            memory_id=memory.id, learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id, status=status, score=score,
            independent_source_count=len(independent_sources), high_signal_source_count=len(high_signal_sources),
            evidence_span_hours=span_hours, conflict_blocked=conflict_memory is not None,
            blocked_conflict_set_id=None, blocked_memory_id=conflict_memory.id if conflict_memory is not None else None,
            reason_codes=reasons or [status],
            metrics_snapshot={
                "quality_score": knowledge_quality_score(memory),
                "confidence_score": memory.confidence_score,
                "freshness_score": memory.freshness_score,
                "stability_score": memory.stability_score,
                "evidence_strength": evidence_strength,
            },
            evaluated_at=datetime.now(timezone.utc),
        )
        await self._promotion_eligibility_repository.upsert_current(record)
        observe_memory_promotion_eligibility(memory_type="knowledge", status=status)
        return record

    async def _compress_memories_for_profile(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
        list_active_memories: Callable[[str], Awaitable[list[MemoryRecordT]]],
        list_embeddings_by_memory_ids: Callable[[str, list[str]], Awaitable[list[MemoryEmbeddingRecordT]]],
        cluster_memories: Callable[[list[MemoryRecordT]], list[list[MemoryRecordT]]],
        compress_group: Callable[[list[MemoryRecordT], dict[str, MemoryEmbeddingRecordT]], Awaitable[int]],
    ) -> MemoryMaintenanceBatchResult:
        active_memories = await list_active_memories(learner_profile_id)
        groups = sorted(cluster_memories(active_memories), key=lambda group: min(item.id for item in group))
        groups = [group for group in groups if cursor is None or min(item.id for item in group) > cursor]
        normalized_batch_size = max(batch_size, 1)
        batch = groups[:normalized_batch_size]
        source_groups = [
            sorted(sorted(group, key=lambda item: item.id)[: max(batch_size, 2)], key=lambda item: (item.importance_score, item.updated_at), reverse=True)
            for group in batch
        ]
        batch_memory_ids = sorted({memory.id for group in source_groups for memory in group})
        embeddings = await list_embeddings_by_memory_ids(learner_profile_id, batch_memory_ids)
        embeddings_by_memory_id = {item.memory_id: item for item in embeddings}
        compressed_groups = 0
        next_cursor = cursor
        for group, source_group in zip(batch, source_groups):
            next_cursor = min(item.id for item in group)
            compressed_groups += await compress_group(source_group, embeddings_by_memory_id)
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch), changed_count=compressed_groups, next_cursor=next_cursor,
            completed=len(groups) <= normalized_batch_size, metadata={"compressed_groups": compressed_groups},
        )

    async def _compress_memories(
        self, *, batch_size: int,
        list_profile_ids: Callable[[], Awaitable[list[str]]],
        list_active_memories: Callable[[str], Awaitable[list[MemoryRecordT]]],
        list_embeddings_by_memory_ids: Callable[[str, list[str]], Awaitable[list[MemoryEmbeddingRecordT]]],
        cluster_memories: Callable[[list[MemoryRecordT]], list[list[MemoryRecordT]]],
        compress_group: Callable[[list[MemoryRecordT], dict[str, MemoryEmbeddingRecordT]], Awaitable[int]],
    ) -> int:
        compressed_groups = 0
        for learner_profile_id in await list_profile_ids():
            active_memories = await list_active_memories(learner_profile_id)
            if len(active_memories) < 2:
                continue
            for group in cluster_memories(active_memories):
                if len(group) < 2:
                    continue
                sorted_group = sorted(group, key=lambda item: (item.importance_score, item.updated_at), reverse=True)[:batch_size]
                embeddings = await list_embeddings_by_memory_ids(learner_profile_id, [memory.id for memory in sorted_group])
                embeddings_by_memory_id = {item.memory_id: item for item in embeddings}
                compressed_groups += await compress_group(sorted_group, embeddings_by_memory_id)
        return compressed_groups

    async def compress_knowledge_memories_for_profile(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        repository = self._knowledge_memory_repository
        embedding_repository = self._knowledge_memory_embedding_repository
        if repository is None or embedding_repository is None or self._embedding_provider is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        return await self._compress_memories_for_profile(
            learner_profile_id=learner_profile_id, cursor=cursor, batch_size=batch_size,
            list_active_memories=lambda profile_id: repository.list_by_profile(profile_id, statuses={"active", "stable"}),
            list_embeddings_by_memory_ids=lambda profile_id, memory_ids: embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ) if hasattr(embedding_repository, 'list_by_memory_ids') else embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ),
            cluster_memories=cluster_knowledge_memories,
            compress_group=lambda group, embeddings_by_memory_id: self._compress_knowledge_group(group, embeddings_by_memory_id=embeddings_by_memory_id),
        )

    async def compress_behavior_memories_for_profile(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        repository = self._behavior_memory_repository
        embedding_repository = self._behavior_memory_embedding_repository
        if repository is None or embedding_repository is None or self._embedding_provider is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        return await self._compress_memories_for_profile(
            learner_profile_id=learner_profile_id, cursor=cursor, batch_size=batch_size,
            list_active_memories=lambda profile_id: repository.list_by_profile(profile_id, statuses={"active", "stable"}),
            list_embeddings_by_memory_ids=lambda profile_id, memory_ids: embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ) if hasattr(embedding_repository, 'list_by_memory_ids') else embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ),
            cluster_memories=cluster_behavior_memories,
            compress_group=lambda group, embeddings_by_memory_id: self._compress_behavior_group(group, embeddings_by_memory_id=embeddings_by_memory_id),
        )

    async def compress_knowledge_memories(self, *, batch_size: int = 5) -> int:
        repository = self._knowledge_memory_repository
        embedding_repository = self._knowledge_memory_embedding_repository
        if repository is None or embedding_repository is None or self._embedding_provider is None:
            return 0
        return await self._compress_memories(
            batch_size=batch_size,
            list_profile_ids=repository.list_profile_ids_with_active_memories,
            list_active_memories=lambda profile_id: repository.list_by_profile(profile_id, statuses={"active", "stable"}),
            list_embeddings_by_memory_ids=lambda profile_id, memory_ids: embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ) if hasattr(embedding_repository, 'list_by_memory_ids') else embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ),
            cluster_memories=cluster_knowledge_memories,
            compress_group=lambda group, embeddings_by_memory_id: self._compress_knowledge_group(group, embeddings_by_memory_id=embeddings_by_memory_id),
        )

    async def compress_behavior_memories(self, *, batch_size: int = 5) -> int:
        repository = self._behavior_memory_repository
        embedding_repository = self._behavior_memory_embedding_repository
        if repository is None or embedding_repository is None or self._embedding_provider is None:
            return 0
        return await self._compress_memories(
            batch_size=batch_size,
            list_profile_ids=repository.list_profile_ids_with_active_memories,
            list_active_memories=lambda profile_id: repository.list_by_profile(profile_id, statuses={"active", "stable"}),
            list_embeddings_by_memory_ids=lambda profile_id, memory_ids: embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ) if hasattr(embedding_repository, 'list_by_memory_ids') else embedding_repository.list_by_memory_ids(
                learner_profile_id=profile_id, memory_ids=memory_ids, statuses={"active", "stable"},
            ),
            cluster_memories=cluster_behavior_memories,
            compress_group=lambda group, embeddings_by_memory_id: self._compress_behavior_group(group, embeddings_by_memory_id=embeddings_by_memory_id),
        )

    async def _compress_knowledge_group(
        self, group: list[KnowledgeMemory], *, embeddings_by_memory_id: dict[str, KnowledgeMemoryEmbeddingRecord],
    ) -> int:
        if (len(group) < 2 or self._knowledge_memory_repository is None
                or self._knowledge_memory_embedding_repository is None or self._embedding_provider is None):
            return 0
        compressed = build_compressed_knowledge_memory(group)
        compressed_vector = (await self._embedding_provider.embed_texts([compressed.summary]))[0]
        await self._knowledge_memory_repository.create(compressed.with_status("compressed"))
        for source in group:
            await self._knowledge_memory_repository.update(source.with_compression(compressed_into_id=compressed.id))
            source_embedding = embeddings_by_memory_id.get(source.id)
            if source_embedding is not None:
                await self._knowledge_memory_embedding_repository.update(
                    KnowledgeMemoryEmbeddingRecord(
                        id=source_embedding.id, memory_id=source_embedding.memory_id,
                        learner_profile_id=source_embedding.learner_profile_id,
                        learner_goal_id=source_embedding.learner_goal_id,
                        knowledge_key=source_embedding.knowledge_key, title=source_embedding.title,
                        summary=source_embedding.summary, knowledge_level=source_embedding.knowledge_level,
                        time_horizon=source_embedding.time_horizon, importance_score=source_embedding.importance_score,
                        confidence_score=source_embedding.confidence_score, freshness_score=source_embedding.freshness_score,
                        stability_score=source_embedding.stability_score, goal_relevance_score=source_embedding.goal_relevance_score,
                        scope_type=source_embedding.scope_type, provider=source_embedding.provider,
                        model=source_embedding.model, dimensions=source_embedding.dimensions,
                        vector=source_embedding.vector, status="compressed", created_at=source_embedding.created_at,
                    )
                )
        await self._knowledge_memory_repository.update(compressed)
        await self._knowledge_memory_embedding_repository.create(
            KnowledgeMemoryEmbeddingRecord.build(
                memory_id=compressed.id, learner_profile_id=compressed.learner_profile_id,
                learner_goal_id=compressed.learner_goal_id, knowledge_key=compressed.knowledge_key,
                title=compressed.title, summary=compressed.summary, knowledge_level=compressed.knowledge_level,
                time_horizon=compressed.time_horizon, importance_score=compressed.importance_score,
                confidence_score=compressed.confidence_score, freshness_score=compressed.freshness_score,
                stability_score=compressed.stability_score, goal_relevance_score=compressed.goal_relevance_score,
                scope_type=compressed.scope_type, provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name, vector=compressed_vector, status=compressed.status,
            )
        )
        if self._governance_service is not None:
            await self._governance_service.record_governance_decision(
                memory_type="knowledge", memory_id=compressed.id, previous_status=None, new_status=compressed.status,
                decision_type="compress", trigger_source="compression_cycle",
                actor_type="system", actor_id="worker", reason_code="memory_cluster_compressed",
                reason_note=None, metrics_snapshot={"source_count": len(group)},
            )
        return 1

    async def _compress_behavior_group(
        self, group: list[BehaviorMemory], *, embeddings_by_memory_id: dict[str, BehaviorMemoryEmbeddingRecord],
    ) -> int:
        if (len(group) < 2 or self._behavior_memory_repository is None
                or self._behavior_memory_embedding_repository is None or self._embedding_provider is None):
            return 0
        compressed = build_compressed_behavior_memory(group)
        compressed_vector = (await self._embedding_provider.embed_texts([compressed.summary]))[0]
        await self._behavior_memory_repository.create(compressed.with_status("compressed"))
        for source in group:
            await self._behavior_memory_repository.update(source.with_compression(compressed_into_id=compressed.id))
            source_embedding = embeddings_by_memory_id.get(source.id)
            if source_embedding is not None:
                await self._behavior_memory_embedding_repository.update(
                    BehaviorMemoryEmbeddingRecord(
                        id=source_embedding.id, memory_id=source_embedding.memory_id,
                        learner_profile_id=source_embedding.learner_profile_id,
                        learner_goal_id=source_embedding.learner_goal_id,
                        behavior_key=source_embedding.behavior_key, behavior_category=source_embedding.behavior_category,
                        title=source_embedding.title, summary=source_embedding.summary,
                        behavior_level=source_embedding.behavior_level, time_horizon=source_embedding.time_horizon,
                        importance_score=source_embedding.importance_score, confidence_score=source_embedding.confidence_score,
                        freshness_score=source_embedding.freshness_score, stability_score=source_embedding.stability_score,
                        goal_relevance_score=source_embedding.goal_relevance_score, scope_type=source_embedding.scope_type,
                        provider=source_embedding.provider, model=source_embedding.model,
                        dimensions=source_embedding.dimensions, vector=source_embedding.vector,
                        status="compressed", created_at=source_embedding.created_at,
                    )
                )
        await self._behavior_memory_repository.update(compressed)
        await self._behavior_memory_embedding_repository.create(
            BehaviorMemoryEmbeddingRecord.build(
                memory_id=compressed.id, learner_profile_id=compressed.learner_profile_id,
                learner_goal_id=compressed.learner_goal_id, behavior_key=compressed.behavior_key,
                behavior_category=compressed.behavior_category, title=compressed.title,
                summary=compressed.summary, behavior_level=compressed.behavior_level,
                time_horizon=compressed.time_horizon, importance_score=compressed.importance_score,
                confidence_score=compressed.confidence_score, freshness_score=compressed.freshness_score,
                stability_score=compressed.stability_score, goal_relevance_score=compressed.goal_relevance_score,
                scope_type=compressed.scope_type, provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name, vector=compressed_vector, status=compressed.status,
            )
        )
        if self._governance_service is not None:
            await self._governance_service.record_governance_decision(
                memory_type="behavior", memory_id=compressed.id, previous_status=None, new_status=compressed.status,
                decision_type="compress", trigger_source="compression_cycle",
                actor_type="system", actor_id="worker", reason_code="memory_cluster_compressed",
                reason_note=None, metrics_snapshot={"source_count": len(group)},
            )
        return 1

    async def bridge_reflection_outcome(
        self, *, reflection: ReflectionRecord, evaluation: ReflectionOutcomeEvaluation,
        knowledge_repository: KnowledgeMemoryRepository | None = None,
        behavior_repository: BehaviorMemoryRepository | None = None,
    ) -> int:
        topic_key = topic_key_from_reflection(reflection)
        if topic_key is None or self._evidence_service is None:
            return 0
        knowledge_memories = []
        behavior_memories = []
        k_repo = knowledge_repository or self._knowledge_memory_repository
        b_repo = behavior_repository or self._behavior_memory_repository
        if k_repo is not None:
            knowledge_memories = [
                item for item in await k_repo.list_by_profile(
                    reflection.learner_profile_id, learner_goal_id=reflection.learner_goal_id,
                    statuses={"candidate", "active", "stable"},
                )
                if topic_alignment_score(topic_key, item.knowledge_key, title=item.title, tags=item.tags, extras=item.prerequisite_keys) >= 0.55
            ]
        if b_repo is not None:
            behavior_memories = [
                item for item in await b_repo.list_by_profile(
                    reflection.learner_profile_id, learner_goal_id=reflection.learner_goal_id,
                    statuses={"candidate", "active", "stable"},
                )
                if topic_alignment_score(
                    topic_key, item.behavior_key, title=item.title, tags=item.tags,
                    extras=[item.behavior_category, item.intervention_effect or ""],
                ) >= 0.45
            ]
        updates = 0
        for memory in knowledge_memories:
            await self._evidence_service.upsert_reflection_bridge_evidence(
                memory_type="knowledge", memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id, learner_goal_id=memory.learner_goal_id,
                reflection=reflection, evaluation=evaluation,
            )
            observe_memory_reflection_bridge(memory_type="knowledge", evaluation_status=evaluation.evaluation_status)
            updates += 1
        for memory in behavior_memories:
            await self._evidence_service.upsert_reflection_bridge_evidence(
                memory_type="behavior", memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id, learner_goal_id=memory.learner_goal_id,
                reflection=reflection, evaluation=evaluation,
            )
            observe_memory_reflection_bridge(memory_type="behavior", evaluation_status=evaluation.evaluation_status)
            updates += 1
        return updates
