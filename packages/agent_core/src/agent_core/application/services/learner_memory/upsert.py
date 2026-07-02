"""Long-term memory upsert, identity race recovery, and embedding sync."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.learner_memory.quality import clamp_score
from agent_core.application.services.learner_memory.result_types import LongTermMemoryUpsertResult
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    BehaviorMemoryEmbeddingRecord,
    KnowledgeMemory,
    KnowledgeMemoryEmbeddingRecord,
)
from agent_core.infrastructure.db.repositories import (
    BehaviorMemoryEmbeddingRepository,
    BehaviorMemoryRepository,
    KnowledgeMemoryEmbeddingRepository,
    KnowledgeMemoryRepository,
)
from agent_core.infrastructure.embedding.types import EmbeddingProvider


def has_material_refresh_change(
    previous: KnowledgeMemory | BehaviorMemory,
    refreshed: KnowledgeMemory | BehaviorMemory,
) -> bool:
    float_deltas = [
        abs(previous.importance_score - refreshed.importance_score),
        abs(previous.confidence_score - refreshed.confidence_score),
        abs(previous.freshness_score - refreshed.freshness_score),
        abs(previous.stability_score - refreshed.stability_score),
        abs(previous.support_score - refreshed.support_score),
        abs(previous.contradiction_score - refreshed.contradiction_score),
        abs(previous.goal_relevance_score - refreshed.goal_relevance_score),
    ]
    int_deltas = [
        abs(previous.evidence_count - refreshed.evidence_count),
        abs(previous.contradiction_count - refreshed.contradiction_count),
    ]
    if isinstance(previous, KnowledgeMemory) and isinstance(refreshed, KnowledgeMemory):
        int_deltas.append(abs(previous.assessment_evidence_count - refreshed.assessment_evidence_count))
        int_deltas.append(abs(previous.task_evidence_count - refreshed.task_evidence_count))
    if isinstance(previous, BehaviorMemory) and isinstance(refreshed, BehaviorMemory):
        int_deltas.append(abs(previous.intervention_success_count - refreshed.intervention_success_count))
        int_deltas.append(abs(previous.intervention_failure_count - refreshed.intervention_failure_count))
        int_deltas.append(abs(previous.cross_session_recurrence_count - refreshed.cross_session_recurrence_count))
    return any(delta >= 0.05 for delta in float_deltas) or any(delta > 0 for delta in int_deltas)


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


def merge_knowledge_memory(*, existing: KnowledgeMemory, incoming: KnowledgeMemory) -> KnowledgeMemory:
    now = datetime.now(timezone.utc)
    source_event_ids = _merge_unique([existing.source_event_ids, incoming.source_event_ids])
    source_memory_ids = _merge_unique([existing.source_memory_ids, incoming.source_memory_ids])
    tags = _merge_unique([existing.tags, incoming.tags])
    prerequisite_keys = _merge_unique([existing.prerequisite_keys, incoming.prerequisite_keys])
    return KnowledgeMemory(
        id=existing.id,
        learner_profile_id=existing.learner_profile_id,
        learner_goal_id=existing.learner_goal_id,
        knowledge_key=existing.knowledge_key,
        title=incoming.title or existing.title,
        summary=incoming.summary or existing.summary,
        details=incoming.details or existing.details,
        knowledge_level=_select_highest_level(
            [existing.knowledge_level, incoming.knowledge_level],
            ordered_levels=["foundation", "core", "advanced", "application"],
        ),
        time_horizon=incoming.time_horizon,
        importance_score=clamp_score(max(existing.importance_score, incoming.importance_score)),
        confidence_score=clamp_score(max(existing.confidence_score, incoming.confidence_score)),
        freshness_score=1.0,
        scope_type=existing.scope_type,
        stability_score=existing.stability_score,
        goal_relevance_score=max(existing.goal_relevance_score, incoming.goal_relevance_score),
        support_score=existing.support_score,
        contradiction_score=existing.contradiction_score,
        evidence_count=existing.evidence_count,
        contradiction_count=existing.contradiction_count,
        last_supported_at=existing.last_supported_at,
        last_contradicted_at=existing.last_contradicted_at,
        promotion_state_changed_at=existing.promotion_state_changed_at,
        suppressed_reason_code=existing.suppressed_reason_code,
        suppressed_reason_note=existing.suppressed_reason_note,
        suppressed_by=existing.suppressed_by,
        suppressed_at=existing.suppressed_at,
        prerequisite_keys=prerequisite_keys,
        source_event_ids=source_event_ids,
        source_memory_ids=source_memory_ids,
        tags=tags,
        status=existing.status,
        compressed_into_id=existing.compressed_into_id,
        last_reviewed_at=existing.last_reviewed_at,
        prerequisite_weight=max(existing.prerequisite_weight, incoming.prerequisite_weight),
        assessment_evidence_count=existing.assessment_evidence_count,
        task_evidence_count=existing.task_evidence_count,
        semantic_category=existing.semantic_category,
        validation_status=existing.validation_status,
        provenance_type=existing.provenance_type,
        provenance_source_id=existing.provenance_source_id,
        scope_ref=dict(existing.scope_ref or incoming.scope_ref),
        promotion_rationale=existing.promotion_rationale,
        created_at=existing.created_at,
        updated_at=now,
    )


def merge_behavior_memory(*, existing: BehaviorMemory, incoming: BehaviorMemory) -> BehaviorMemory:
    now = datetime.now(timezone.utc)
    source_event_ids = _merge_unique([existing.source_event_ids, incoming.source_event_ids])
    source_memory_ids = _merge_unique([existing.source_memory_ids, incoming.source_memory_ids])
    tags = _merge_unique([existing.tags, incoming.tags])
    return BehaviorMemory(
        id=existing.id,
        learner_profile_id=existing.learner_profile_id,
        learner_goal_id=existing.learner_goal_id,
        behavior_key=existing.behavior_key,
        behavior_category=existing.behavior_category,
        title=incoming.title or existing.title,
        summary=incoming.summary or existing.summary,
        details=incoming.details or existing.details,
        behavior_level=_select_highest_level(
            [existing.behavior_level, incoming.behavior_level],
            ordered_levels=["surface", "recurrent", "persistent", "critical"],
        ),
        time_horizon=incoming.time_horizon,
        importance_score=clamp_score(max(existing.importance_score, incoming.importance_score)),
        confidence_score=clamp_score(max(existing.confidence_score, incoming.confidence_score)),
        freshness_score=1.0,
        scope_type=existing.scope_type,
        stability_score=existing.stability_score,
        goal_relevance_score=max(existing.goal_relevance_score, incoming.goal_relevance_score),
        support_score=existing.support_score,
        contradiction_score=existing.contradiction_score,
        evidence_count=existing.evidence_count,
        contradiction_count=existing.contradiction_count,
        last_supported_at=existing.last_supported_at,
        last_contradicted_at=existing.last_contradicted_at,
        promotion_state_changed_at=existing.promotion_state_changed_at,
        suppressed_reason_code=existing.suppressed_reason_code,
        suppressed_reason_note=existing.suppressed_reason_note,
        suppressed_by=existing.suppressed_by,
        suppressed_at=existing.suppressed_at,
        source_event_ids=source_event_ids,
        source_memory_ids=source_memory_ids,
        tags=tags,
        intervention_effect=incoming.intervention_effect or existing.intervention_effect,
        status=existing.status,
        compressed_into_id=existing.compressed_into_id,
        last_reviewed_at=existing.last_reviewed_at,
        intervention_success_count=existing.intervention_success_count,
        intervention_failure_count=existing.intervention_failure_count,
        cross_session_recurrence_count=existing.cross_session_recurrence_count,
        semantic_category=existing.semantic_category,
        validation_status=existing.validation_status,
        provenance_type=existing.provenance_type,
        provenance_source_id=existing.provenance_source_id,
        scope_ref=dict(existing.scope_ref or incoming.scope_ref),
        promotion_rationale=existing.promotion_rationale,
        created_at=existing.created_at,
        updated_at=now,
    )


class UpsertService:
    """Handles long-term memory upsert, identity race recovery, and embedding sync."""

    def __init__(
        self,
        *,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        knowledge_memory_embedding_repository: KnowledgeMemoryEmbeddingRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        behavior_memory_embedding_repository: BehaviorMemoryEmbeddingRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        audit_service: AuditService | None = None,
    ) -> None:
        self._knowledge_memory_repository = knowledge_memory_repository
        self._knowledge_memory_embedding_repository = knowledge_memory_embedding_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._behavior_memory_embedding_repository = behavior_memory_embedding_repository
        self._embedding_provider = embedding_provider
        self._audit_service = audit_service

    @property
    def embedding_provider_name(self) -> str | None:
        return self._embedding_provider.provider_name if self._embedding_provider is not None else None

    @property
    def embedding_model_name(self) -> str | None:
        return self._embedding_provider.model_name if self._embedding_provider is not None else None

    async def upsert_knowledge_memory(
        self,
        memory: KnowledgeMemory,
        *,
        persist_embedding: bool = False,
    ) -> LongTermMemoryUpsertResult:
        if self._knowledge_memory_repository is None:
            return LongTermMemoryUpsertResult(memory=memory, action="skipped")
        existing_candidate = await self._knowledge_memory_repository.get_by_identity(
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            knowledge_key=memory.knowledge_key,
            semantic_category=memory.semantic_category,
            statuses={"candidate"},
        )
        if existing_candidate is not None:
            refreshed = merge_knowledge_memory(existing=existing_candidate, incoming=memory)
            await self._knowledge_memory_repository.update(refreshed)
            await self.sync_knowledge_embedding(refreshed)
            await self._record_memory_write_audit(
                memory_type="knowledge",
                memory_id=refreshed.id,
                memory=refreshed,
                embedding_record=None,
            )
            return LongTermMemoryUpsertResult(memory=refreshed, action="refreshed")
        existing_active = await self._knowledge_memory_repository.get_by_identity(
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            knowledge_key=memory.knowledge_key,
            semantic_category=memory.semantic_category,
            statuses={"active", "stable"},
        )
        if existing_active is not None:
            return LongTermMemoryUpsertResult(memory=existing_active, action="evidence_only")
        existing_suppressed = await self._knowledge_memory_repository.get_by_identity(
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            knowledge_key=memory.knowledge_key,
            semantic_category=memory.semantic_category,
            statuses={"suppressed"},
        )
        if existing_suppressed is not None:
            return LongTermMemoryUpsertResult(memory=existing_suppressed, action="skipped_suppressed")
        recorded = await self._record_knowledge_memory(memory, persist_embedding=persist_embedding)
        if recorded.id != memory.id:
            return await self._resolve_knowledge_identity_race(existing=recorded, incoming=memory)
        return LongTermMemoryUpsertResult(memory=recorded, action="created")

    async def upsert_behavior_memory(
        self,
        memory: BehaviorMemory,
        *,
        persist_embedding: bool = False,
    ) -> LongTermMemoryUpsertResult:
        if self._behavior_memory_repository is None:
            return LongTermMemoryUpsertResult(memory=memory, action="skipped")
        existing_candidate = await self._behavior_memory_repository.get_by_identity(
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            behavior_key=memory.behavior_key,
            behavior_category=memory.behavior_category,
            statuses={"candidate"},
        )
        if existing_candidate is not None:
            refreshed = merge_behavior_memory(existing=existing_candidate, incoming=memory)
            await self._behavior_memory_repository.update(refreshed)
            await self.sync_behavior_embedding(refreshed)
            await self._record_memory_write_audit(
                memory_type="behavior",
                memory_id=refreshed.id,
                memory=refreshed,
                embedding_record=None,
            )
            return LongTermMemoryUpsertResult(memory=refreshed, action="refreshed")
        existing_active = await self._behavior_memory_repository.get_by_identity(
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            behavior_key=memory.behavior_key,
            behavior_category=memory.behavior_category,
            statuses={"active", "stable"},
        )
        if existing_active is not None:
            return LongTermMemoryUpsertResult(memory=existing_active, action="evidence_only")
        existing_suppressed = await self._behavior_memory_repository.get_by_identity(
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            behavior_key=memory.behavior_key,
            behavior_category=memory.behavior_category,
            statuses={"suppressed"},
        )
        if existing_suppressed is not None:
            return LongTermMemoryUpsertResult(memory=existing_suppressed, action="skipped_suppressed")
        recorded = await self._record_behavior_memory(memory, persist_embedding=persist_embedding)
        if recorded.id != memory.id:
            return await self._resolve_behavior_identity_race(existing=recorded, incoming=memory)
        return LongTermMemoryUpsertResult(memory=recorded, action="created")

    async def _resolve_knowledge_identity_race(
        self,
        *,
        existing: KnowledgeMemory,
        incoming: KnowledgeMemory,
    ) -> LongTermMemoryUpsertResult:
        if existing.status == "candidate":
            refreshed = merge_knowledge_memory(existing=existing, incoming=incoming)
            if self._knowledge_memory_repository is not None:
                await self._knowledge_memory_repository.update(refreshed)
            await self.sync_knowledge_embedding(refreshed)
            await self._record_memory_write_audit(
                memory_type="knowledge",
                memory_id=refreshed.id,
                memory=refreshed,
                embedding_record=None,
            )
            return LongTermMemoryUpsertResult(memory=refreshed, action="refreshed")
        if existing.status in {"active", "stable"}:
            return LongTermMemoryUpsertResult(memory=existing, action="evidence_only")
        if existing.status == "suppressed":
            return LongTermMemoryUpsertResult(memory=existing, action="skipped_suppressed")
        return LongTermMemoryUpsertResult(memory=existing, action="skipped")

    async def _resolve_behavior_identity_race(
        self,
        *,
        existing: BehaviorMemory,
        incoming: BehaviorMemory,
    ) -> LongTermMemoryUpsertResult:
        if existing.status == "candidate":
            refreshed = merge_behavior_memory(existing=existing, incoming=incoming)
            if self._behavior_memory_repository is not None:
                await self._behavior_memory_repository.update(refreshed)
            await self.sync_behavior_embedding(refreshed)
            await self._record_memory_write_audit(
                memory_type="behavior",
                memory_id=refreshed.id,
                memory=refreshed,
                embedding_record=None,
            )
            return LongTermMemoryUpsertResult(memory=refreshed, action="refreshed")
        if existing.status in {"active", "stable"}:
            return LongTermMemoryUpsertResult(memory=existing, action="evidence_only")
        if existing.status == "suppressed":
            return LongTermMemoryUpsertResult(memory=existing, action="skipped_suppressed")
        return LongTermMemoryUpsertResult(memory=existing, action="skipped")

    async def _record_knowledge_memory(self, memory: KnowledgeMemory, *, persist_embedding: bool) -> KnowledgeMemory:
        if self._knowledge_memory_repository is None:
            raise RuntimeError("knowledge memory repository is not configured")
        failure_stage = "knowledge_memory.persist"
        embedding_record: KnowledgeMemoryEmbeddingRecord | None = None
        try:
            existing = await self._knowledge_memory_repository.create(memory)
            if existing is not None:
                return existing
            if persist_embedding and self._embedding_provider is not None and self._knowledge_memory_embedding_repository is not None:
                failure_stage = "knowledge_embedding.generate"
                vector = (await self._embedding_provider.embed_texts([memory.summary]))[0]
                embedding_record = KnowledgeMemoryEmbeddingRecord.build(
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    knowledge_key=memory.knowledge_key,
                    title=memory.title,
                    summary=memory.summary,
                    knowledge_level=memory.knowledge_level,
                    time_horizon=memory.time_horizon,
                    importance_score=memory.importance_score,
                    confidence_score=memory.confidence_score,
                    freshness_score=memory.freshness_score,
                    stability_score=memory.stability_score,
                    goal_relevance_score=memory.goal_relevance_score,
                    scope_type=memory.scope_type,
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    vector=vector,
                    status=memory.status,
                )
                failure_stage = "knowledge_embedding.persist"
                await self._knowledge_memory_embedding_repository.create(embedding_record)
            await self._record_memory_write_audit(
                memory_type="knowledge",
                memory_id=memory.id,
                memory=memory,
                embedding_record=embedding_record,
            )
            return memory
        except Exception as exc:
            if self._audit_service is not None:
                await self._audit_service.record_durable(
                    event_type="knowledge_memory.record.failed",
                    resource_type="knowledge_memory",
                    resource_id=memory.id,
                    actor="system",
                    event_data={
                        "memory_id": memory.id,
                        "learner_profile_id": memory.learner_profile_id,
                        "knowledge_key": memory.knowledge_key,
                        "failure_stage": failure_stage,
                        "embedding_provider": self.embedding_provider_name,
                        "embedding_model": self.embedding_model_name,
                        "error": str(exc),
                    },
                )
            raise

    async def _record_behavior_memory(self, memory: BehaviorMemory, *, persist_embedding: bool) -> BehaviorMemory:
        if self._behavior_memory_repository is None:
            raise RuntimeError("behavior memory repository is not configured")
        failure_stage = "behavior_memory.persist"
        embedding_record: BehaviorMemoryEmbeddingRecord | None = None
        try:
            existing = await self._behavior_memory_repository.create(memory)
            if existing is not None:
                return existing
            if persist_embedding and self._embedding_provider is not None and self._behavior_memory_embedding_repository is not None:
                failure_stage = "behavior_embedding.generate"
                vector = (await self._embedding_provider.embed_texts([memory.summary]))[0]
                embedding_record = BehaviorMemoryEmbeddingRecord.build(
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    behavior_key=memory.behavior_key,
                    behavior_category=memory.behavior_category,
                    title=memory.title,
                    summary=memory.summary,
                    behavior_level=memory.behavior_level,
                    time_horizon=memory.time_horizon,
                    importance_score=memory.importance_score,
                    confidence_score=memory.confidence_score,
                    freshness_score=memory.freshness_score,
                    stability_score=memory.stability_score,
                    goal_relevance_score=memory.goal_relevance_score,
                    scope_type=memory.scope_type,
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    vector=vector,
                    status=memory.status,
                )
                failure_stage = "behavior_embedding.persist"
                await self._behavior_memory_embedding_repository.create(embedding_record)
            await self._record_memory_write_audit(
                memory_type="behavior",
                memory_id=memory.id,
                memory=memory,
                embedding_record=embedding_record,
            )
            return memory
        except Exception as exc:
            if self._audit_service is not None:
                await self._audit_service.record_durable(
                    event_type="behavior_memory.record.failed",
                    resource_type="behavior_memory",
                    resource_id=memory.id,
                    actor="system",
                    event_data={
                        "memory_id": memory.id,
                        "learner_profile_id": memory.learner_profile_id,
                        "behavior_key": memory.behavior_key,
                        "failure_stage": failure_stage,
                        "embedding_provider": self.embedding_provider_name,
                        "embedding_model": self.embedding_model_name,
                        "error": str(exc),
                    },
                )
            raise

    async def sync_knowledge_embedding(self, memory: KnowledgeMemory, *, create_missing: bool = False) -> None:
        if self._knowledge_memory_embedding_repository is None:
            return
        embedding = await self._knowledge_memory_embedding_repository.get_by_memory_id(memory.id)
        if embedding is None:
            if not create_missing or self._embedding_provider is None:
                return
            vector = (await self._embedding_provider.embed_texts([memory.summary]))[0]
            await self._knowledge_memory_embedding_repository.create(
                KnowledgeMemoryEmbeddingRecord.build(
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    knowledge_key=memory.knowledge_key,
                    title=memory.title,
                    summary=memory.summary,
                    knowledge_level=memory.knowledge_level,
                    time_horizon=memory.time_horizon,
                    importance_score=memory.importance_score,
                    confidence_score=memory.confidence_score,
                    freshness_score=memory.freshness_score,
                    stability_score=memory.stability_score,
                    goal_relevance_score=memory.goal_relevance_score,
                    scope_type=memory.scope_type,
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    vector=vector,
                    status=memory.status,
                )
            )
            return
        await self._knowledge_memory_embedding_repository.update(
            KnowledgeMemoryEmbeddingRecord(
                id=embedding.id,
                memory_id=embedding.memory_id,
                learner_profile_id=embedding.learner_profile_id,
                learner_goal_id=embedding.learner_goal_id,
                knowledge_key=memory.knowledge_key,
                title=memory.title,
                summary=memory.summary,
                knowledge_level=memory.knowledge_level,
                time_horizon=memory.time_horizon,
                importance_score=memory.importance_score,
                confidence_score=memory.confidence_score,
                freshness_score=memory.freshness_score,
                stability_score=memory.stability_score,
                goal_relevance_score=memory.goal_relevance_score,
                scope_type=memory.scope_type,
                provider=embedding.provider,
                model=embedding.model,
                dimensions=embedding.dimensions,
                vector=embedding.vector,
                status=memory.status,
                created_at=embedding.created_at,
            )
        )

    async def sync_behavior_embedding(self, memory: BehaviorMemory) -> None:
        if self._behavior_memory_embedding_repository is None:
            return
        embedding = await self._behavior_memory_embedding_repository.get_by_memory_id(memory.id)
        if embedding is None:
            return
        await self._behavior_memory_embedding_repository.update(
            BehaviorMemoryEmbeddingRecord(
                id=embedding.id,
                memory_id=embedding.memory_id,
                learner_profile_id=embedding.learner_profile_id,
                learner_goal_id=embedding.learner_goal_id,
                behavior_key=memory.behavior_key,
                behavior_category=memory.behavior_category,
                title=memory.title,
                summary=memory.summary,
                behavior_level=memory.behavior_level,
                time_horizon=memory.time_horizon,
                importance_score=memory.importance_score,
                confidence_score=memory.confidence_score,
                freshness_score=memory.freshness_score,
                stability_score=memory.stability_score,
                goal_relevance_score=memory.goal_relevance_score,
                scope_type=memory.scope_type,
                provider=embedding.provider,
                model=embedding.model,
                dimensions=embedding.dimensions,
                vector=embedding.vector,
                status=memory.status,
                created_at=embedding.created_at,
            )
        )

    async def _record_memory_write_audit(
        self,
        *,
        memory_type: str,
        memory_id: str,
        memory: KnowledgeMemory | BehaviorMemory,
        embedding_record: KnowledgeMemoryEmbeddingRecord | BehaviorMemoryEmbeddingRecord | None,
    ) -> None:
        if self._audit_service is None:
            return
        payload: dict[str, Any] = {
            "memory_id": memory_id,
            "learner_profile_id": memory.learner_profile_id,
            "learner_goal_id": memory.learner_goal_id,
            "importance_score": memory.importance_score,
            "confidence_score": memory.confidence_score,
            "freshness_score": memory.freshness_score,
            "status": memory.status,
            "scope_type": memory.scope_type,
            "embedding_provider": embedding_record.provider if embedding_record is not None else None,
            "embedding_model": embedding_record.model if embedding_record is not None else None,
            "embedding_dimensions": embedding_record.dimensions if embedding_record is not None else None,
        }
        if memory_type == "knowledge":
            payload["knowledge_key"] = getattr(memory, "knowledge_key", None)
            payload["knowledge_level"] = getattr(memory, "knowledge_level", None)
            payload["time_horizon"] = getattr(memory, "time_horizon", None)
            payload["source_event_ids"] = getattr(memory, "source_event_ids", [])
        else:
            payload["behavior_key"] = getattr(memory, "behavior_key", None)
            payload["behavior_category"] = getattr(memory, "behavior_category", None)
            payload["behavior_level"] = getattr(memory, "behavior_level", None)
            payload["time_horizon"] = getattr(memory, "time_horizon", None)
            payload["source_event_ids"] = getattr(memory, "source_event_ids", [])
        await self._audit_service.record(
            event_type=f"{memory_type}_memory.recorded",
            resource_type=f"{memory_type}_memory",
            resource_id=memory_id,
            actor="system",
            event_data=payload,
        )
