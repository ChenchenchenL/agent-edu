from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import sqrt
from time import perf_counter
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.memory_conflict_policy import (
    CONFLICT_CONTRADICTION_THRESHOLD,
    MemoryConflictPolicy,
)
from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.domain.entities.autonomy import LearnerTopicMastery, TaskAttempt
from agent_core.domain.entities.memory import (
    BEHAVIOR_LEVELS,
    MEMORY_STATUSES,
    MEMORY_RETRIEVAL_STATUSES,
    BehaviorMemory,
    BehaviorMemoryEmbeddingRecord,
    BehaviorMemoryRetrievalResult,
    BehaviorMemoryStatusUpdate,
    KnowledgeMemory,
    KnowledgeMemoryEmbeddingRecord,
    KnowledgeMemoryRetrievalResult,
    KnowledgeMemoryStatusUpdate,
    MemoryAnnotation,
    MemoryConflictMember,
    MemoryConflictSet,
    MemoryEmbeddingRecord,
    MemoryEvent,
    MemoryEvidenceLink,
    MemoryGovernanceDecision,
    MemoryRetrievalResult,
    RetrievedBehaviorMemory,
    RetrievedKnowledgeMemory,
    RetrievedMemory,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.infrastructure.db.repositories import (
    BehaviorMemoryEmbeddingRepository,
    BehaviorMemoryRepository,
    KnowledgeMemoryEmbeddingRepository,
    KnowledgeMemoryRepository,
    LearnerTopicMasteryRepository,
    MemoryAnnotationRepository,
    MemoryEmbeddingRepository,
    MemoryEventRepository,
    MemoryEvidenceLinkRepository,
    MemoryGovernanceDecisionRepository,
    MemoryConflictRepository,
    TaskAttemptRepository,
)
from agent_core.infrastructure.embedding.types import EmbeddingProvider
from agent_core.infrastructure.observability.metrics import (
    observe_memory_conflict_event,
    observe_memory_evidence_upsert,
    observe_memory_governance_decision,
    observe_memory_maintenance_run,
    observe_memory_quality_assessment,
    observe_memory_reflection_bridge,
    observe_memory_retrieval,
    set_memory_candidate_backlog,
    set_memory_open_conflicts,
)


@dataclass(frozen=True)
class LongTermMemoryWriteResult:
    knowledge_memories: list[KnowledgeMemory]
    behavior_memories: list[BehaviorMemory]


@dataclass(frozen=True)
class LongTermMemoryUpsertResult:
    memory: KnowledgeMemory | BehaviorMemory
    action: str


@dataclass(frozen=True)
class MemoryMaintenanceResult:
    compressed_knowledge_groups: int
    compressed_behavior_groups: int
    promoted_knowledge: int = 0
    promoted_behavior: int = 0
    demoted_knowledge: int = 0
    demoted_behavior: int = 0


@dataclass(frozen=True)
class MemoryMaintenanceBatchResult:
    processed_count: int
    changed_count: int
    next_cursor: str | None
    completed: bool
    metadata: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeEvidenceWeights:
    completed_assessment: float = 0.35
    completed_practice_or_review: float = 0.25
    completed_other_task: float = 0.15
    failed_assessment: float = 0.35
    failed_other_task: float = 0.25
    progress_event: float = 0.10
    struggle_event: float = 0.08
    neutral_event_refresh: float = 0.05
    strong_mastery: float = 0.10
    weak_mastery: float = 0.10
    task_attempt_assessment_link: float = 0.35
    task_attempt_default_link: float = 0.25
    completed_practice_or_review_link: float = 0.20


@dataclass(frozen=True)
class BehaviorEvidenceWeights:
    recurrence_per_session: float = 0.20
    max_recurrence_support: float = 0.60
    failed_or_skipped_task: float = 0.15
    completed_task_contradiction: float = 0.10
    failed_or_skipped_task_link: float = 0.20
    completed_task_link: float = 0.10
    struggle_event_link: float = 0.12
    neutral_event_link: float = 0.06


KNOWLEDGE_EVIDENCE_WEIGHTS = KnowledgeEvidenceWeights()
BEHAVIOR_EVIDENCE_WEIGHTS = BehaviorEvidenceWeights()


@dataclass(frozen=True)
class MemoryConflictMemberDetail:
    id: str
    conflict_set_id: str
    memory_type: str
    memory_id: str
    memory_key: str
    stance: str
    support_score: float
    contradiction_score: float
    member_title: str | None
    member_summary: str | None
    member_status: str | None
    member_validation_status: str | None
    created_at: datetime


@dataclass(frozen=True)
class ReflectionCorpusMemoryItem:
    memory_type: str
    memory_id: str
    learner_profile_id: str
    learner_goal_id: str | None
    memory_key: str
    memory_level: str
    title: str
    summary: str
    status: str
    time_horizon: str
    importance_score: float
    confidence_score: float
    freshness_score: float
    stability_score: float
    goal_relevance_score: float
    support_score: float
    contradiction_score: float
    evidence_count: int
    contradiction_count: int
    reflection_priority_score: float
    recommended_action: str
    rationale: str
    recommended_action_reason: str
    topic_alignment_score: float
    governance_pressure: float
    review_recommended: bool
    quality_score: float
    quality_tier: str
    promotion_readiness: str
    quality_reasons: list[str]
    evidence_mix: dict[str, float]
    semantic_category: str
    validation_status: str
    provenance_type: str
    provenance_source_id: str | None
    scope_ref: dict[str, str | None]
    promotion_rationale: str | None
    contested: bool
    source_event_ids: list[str]
    source_memory_ids: list[str]
    tags: list[str]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ReflectionCorpusSummary:
    total_items: int
    knowledge_items: int
    behavior_items: int
    candidate_items: int
    stable_items: int
    contradiction_focus_items: int
    stale_focus_items: int
    validate_items: int
    reinforce_items: int


@dataclass(frozen=True)
class ReflectionCorpusResult:
    learner_profile_id: str
    learner_goal_id: str | None
    generated_at: datetime
    items: list[ReflectionCorpusMemoryItem]
    summary: ReflectionCorpusSummary


@dataclass(frozen=True)
class BrowseMemoriesResult:
    total: int
    limit: int
    offset: int
    items: list[KnowledgeMemory] | list[BehaviorMemory]


@dataclass(frozen=True)
class MemoryGovernanceSummary:
    learner_profile_id: str
    learner_goal_id: str | None
    knowledge_total: int
    behavior_total: int
    candidate_total: int
    active_total: int
    stable_total: int
    archived_total: int
    suppressed_total: int
    contradiction_focus_total: int
    stale_candidate_total: int
    high_priority_total: int
    recent_promotions: int
    recent_demotions: int
    recent_archives: int
    recent_compressions: int
    promotion_candidate_total: int
    demotion_risk_total: int
    operator_review_recommended_total: int
    reflection_bridge_total: int
    high_quality_total: int
    medium_quality_total: int
    ready_promotion_total: int
    weak_candidate_total: int
    quality_tier_totals: dict[str, int]
    topic_bucket_summary: list[dict[str, object]]


@dataclass(frozen=True)
class MemoryInterpretationFact:
    memory_type: str
    memory_id: str
    memory_key: str
    semantic_category: str
    validation_status: str
    title: str
    summary: str
    confidence_score: float
    importance_score: float
    recommended_use: str


@dataclass(frozen=True)
class MemoryInterpretationResult:
    learner_profile_id: str
    learner_goal_id: str | None
    generated_at: datetime
    facts: list[MemoryInterpretationFact]
    behavior_patterns: list[MemoryInterpretationFact]
    contested_items: list[MemoryInterpretationFact]
    recommended_constraints: list[str]
    conflict_count: int


class MemoryService:
    def __init__(
        self,
        repository: MemoryEventRepository,
        *,
        embedding_repository: MemoryEmbeddingRepository | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        audit_service: AuditService | None = None,
        knowledge_memory_repository: KnowledgeMemoryRepository | None = None,
        knowledge_memory_embedding_repository: KnowledgeMemoryEmbeddingRepository | None = None,
        behavior_memory_repository: BehaviorMemoryRepository | None = None,
        behavior_memory_embedding_repository: BehaviorMemoryEmbeddingRepository | None = None,
        evidence_link_repository: MemoryEvidenceLinkRepository | None = None,
        governance_decision_repository: MemoryGovernanceDecisionRepository | None = None,
        conflict_repository: MemoryConflictRepository | None = None,
        annotation_repository: MemoryAnnotationRepository | None = None,
        task_attempt_repository: TaskAttemptRepository | None = None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
        governance_config: dict[str, float | int] | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_repository = embedding_repository
        self._embedding_provider = embedding_provider
        self._audit_service = audit_service
        self._knowledge_memory_repository = knowledge_memory_repository
        self._knowledge_memory_embedding_repository = knowledge_memory_embedding_repository
        self._behavior_memory_repository = behavior_memory_repository
        self._behavior_memory_embedding_repository = behavior_memory_embedding_repository
        self._evidence_link_repository = evidence_link_repository
        self._governance_decision_repository = governance_decision_repository
        self._conflict_repository = conflict_repository
        self._annotation_repository = annotation_repository
        self._task_attempt_repository = task_attempt_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._governance_config = governance_config or self._default_governance_config()

    @property
    def embedding_provider_name(self) -> str | None:
        return self._embedding_provider.provider_name if self._embedding_provider is not None else None

    @property
    def embedding_model_name(self) -> str | None:
        return self._embedding_provider.model_name if self._embedding_provider is not None else None

    async def record_session_event(
        self,
        *,
        session_id: str,
        learner_profile_id: str,
        memory_scope: str,
        memory_level: str,
        summary: str,
        progress_note: str | None,
        struggle_note: str | None,
        concept_focus: str | None,
        source_message_id: str | None,
        tags: list[str],
    ) -> MemoryEvent:
        event = MemoryEvent.build(
            session_id=session_id,
            learner_profile_id=learner_profile_id,
            event_type="session.note",
            memory_scope=memory_scope,
            memory_level=memory_level,
            summary=summary,
            progress_note=progress_note,
            struggle_note=struggle_note,
            concept_focus=concept_focus,
            source_message_id=source_message_id,
            tags=tags,
        )
        embedding_record: MemoryEmbeddingRecord | None = None
        failure_stage = "memory_event.persist"
        try:
            await self._repository.create(event)
            if self._embedding_provider is not None and self._embedding_repository is not None:
                failure_stage = "embedding.generate"
                vector = (await self._embedding_provider.embed_texts([summary]))[0]
                embedding_record = MemoryEmbeddingRecord.build(
                    memory_event_id=event.id,
                    session_id=session_id,
                    learner_profile_id=learner_profile_id,
                    memory_scope=memory_scope,
                    memory_level=memory_level,
                    provider=self._embedding_provider.provider_name,
                    model=self._embedding_provider.model_name,
                    vector=vector,
                    summary=summary,
                )
                failure_stage = "embedding.persist"
                await self._embedding_repository.create(embedding_record)
            if self._audit_service is not None:
                failure_stage = "audit.persist"
                await self._audit_service.record(
                    event_type="memory.event.recorded",
                    resource_type="memory_event",
                    resource_id=event.id,
                    actor="system",
                    event_data={
                        "memory_event_id": event.id,
                        "session_id": session_id,
                        "learner_profile_id": learner_profile_id,
                        "source_message_id": source_message_id,
                        "memory_scope": memory_scope,
                        "memory_level": memory_level,
                        "concept_focus": concept_focus,
                        "tags": tags,
                        "embedding_provider": embedding_record.provider if embedding_record is not None else None,
                        "embedding_model": embedding_record.model if embedding_record is not None else None,
                        "embedding_dimensions": embedding_record.dimensions if embedding_record is not None else None,
                    },
                )
            return event
        except Exception as exc:
            if self._audit_service is not None:
                await self._audit_service.record_durable(
                    event_type="memory.event.record.failed",
                    resource_type="memory_event",
                    resource_id=event.id,
                    actor="system",
                    event_data={
                        "memory_event_id": event.id,
                        "session_id": session_id,
                        "learner_profile_id": learner_profile_id,
                        "source_message_id": source_message_id,
                        "memory_scope": memory_scope,
                        "memory_level": memory_level,
                        "failure_stage": failure_stage,
                        "embedding_provider": self.embedding_provider_name,
                        "embedding_model": self.embedding_model_name,
                        "error": str(exc),
                    },
                )
            raise

    async def record_learning_memories(
        self,
        *,
        session_id: str,
        learner_profile_id: str,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
    ) -> list[MemoryEvent]:
        extraction = self.extract_learning_signals(
            learner_message=learner_message,
            assistant_message=assistant_message,
            mode=mode,
            subject=subject,
            session_title=session_title,
        )
        return [
            await self.record_session_event(
                session_id=session_id,
                learner_profile_id=learner_profile_id,
                memory_scope=str(item["memory_scope"]),
                memory_level=str(item["memory_level"]),
                summary=str(item["summary"]),
                progress_note=item["progress_note"] if isinstance(item["progress_note"], str) else None,
                struggle_note=item["struggle_note"] if isinstance(item["struggle_note"], str) else None,
                concept_focus=item["concept_focus"] if isinstance(item["concept_focus"], str) else None,
                source_message_id=source_message_id,
                tags=list(item["tags"]) if isinstance(item["tags"], list) else [],
            )
            for item in extraction
        ]

    async def record_long_term_memories(
        self,
        *,
        session_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        persist_embeddings: bool = False,
    ) -> LongTermMemoryWriteResult:
        raise ValidationError(
            "record_long_term_memories() is deprecated. Use LongTermMemoryMaterializationService instead."
        )

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
            refreshed = self._merge_knowledge_memory(existing=existing_candidate, incoming=memory)
            await self._knowledge_memory_repository.update(refreshed)
            await self._sync_knowledge_embedding(refreshed)
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
            refreshed = self._merge_behavior_memory(existing=existing_candidate, incoming=memory)
            await self._behavior_memory_repository.update(refreshed)
            await self._sync_behavior_embedding(refreshed)
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
            refreshed = self._merge_knowledge_memory(existing=existing, incoming=incoming)
            if self._knowledge_memory_repository is not None:
                await self._knowledge_memory_repository.update(refreshed)
            await self._sync_knowledge_embedding(refreshed)
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
            refreshed = self._merge_behavior_memory(existing=existing, incoming=incoming)
            if self._behavior_memory_repository is not None:
                await self._behavior_memory_repository.update(refreshed)
            await self._sync_behavior_embedding(refreshed)
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

    def build_knowledge_memory_candidate(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        source_event_ids: list[str] | None = None,
        provenance_type: str | None = None,
        provenance_source_id: str | None = None,
    ) -> KnowledgeMemory | None:
        return self._build_knowledge_memory(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=source_message_id,
            mode=mode,
            subject=subject,
            session_title=session_title,
            source_event_ids=source_event_ids,
            provenance_type=provenance_type,
            provenance_source_id=provenance_source_id,
        )

    def build_behavior_memory_candidate(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        source_event_ids: list[str] | None = None,
        provenance_type: str | None = None,
        provenance_source_id: str | None = None,
    ) -> BehaviorMemory | None:
        return self._build_behavior_memory(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            learner_message=learner_message,
            assistant_message=assistant_message,
            source_message_id=source_message_id,
            mode=mode,
            subject=subject,
            session_title=session_title,
            source_event_ids=source_event_ids,
            provenance_type=provenance_type,
            provenance_source_id=provenance_source_id,
        )

    def extract_learning_signals(
        self,
        *,
        learner_message: str,
        assistant_message: str,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
    ) -> list[dict[str, str | list[str] | None]]:
        topic = subject or session_title or self._infer_concept_focus(learner_message)
        struggle_note = self._infer_struggle_note(learner_message)
        progress_note = self._infer_progress_note(assistant_message=assistant_message, mode=mode)
        concept_focus = self._infer_concept_focus(learner_message) or topic
        summary = self._build_event_summary(
            topic=topic or "current topic",
            concept_focus=concept_focus,
            struggle_note=struggle_note,
            progress_note=progress_note,
            mode=mode,
        )
        events: list[dict[str, str | list[str] | None]] = [
            {
                "memory_scope": "session",
                "memory_level": "episodic",
                "summary": summary,
                "progress_note": progress_note,
                "struggle_note": struggle_note,
                "concept_focus": concept_focus,
                "tags": self._build_tags(mode=mode, concept_focus=concept_focus, struggle_note=struggle_note),
            }
        ]
        if progress_note is not None or struggle_note is not None:
            events.append(
                {
                    "memory_scope": "profile",
                    "memory_level": "semantic",
                    "summary": self._build_profile_summary(
                        topic=topic or "current topic",
                        concept_focus=concept_focus,
                        progress_note=progress_note,
                        struggle_note=struggle_note,
                    ),
                    "progress_note": progress_note,
                    "struggle_note": struggle_note,
                    "concept_focus": concept_focus,
                    "tags": self._build_tags(mode=mode, concept_focus=concept_focus, struggle_note=struggle_note)
                    + ["profile"],
                }
            )
        return events

    async def retrieve_relevant_session_memories(
        self,
        *,
        session_id: str,
        query_text: str,
        limit: int = 3,
        candidate_limit: int = 24,
        min_score: float = 0.15,
    ) -> MemoryRetrievalResult:
        return await self._retrieve_memory_events(
            query_text=query_text,
            candidate_limit=candidate_limit,
            min_score=min_score,
            limit=limit,
            fetch=lambda: self._embedding_repository.list_recent_by_session(session_id=session_id, limit=candidate_limit)
            if self._embedding_repository is not None
            else [],
            filter_scope=None,
        )

    async def retrieve_relevant_profile_memories(
        self,
        *,
        learner_profile_id: str,
        query_text: str,
        limit: int = 3,
        candidate_limit: int = 24,
        min_score: float = 0.15,
    ) -> MemoryRetrievalResult:
        return await self._retrieve_memory_events(
            query_text=query_text,
            candidate_limit=candidate_limit,
            min_score=min_score,
            limit=limit,
            fetch=lambda: self._embedding_repository.list_recent_by_profile(
                learner_profile_id=learner_profile_id,
                limit=candidate_limit,
            )
            if self._embedding_repository is not None
            else [],
            filter_scope="profile",
        )

    async def retrieve_relevant_knowledge_memories(
        self,
        *,
        learner_profile_id: str,
        query_text: str,
        limit: int = 3,
        candidate_limit: int = 24,
        min_score: float = 0.15,
    ) -> KnowledgeMemoryRetrievalResult:
        if self._embedding_provider is None or self._knowledge_memory_embedding_repository is None:
            return KnowledgeMemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0)

        started_at = perf_counter()
        query_vectors = await self._embedding_provider.embed_texts([query_text])
        if not query_vectors:
            return KnowledgeMemoryRetrievalResult(
                memories=[],
                provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name,
                latency_ms=int((perf_counter() - started_at) * 1000),
                candidate_count=0,
            )
        query_vector = query_vectors[0]
        candidates = await self._knowledge_memory_embedding_repository.list_recent_by_profile(
            learner_profile_id=learner_profile_id,
            limit=candidate_limit,
        )
        scored: list[RetrievedKnowledgeMemory] = []
        for item in candidates:
            if not item.vector or item.status not in MEMORY_RETRIEVAL_STATUSES:
                continue
            score = self._score_long_term_memory(
                vector=item.vector,
                query_vector=query_vector,
                importance_score=item.importance_score,
                confidence_score=item.confidence_score,
                freshness_score=item.freshness_score,
                stability_score=item.stability_score,
                goal_relevance_score=item.goal_relevance_score,
                created_at=item.created_at,
            )
            scored.append(
                RetrievedKnowledgeMemory(
                    memory_id=item.memory_id,
                    knowledge_key=item.knowledge_key,
                    title=item.title,
                    summary=item.summary,
                    knowledge_level=item.knowledge_level,
                    time_horizon=item.time_horizon,
                    importance_score=item.importance_score,
                    confidence_score=item.confidence_score,
                    freshness_score=item.freshness_score,
                    stability_score=item.stability_score,
                    goal_relevance_score=item.goal_relevance_score,
                    status=item.status,
                    score=score,
                    created_at=item.created_at,
                )
            )
        scored.sort(key=lambda item: (item.score, item.importance_score, item.created_at), reverse=True)
        memories = [item for item in scored if item.score >= min_score][:limit]
        observe_memory_retrieval(
            memory_type="knowledge",
            result_count=len(memories),
            candidate_count=len(candidates),
        )
        return KnowledgeMemoryRetrievalResult(
            memories=memories,
            provider=self._embedding_provider.provider_name,
            model=self._embedding_provider.model_name,
            latency_ms=int((perf_counter() - started_at) * 1000),
            candidate_count=len(candidates),
        )

    async def retrieve_relevant_behavior_memories(
        self,
        *,
        learner_profile_id: str,
        query_text: str,
        limit: int = 3,
        candidate_limit: int = 24,
        min_score: float = 0.15,
    ) -> BehaviorMemoryRetrievalResult:
        if self._embedding_provider is None or self._behavior_memory_embedding_repository is None:
            return BehaviorMemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0)

        started_at = perf_counter()
        query_vectors = await self._embedding_provider.embed_texts([query_text])
        if not query_vectors:
            return BehaviorMemoryRetrievalResult(
                memories=[],
                provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name,
                latency_ms=int((perf_counter() - started_at) * 1000),
                candidate_count=0,
            )
        query_vector = query_vectors[0]
        candidates = await self._behavior_memory_embedding_repository.list_recent_by_profile(
            learner_profile_id=learner_profile_id,
            limit=candidate_limit,
        )
        scored: list[RetrievedBehaviorMemory] = []
        for item in candidates:
            if not item.vector or item.status not in MEMORY_RETRIEVAL_STATUSES:
                continue
            score = self._score_long_term_memory(
                vector=item.vector,
                query_vector=query_vector,
                importance_score=item.importance_score,
                confidence_score=item.confidence_score,
                freshness_score=item.freshness_score,
                stability_score=item.stability_score,
                goal_relevance_score=item.goal_relevance_score,
                created_at=item.created_at,
            )
            scored.append(
                RetrievedBehaviorMemory(
                    memory_id=item.memory_id,
                    behavior_key=item.behavior_key,
                    behavior_category=item.behavior_category,
                    title=item.title,
                    summary=item.summary,
                    behavior_level=item.behavior_level,
                    time_horizon=item.time_horizon,
                    importance_score=item.importance_score,
                    confidence_score=item.confidence_score,
                    freshness_score=item.freshness_score,
                    stability_score=item.stability_score,
                    goal_relevance_score=item.goal_relevance_score,
                    status=item.status,
                    score=score,
                    created_at=item.created_at,
                )
            )
        scored.sort(key=lambda item: (item.score, item.importance_score, item.created_at), reverse=True)
        memories = [item for item in scored if item.score >= min_score][:limit]
        observe_memory_retrieval(
            memory_type="behavior",
            result_count=len(memories),
            candidate_count=len(candidates),
        )
        return BehaviorMemoryRetrievalResult(
            memories=memories,
            provider=self._embedding_provider.provider_name,
            model=self._embedding_provider.model_name,
            latency_ms=int((perf_counter() - started_at) * 1000),
            candidate_count=len(candidates),
        )

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

    async def describe_knowledge_memory(self, memory: KnowledgeMemory) -> dict[str, Any]:
        snapshot = await self._memory_quality_snapshot("knowledge", memory)
        return {**memory.__dict__, **snapshot}

    async def describe_behavior_memory(self, memory: BehaviorMemory) -> dict[str, Any]:
        snapshot = await self._memory_quality_snapshot("behavior", memory)
        return {**memory.__dict__, **snapshot}

    async def browse_knowledge_memories(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> BrowseMemoriesResult:
        if self._knowledge_memory_repository is None:
            return BrowseMemoriesResult(total=0, limit=limit, offset=offset, items=[])
        total = len(
            await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses=statuses,
            )
        )
        items = await self._knowledge_memory_repository.list_by_profile(
            learner_profile_id,
            learner_goal_id=learner_goal_id,
            statuses=statuses,
            limit=limit,
            offset=offset,
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
        if self._behavior_memory_repository is None:
            return BrowseMemoriesResult(total=0, limit=limit, offset=offset, items=[])
        total = len(
            await self._behavior_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses=statuses,
            )
        )
        items = await self._behavior_memory_repository.list_by_profile(
            learner_profile_id,
            learner_goal_id=learner_goal_id,
            statuses=statuses,
            limit=limit,
            offset=offset,
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
            self._conflict_member_detail(
                member=member,
                memory=memories.get((member.memory_type, member.memory_id)),
            )
            for member in members
        ]

    async def build_interpretation(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        limit_per_type: int = 8,
    ) -> MemoryInterpretationResult:
        knowledge = (
            await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses={"active", "stable", "candidate"},
                limit=limit_per_type * 2,
            )
            if self._knowledge_memory_repository is not None
            else []
        )
        behavior = (
            await self._behavior_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses={"active", "stable", "candidate"},
                limit=limit_per_type * 2,
            )
            if self._behavior_memory_repository is not None
            else []
        )
        conflicts = await self.list_conflict_sets(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            status="open",
            limit=20,
        )
        facts = [
            self._interpret_knowledge_memory(item)
            for item in knowledge
            if item.validation_status in {"validated", "locally_valid", "unverified"}
            and item.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD
        ][:limit_per_type]
        behavior_patterns = [
            self._interpret_behavior_memory(item)
            for item in behavior
            if item.validation_status in {"validated", "locally_valid", "unverified"}
            and item.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD
        ][:limit_per_type]
        contested_items = [
            self._interpret_knowledge_memory(item)
            for item in knowledge
            if item.validation_status == "contested" or item.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD
        ] + [
            self._interpret_behavior_memory(item)
            for item in behavior
            if item.validation_status == "contested" or item.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD
        ]
        constraints = self._interpretation_constraints(
            facts=facts,
            behavior_patterns=behavior_patterns,
            contested_items=contested_items,
            conflicts=conflicts,
        )
        return MemoryInterpretationResult(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            generated_at=datetime.now(timezone.utc),
            facts=facts,
            behavior_patterns=behavior_patterns,
            contested_items=contested_items[:limit_per_type],
            recommended_constraints=constraints,
            conflict_count=len(conflicts),
        )

    async def build_reflection_corpus(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        limit_per_type: int = 8,
    ) -> ReflectionCorpusResult:
        knowledge_items: list[ReflectionCorpusMemoryItem] = []
        behavior_items: list[ReflectionCorpusMemoryItem] = []

        if self._knowledge_memory_repository is not None:
            knowledge_memories = await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses={"candidate", "active", "stable", "archived"},
            )
            knowledge_items = [
                await self._build_reflection_corpus_item("knowledge", memory)
                for memory in knowledge_memories
                if learner_goal_id is None or memory.learner_goal_id == learner_goal_id
            ]

        if self._behavior_memory_repository is not None:
            behavior_memories = await self._behavior_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses={"candidate", "active", "stable", "archived"},
            )
            behavior_items = [
                await self._build_reflection_corpus_item("behavior", memory)
                for memory in behavior_memories
                if learner_goal_id is None or memory.learner_goal_id == learner_goal_id
            ]

        ranked_knowledge = sorted(
            knowledge_items,
            key=lambda item: (item.reflection_priority_score, item.updated_at),
            reverse=True,
        )[:limit_per_type]
        ranked_behavior = sorted(
            behavior_items,
            key=lambda item: (item.reflection_priority_score, item.updated_at),
            reverse=True,
        )[:limit_per_type]
        merged_items = sorted(
            ranked_knowledge + ranked_behavior,
            key=lambda item: (item.reflection_priority_score, item.updated_at),
            reverse=True,
        )
        summary = ReflectionCorpusSummary(
            total_items=len(merged_items),
            knowledge_items=len(ranked_knowledge),
            behavior_items=len(ranked_behavior),
            candidate_items=sum(1 for item in merged_items if item.status == "candidate"),
            stable_items=sum(1 for item in merged_items if item.status == "stable"),
            contradiction_focus_items=sum(1 for item in merged_items if item.recommended_action == "validate"),
            stale_focus_items=sum(1 for item in merged_items if item.recommended_action == "refresh"),
            validate_items=sum(1 for item in merged_items if item.recommended_action == "validate"),
            reinforce_items=sum(1 for item in merged_items if item.recommended_action == "reinforce"),
        )
        if self._audit_service is not None:
            await self._audit_service.record(
                event_type="memory.reflection_corpus.generated",
                resource_type="learner_profile",
                resource_id=learner_profile_id,
                actor="system",
                event_data={
                    "learner_profile_id": learner_profile_id,
                    "learner_goal_id": learner_goal_id,
                    "limit_per_type": limit_per_type,
                    "total_items": summary.total_items,
                    "knowledge_items": summary.knowledge_items,
                    "behavior_items": summary.behavior_items,
                    "validate_items": summary.validate_items,
                    "reinforce_items": summary.reinforce_items,
                },
            )
        return ReflectionCorpusResult(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            generated_at=datetime.now(timezone.utc),
            items=merged_items,
            summary=summary,
        )

    async def build_governance_summary(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
    ) -> MemoryGovernanceSummary:
        knowledge = (
            await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses=set(MEMORY_STATUSES),
            )
            if self._knowledge_memory_repository is not None
            else []
        )
        behavior = (
            await self._behavior_memory_repository.list_by_profile(
                learner_profile_id,
                learner_goal_id=learner_goal_id,
                statuses=set(MEMORY_STATUSES),
            )
            if self._behavior_memory_repository is not None
            else []
        )
        decisions = (
            await self._governance_decision_repository.list_by_profile(
                learner_profile_id=learner_profile_id,
                learner_goal_id=learner_goal_id,
                limit=100,
            )
            if self._governance_decision_repository is not None
            else []
        )
        all_memories = [*knowledge, *behavior]
        evidence_links = (
            await self._evidence_link_repository.list_by_profile(
                learner_profile_id=learner_profile_id,
                learner_goal_id=learner_goal_id,
                limit=200,
            )
            if self._evidence_link_repository is not None
            else []
        )
        quality_snapshots = [self._memory_quality_snapshot_sync(item) for item in all_memories]
        return MemoryGovernanceSummary(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            knowledge_total=len(knowledge),
            behavior_total=len(behavior),
            candidate_total=sum(1 for item in all_memories if item.status == "candidate"),
            active_total=sum(1 for item in all_memories if item.status == "active"),
            stable_total=sum(1 for item in all_memories if item.status == "stable"),
            archived_total=sum(1 for item in all_memories if item.status == "archived"),
            suppressed_total=sum(1 for item in all_memories if item.status == "suppressed"),
            contradiction_focus_total=sum(1 for item in all_memories if item.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD),
            stale_candidate_total=sum(
                1 for item in all_memories if item.status == "candidate" and item.freshness_score < 0.35
            ),
            high_priority_total=sum(1 for item in all_memories if self._reflection_priority_score(memory=item) >= 0.65),
            recent_promotions=sum(1 for item in decisions if item.decision_type == "promote"),
            recent_demotions=sum(1 for item in decisions if item.decision_type == "demote"),
            recent_archives=sum(1 for item in decisions if item.decision_type == "archive"),
            recent_compressions=sum(1 for item in decisions if item.decision_type == "compress"),
            promotion_candidate_total=sum(
                1 for item in knowledge if self._is_knowledge_promotion_candidate(item)
            )
            + sum(1 for item in behavior if self._is_behavior_promotion_candidate(item)),
            demotion_risk_total=sum(1 for item in all_memories if self._governance_pressure(item) >= 0.65),
            operator_review_recommended_total=sum(1 for item in all_memories if self._review_recommended(item)),
            reflection_bridge_total=sum(1 for item in evidence_links if item.evidence_source_type == "reflection_outcome"),
            high_quality_total=sum(1 for item in quality_snapshots if item["quality_tier"] == "high"),
            medium_quality_total=sum(1 for item in quality_snapshots if item["quality_tier"] == "medium"),
            ready_promotion_total=sum(1 for item in quality_snapshots if item["promotion_readiness"] == "ready"),
            weak_candidate_total=sum(
                1
                for memory, snapshot in zip(all_memories, quality_snapshots, strict=False)
                if memory.status == "candidate" and snapshot["quality_tier"] == "low"
            ),
            quality_tier_totals={
                "low": sum(1 for item in quality_snapshots if item["quality_tier"] == "low"),
                "medium": sum(1 for item in quality_snapshots if item["quality_tier"] == "medium"),
                "high": sum(1 for item in quality_snapshots if item["quality_tier"] == "high"),
            },
            topic_bucket_summary=self._topic_bucket_summary(all_memories),
        )

    async def suppress_memory(
        self,
        *,
        memory_type: str,
        memory_id: str,
        reason_code: str,
        note: str | None,
        actor_id: str,
    ) -> KnowledgeMemory | BehaviorMemory:
        return await self._apply_operator_status_change(
            memory_type=memory_type,
            memory_id=memory_id,
            new_status="suppressed",
            reason_code=reason_code,
            reason_note=note,
            actor_id=actor_id,
            decision_type="suppress",
        )

    async def restore_memory(
        self,
        *,
        memory_type: str,
        memory_id: str,
        restore_to_status: str,
        reason: str | None,
        actor_id: str,
    ) -> KnowledgeMemory | BehaviorMemory:
        if restore_to_status not in {"candidate", "active"}:
            raise ValidationError("restore_to_status must be candidate or active.")
        return await self._apply_operator_status_change(
            memory_type=memory_type,
            memory_id=memory_id,
            new_status=restore_to_status,
            reason_code="operator_restore",
            reason_note=reason,
            actor_id=actor_id,
            decision_type="restore",
        )

    async def annotate_memory(
        self,
        *,
        memory_type: str,
        memory_id: str,
        annotation_code: str,
        note: str,
        actor_id: str,
    ) -> MemoryAnnotation:
        if self._annotation_repository is None:
            raise ValidationError("annotation repository is not configured")
        annotation = MemoryAnnotation.build(
            memory_type=memory_type,
            memory_id=memory_id,
            annotation_code=annotation_code,
            note=note,
            created_by=actor_id,
        )
        await self._annotation_repository.create(annotation)
        if self._evidence_link_repository is not None:
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type=memory_type,
                    memory_id=memory_id,
                    learner_profile_id=(await self._get_memory(memory_type, memory_id)).learner_profile_id,
                    learner_goal_id=(await self._get_memory(memory_type, memory_id)).learner_goal_id,
                    evidence_source_type="operator_annotation",
                    evidence_source_id=annotation.id,
                    evidence_role=MemoryNormalizer.classify_evidence_role(
                        memory_type=memory_type,
                        evidence_source_type="operator_annotation",
                    ),
                    signal_type=annotation_code,
                    weight=0.1,
                    payload={"annotation_code": annotation_code},
                    observed_at=annotation.created_at,
                )
            )
        if self._audit_service is not None:
            await self._audit_service.record(
                event_type=f"{memory_type}_memory.annotated",
                resource_type=f"{memory_type}_memory",
                resource_id=memory_id,
                actor="operator",
                event_data={
                    "memory_id": memory_id,
                    "annotation_id": annotation.id,
                    "annotation_code": annotation.annotation_code,
                    "created_by": actor_id,
                },
            )
        return annotation

    async def run_memory_maintenance(self, *, batch_size: int = 5) -> MemoryMaintenanceResult:
        started_at = perf_counter()
        promoted_knowledge, demoted_knowledge = await self._refresh_and_govern_knowledge()
        promoted_behavior, demoted_behavior = await self._refresh_and_govern_behavior()
        await self.refresh_conflict_sets()
        compressed_knowledge_groups = await self.compress_knowledge_memories(batch_size=batch_size)
        compressed_behavior_groups = await self.compress_behavior_memories(batch_size=batch_size)
        await self.refresh_observability_metrics()
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

    async def run_knowledge_governance_batch(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        if self._knowledge_memory_repository is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        fetched = await self._knowledge_memory_repository.list_by_profile_after_id(
            learner_profile_id=learner_profile_id,
            statuses={"candidate", "active", "stable"},
            after_id=cursor,
            limit=max(batch_size, 1) + 1,
        )
        batch = fetched[: max(batch_size, 1)]
        promoted = 0
        demoted = 0
        refreshed_count = 0
        for memory in batch:
            refreshed = await self._refresh_knowledge_memory(memory)
            if refreshed.status != memory.status:
                if refreshed.status in {"active", "stable"} and memory.status in {"candidate", "active"}:
                    promoted += 1
                elif memory.status == "stable" and refreshed.status == "active":
                    demoted += 1
            elif self._has_material_refresh_change(memory, refreshed):
                refreshed_count += 1
        next_cursor = batch[-1].id if batch else cursor
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=promoted + demoted + refreshed_count,
            next_cursor=next_cursor,
            completed=len(fetched) <= max(batch_size, 1),
            metadata={
                "promoted": promoted,
                "demoted": demoted,
                "refreshed": refreshed_count,
            },
        )

    async def run_behavior_governance_batch(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        if self._behavior_memory_repository is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        fetched = await self._behavior_memory_repository.list_by_profile_after_id(
            learner_profile_id=learner_profile_id,
            statuses={"candidate", "active", "stable"},
            after_id=cursor,
            limit=max(batch_size, 1) + 1,
        )
        batch = fetched[: max(batch_size, 1)]
        promoted = 0
        demoted = 0
        refreshed_count = 0
        for memory in batch:
            refreshed = await self._refresh_behavior_memory(memory)
            if refreshed.status != memory.status:
                if refreshed.status in {"active", "stable"} and memory.status in {"candidate", "active"}:
                    promoted += 1
                elif memory.status == "stable" and refreshed.status == "active":
                    demoted += 1
            elif self._has_material_refresh_change(memory, refreshed):
                refreshed_count += 1
        next_cursor = batch[-1].id if batch else cursor
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=promoted + demoted + refreshed_count,
            next_cursor=next_cursor,
            completed=len(fetched) <= max(batch_size, 1),
            metadata={
                "promoted": promoted,
                "demoted": demoted,
                "refreshed": refreshed_count,
            },
        )

    async def compress_knowledge_memories_for_profile(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        if (
            self._knowledge_memory_repository is None
            or self._knowledge_memory_embedding_repository is None
            or self._embedding_provider is None
        ):
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        active_memories = await self._knowledge_memory_repository.list_by_profile(
            learner_profile_id,
            statuses={"active", "stable"},
        )
        embeddings = await self._knowledge_memory_embedding_repository.list_by_profile(
            learner_profile_id=learner_profile_id
        )
        embeddings_by_memory_id = {item.memory_id: item for item in embeddings}
        groups = sorted(
            self._cluster_knowledge_memories(active_memories),
            key=lambda group: min(item.id for item in group),
        )
        groups = [group for group in groups if cursor is None or min(item.id for item in group) > cursor]
        batch = groups[: max(batch_size, 1)]
        compressed_groups = 0
        next_cursor = cursor
        for group in batch:
            next_cursor = min(item.id for item in group)
            source_batch = sorted(group, key=lambda item: item.id)[: max(batch_size, 2)]
            sorted_group = sorted(source_batch, key=lambda item: (item.importance_score, item.updated_at), reverse=True)
            compressed_groups += await self._compress_knowledge_group(
                sorted_group,
                embeddings_by_memory_id=embeddings_by_memory_id,
            )
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=compressed_groups,
            next_cursor=next_cursor,
            completed=len(groups) <= max(batch_size, 1),
            metadata={"compressed_groups": compressed_groups},
        )

    async def compress_behavior_memories_for_profile(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        if (
            self._behavior_memory_repository is None
            or self._behavior_memory_embedding_repository is None
            or self._embedding_provider is None
        ):
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        active_memories = await self._behavior_memory_repository.list_by_profile(
            learner_profile_id,
            statuses={"active", "stable"},
        )
        embeddings = await self._behavior_memory_embedding_repository.list_by_profile(
            learner_profile_id=learner_profile_id
        )
        embeddings_by_memory_id = {item.memory_id: item for item in embeddings}
        groups = sorted(
            self._cluster_behavior_memories(active_memories),
            key=lambda group: min(item.id for item in group),
        )
        groups = [group for group in groups if cursor is None or min(item.id for item in group) > cursor]
        batch = groups[: max(batch_size, 1)]
        compressed_groups = 0
        next_cursor = cursor
        for group in batch:
            next_cursor = min(item.id for item in group)
            source_batch = sorted(group, key=lambda item: item.id)[: max(batch_size, 2)]
            sorted_group = sorted(source_batch, key=lambda item: (item.importance_score, item.updated_at), reverse=True)
            compressed_groups += await self._compress_behavior_group(
                sorted_group,
                embeddings_by_memory_id=embeddings_by_memory_id,
            )
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=compressed_groups,
            next_cursor=next_cursor,
            completed=len(groups) <= max(batch_size, 1),
            metadata={"compressed_groups": compressed_groups},
        )

    async def refresh_conflict_sets_for_profile(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        if self._conflict_repository is None:
            return MemoryMaintenanceBatchResult(processed_count=0, changed_count=0, next_cursor=None, completed=True)
        memory_by_ref, active_conflict_keys, written = await self._upsert_profile_conflict_sets(
            learner_profile_id=learner_profile_id
        )
        if hasattr(self._conflict_repository, "list_open_sets_by_profile_after_id"):
            fetched_sets = await self._conflict_repository.list_open_sets_by_profile_after_id(
                learner_profile_id=learner_profile_id,
                after_id=cursor,
                limit=max(batch_size, 1) + 1,
            )
        else:
            open_sets = await self._conflict_repository.list_sets_by_profile(
                learner_profile_id=learner_profile_id,
                status="open",
                limit=10000,
            )
            fetched_sets = [
                item
                for item in sorted(open_sets, key=lambda item: item.id)
                if cursor is None or item.id > cursor
            ][: max(batch_size, 1) + 1]
        batch = fetched_sets[: max(batch_size, 1)]
        closed = await self._close_inactive_conflict_sets(
            active_conflict_keys=active_conflict_keys,
            visible_memories=memory_by_ref,
            conflict_sets=batch,
        )
        await self.refresh_observability_metrics()
        next_cursor = batch[-1].id if batch else cursor
        return MemoryMaintenanceBatchResult(
            processed_count=len(batch),
            changed_count=written + closed,
            next_cursor=next_cursor,
            completed=len(fetched_sets) <= max(batch_size, 1),
            metadata={"written": written, "closed": closed},
        )

    async def refresh_conflict_sets(self) -> int:
        if self._conflict_repository is None:
            return 0
        profile_ids: set[str] = set()
        if self._knowledge_memory_repository is not None:
            profile_ids.update(
                await self._knowledge_memory_repository.list_profile_ids_with_statuses(
                    {"candidate", "active", "stable"}
                )
            )
        if self._behavior_memory_repository is not None:
            profile_ids.update(
                await self._behavior_memory_repository.list_profile_ids_with_statuses(
                    {"candidate", "active", "stable"}
                )
            )
        if hasattr(self._conflict_repository, "list_profile_ids_with_open_sets"):
            profile_ids.update(await self._conflict_repository.list_profile_ids_with_open_sets())
        else:
            profile_ids.update(item.learner_profile_id for item in await self._conflict_repository.list_open_sets())
        written = 0
        for learner_profile_id in sorted(profile_ids):
            memory_by_ref, active_conflict_keys, profile_written = await self._upsert_profile_conflict_sets(
                learner_profile_id=learner_profile_id
            )
            if hasattr(self._conflict_repository, "list_sets_by_profile"):
                conflict_sets = await self._conflict_repository.list_sets_by_profile(
                    learner_profile_id=learner_profile_id,
                    status="open",
                    limit=10000,
                )
            else:
                conflict_sets = [
                    item
                    for item in await self._conflict_repository.list_open_sets()
                    if item.learner_profile_id == learner_profile_id
                ]
            await self._close_inactive_conflict_sets(
                active_conflict_keys=active_conflict_keys,
                visible_memories=memory_by_ref,
                conflict_sets=conflict_sets,
            )
            written += profile_written
        await self.refresh_observability_metrics()
        return written

    async def _upsert_profile_conflict_sets(
        self,
        *,
        learner_profile_id: str,
    ) -> tuple[dict[tuple[str, str], KnowledgeMemory | BehaviorMemory], set[tuple[str, str | None, str, str]], int]:
        memories: list[KnowledgeMemory | BehaviorMemory] = []
        if self._knowledge_memory_repository is not None:
            memories.extend(
                await self._knowledge_memory_repository.list_by_profile(
                    learner_profile_id,
                    statuses={"candidate", "active", "stable"},
                )
            )
        if self._behavior_memory_repository is not None:
            memories.extend(
                await self._behavior_memory_repository.list_by_profile(
                    learner_profile_id,
                    statuses={"candidate", "active", "stable"},
                )
            )
        memory_by_ref: dict[tuple[str, str], KnowledgeMemory | BehaviorMemory] = {
            ("knowledge" if isinstance(memory, KnowledgeMemory) else "behavior", memory.id): memory
            for memory in memories
        }
        grouped: dict[tuple[str, str | None, str], list[KnowledgeMemory | BehaviorMemory]] = {}
        for memory in memories:
            if memory.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD:
                continue
            topic_key = getattr(memory, "knowledge_key", "") or getattr(memory, "behavior_key", "")
            grouped.setdefault((memory.learner_profile_id, memory.learner_goal_id, topic_key), []).append(memory)
        active_conflict_keys = {
            (learner_profile_id, learner_goal_id, topic_key, "contradictory_evidence")
            for learner_profile_id, learner_goal_id, topic_key in grouped
        }
        written = 0
        for (learner_profile_id, learner_goal_id, topic_key), items in grouped.items():
            severity = self._clamp_score(max(item.contradiction_score for item in items))
            decision = MemoryConflictPolicy.open_contradictory_evidence(
                topic_key=topic_key,
                current_memory_count=len(items),
                severity_score=severity,
            )
            conflict_set = MemoryConflictSet.build(
                learner_profile_id=learner_profile_id,
                learner_goal_id=learner_goal_id,
                topic_key=topic_key,
                conflict_type="contradictory_evidence",
                severity_score=severity,
                summary=f"Contradictory memory evidence for topic '{topic_key}'.",
                reason_code=decision.reason_code,
                reason_note=decision.reason_note,
                handling_result=decision.handling_result,
                status_impact=decision.status_impact,
            )
            members = [
                MemoryConflictMember.build(
                    conflict_set_id=conflict_set.id,
                    memory_type="knowledge" if isinstance(item, KnowledgeMemory) else "behavior",
                    memory_id=item.id,
                    memory_key=getattr(item, "knowledge_key", "") or getattr(item, "behavior_key", ""),
                    stance="contested",
                    support_score=item.support_score,
                    contradiction_score=item.contradiction_score,
                )
                for item in items
            ]
            _, created = await self._conflict_repository.upsert_set(conflict_set=conflict_set, members=members)
            observe_memory_conflict_event(
                conflict_type=conflict_set.conflict_type,
                event="created" if created else "refreshed",
                status=conflict_set.status,
            )
            written += 1
        return memory_by_ref, active_conflict_keys, written

    async def _close_inactive_conflict_sets(
        self,
        *,
        active_conflict_keys: set[tuple[str, str | None, str, str]],
        visible_memories: dict[tuple[str, str], KnowledgeMemory | BehaviorMemory],
        conflict_sets: list[MemoryConflictSet] | None = None,
    ) -> int:
        if self._conflict_repository is None:
            return 0
        closed_count = 0
        open_sets = conflict_sets if conflict_sets is not None else await self._conflict_repository.list_open_sets()
        for conflict_set in open_sets:
            conflict_key = (
                conflict_set.learner_profile_id,
                conflict_set.learner_goal_id,
                conflict_set.topic_key,
                conflict_set.conflict_type,
            )
            if conflict_key in active_conflict_keys:
                continue
            members = [
                item
                for item in await self._conflict_repository.list_members(conflict_set_id=conflict_set.id)
                if item.stance != "superseded"
            ]
            if not members:
                decision = MemoryConflictPolicy.close_no_current_members()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="stale",
                    summary=f"Conflict for topic '{conflict_set.topic_key}' became stale because it has no current members.",
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="stale",
                )
                closed_count += 1
                continue
            member_memories = [
                visible_memories.get((member.memory_type, member.memory_id))
                for member in members
            ]
            if any(memory is None for memory in member_memories):
                decision = MemoryConflictPolicy.close_member_not_visible()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="stale",
                    summary=(
                        f"Conflict for topic '{conflict_set.topic_key}' became stale because one or more "
                        "member memories are no longer visible."
                    ),
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="stale",
                )
                closed_count += 1
                continue
            if all(
                memory is not None and memory.contradiction_score < CONFLICT_CONTRADICTION_THRESHOLD
                for memory in member_memories
            ):
                decision = MemoryConflictPolicy.close_resolved_by_refresh()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="resolved",
                    summary=f"Conflict for topic '{conflict_set.topic_key}' resolved after contradiction fell below threshold.",
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="resolved",
                )
                closed_count += 1
            else:
                decision = MemoryConflictPolicy.close_inactive_refresh()
                await self._conflict_repository.close_open_set(
                    conflict_set_id=conflict_set.id,
                    status="stale",
                    summary=f"Conflict for topic '{conflict_set.topic_key}' became stale after refresh.",
                    reason_code=decision.reason_code,
                    reason_note=decision.reason_note,
                    handling_result=decision.handling_result,
                    status_impact=decision.status_impact,
                )
                observe_memory_conflict_event(
                    conflict_type=conflict_set.conflict_type,
                    event="closed",
                    status="stale",
                )
                closed_count += 1
        return closed_count

    @staticmethod
    def _conflict_member_detail(
        *,
        member: MemoryConflictMember,
        memory: KnowledgeMemory | BehaviorMemory | None,
    ) -> MemoryConflictMemberDetail:
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

    async def bridge_reflection_outcome(
        self,
        *,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
    ) -> int:
        topic_key = self._topic_key_from_reflection(reflection)
        if topic_key is None:
            return 0
        knowledge_memories = []
        behavior_memories = []
        if self._knowledge_memory_repository is not None:
            knowledge_memories = [
                item
                for item in await self._knowledge_memory_repository.list_by_profile(
                    reflection.learner_profile_id,
                    learner_goal_id=reflection.learner_goal_id,
                    statuses={"candidate", "active", "stable"},
                )
                if self._topic_alignment_score(
                    topic_key,
                    item.knowledge_key,
                    title=item.title,
                    tags=item.tags,
                    extras=item.prerequisite_keys,
                )
                >= 0.55
            ]
        if self._behavior_memory_repository is not None:
            behavior_memories = [
                item
                for item in await self._behavior_memory_repository.list_by_profile(
                    reflection.learner_profile_id,
                    learner_goal_id=reflection.learner_goal_id,
                    statuses={"candidate", "active", "stable"},
                )
                if self._topic_alignment_score(
                    topic_key,
                    item.behavior_key,
                    title=item.title,
                    tags=item.tags,
                    extras=[item.behavior_category, item.intervention_effect or ""],
                )
                >= 0.45
            ]
        updates = 0
        for memory in knowledge_memories:
            await self._upsert_reflection_bridge_evidence(
                memory_type="knowledge",
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                reflection=reflection,
                evaluation=evaluation,
            )
            observe_memory_reflection_bridge(memory_type="knowledge", evaluation_status=evaluation.evaluation_status)
            updates += 1
        for memory in behavior_memories:
            await self._upsert_reflection_bridge_evidence(
                memory_type="behavior",
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                reflection=reflection,
                evaluation=evaluation,
            )
            observe_memory_reflection_bridge(memory_type="behavior", evaluation_status=evaluation.evaluation_status)
            updates += 1
        return updates

    async def compress_knowledge_memories(self, *, batch_size: int = 5) -> int:
        if (
            self._knowledge_memory_repository is None
            or self._knowledge_memory_embedding_repository is None
            or self._embedding_provider is None
        ):
            return 0
        compressed_groups = 0
        profile_ids = await self._knowledge_memory_repository.list_profile_ids_with_active_memories()
        for learner_profile_id in profile_ids:
            active_memories = await self._knowledge_memory_repository.list_by_profile(
                learner_profile_id,
                statuses={"active", "stable"},
            )
            if len(active_memories) < 2:
                continue
            embeddings = await self._knowledge_memory_embedding_repository.list_by_profile(
                learner_profile_id=learner_profile_id
            )
            embeddings_by_memory_id = {item.memory_id: item for item in embeddings}
            for group in self._cluster_knowledge_memories(active_memories):
                if len(group) < 2:
                    continue
                group = sorted(group, key=lambda item: (item.importance_score, item.updated_at), reverse=True)[:batch_size]
                compressed_groups += await self._compress_knowledge_group(
                    group,
                    embeddings_by_memory_id=embeddings_by_memory_id,
                )
        return compressed_groups

    async def compress_behavior_memories(self, *, batch_size: int = 5) -> int:
        if (
            self._behavior_memory_repository is None
            or self._behavior_memory_embedding_repository is None
            or self._embedding_provider is None
        ):
            return 0
        compressed_groups = 0
        profile_ids = await self._behavior_memory_repository.list_profile_ids_with_active_memories()
        for learner_profile_id in profile_ids:
            active_memories = await self._behavior_memory_repository.list_by_profile(
                learner_profile_id,
                statuses={"active", "stable"},
            )
            if len(active_memories) < 2:
                continue
            embeddings = await self._behavior_memory_embedding_repository.list_by_profile(
                learner_profile_id=learner_profile_id
            )
            embeddings_by_memory_id = {item.memory_id: item for item in embeddings}
            for group in self._cluster_behavior_memories(active_memories):
                if len(group) < 2:
                    continue
                group = sorted(group, key=lambda item: (item.importance_score, item.updated_at), reverse=True)[:batch_size]
                compressed_groups += await self._compress_behavior_group(
                    group,
                    embeddings_by_memory_id=embeddings_by_memory_id,
                )
        return compressed_groups

    async def _compress_knowledge_group(
        self,
        group: list[KnowledgeMemory],
        *,
        embeddings_by_memory_id: dict[str, KnowledgeMemoryEmbeddingRecord],
    ) -> int:
        if (
            len(group) < 2
            or self._knowledge_memory_repository is None
            or self._knowledge_memory_embedding_repository is None
            or self._embedding_provider is None
        ):
            return 0
        compressed = self._build_compressed_knowledge_memory(group)
        compressed_vector = (await self._embedding_provider.embed_texts([compressed.summary]))[0]
        await self._knowledge_memory_repository.create(compressed.with_status("compressed"))
        for source in group:
            await self._knowledge_memory_repository.update(source.with_compression(compressed_into_id=compressed.id))
            source_embedding = embeddings_by_memory_id.get(source.id)
            if source_embedding is not None:
                await self._knowledge_memory_embedding_repository.update(
                    KnowledgeMemoryEmbeddingRecord(
                        id=source_embedding.id,
                        memory_id=source_embedding.memory_id,
                        learner_profile_id=source_embedding.learner_profile_id,
                        learner_goal_id=source_embedding.learner_goal_id,
                        knowledge_key=source_embedding.knowledge_key,
                        title=source_embedding.title,
                        summary=source_embedding.summary,
                        knowledge_level=source_embedding.knowledge_level,
                        time_horizon=source_embedding.time_horizon,
                        importance_score=source_embedding.importance_score,
                        confidence_score=source_embedding.confidence_score,
                        freshness_score=source_embedding.freshness_score,
                        stability_score=source_embedding.stability_score,
                        goal_relevance_score=source_embedding.goal_relevance_score,
                        scope_type=source_embedding.scope_type,
                        provider=source_embedding.provider,
                        model=source_embedding.model,
                        dimensions=source_embedding.dimensions,
                        vector=source_embedding.vector,
                        status="compressed",
                        created_at=source_embedding.created_at,
                    )
                )
        await self._knowledge_memory_repository.update(compressed)
        await self._knowledge_memory_embedding_repository.create(
            KnowledgeMemoryEmbeddingRecord.build(
                memory_id=compressed.id,
                learner_profile_id=compressed.learner_profile_id,
                learner_goal_id=compressed.learner_goal_id,
                knowledge_key=compressed.knowledge_key,
                title=compressed.title,
                summary=compressed.summary,
                knowledge_level=compressed.knowledge_level,
                time_horizon=compressed.time_horizon,
                importance_score=compressed.importance_score,
                confidence_score=compressed.confidence_score,
                freshness_score=compressed.freshness_score,
                stability_score=compressed.stability_score,
                goal_relevance_score=compressed.goal_relevance_score,
                scope_type=compressed.scope_type,
                provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name,
                vector=compressed_vector,
                status=compressed.status,
            )
        )
        await self._record_governance_decision(
            memory_type="knowledge",
            memory_id=compressed.id,
            previous_status=None,
            new_status=compressed.status,
            decision_type="compress",
            trigger_source="compression_cycle",
            actor_type="system",
            actor_id="worker",
            reason_code="memory_cluster_compressed",
            reason_note=None,
            metrics_snapshot={"source_count": len(group)},
        )
        return 1

    async def _compress_behavior_group(
        self,
        group: list[BehaviorMemory],
        *,
        embeddings_by_memory_id: dict[str, BehaviorMemoryEmbeddingRecord],
    ) -> int:
        if (
            len(group) < 2
            or self._behavior_memory_repository is None
            or self._behavior_memory_embedding_repository is None
            or self._embedding_provider is None
        ):
            return 0
        compressed = self._build_compressed_behavior_memory(group)
        compressed_vector = (await self._embedding_provider.embed_texts([compressed.summary]))[0]
        await self._behavior_memory_repository.create(compressed.with_status("compressed"))
        for source in group:
            await self._behavior_memory_repository.update(source.with_compression(compressed_into_id=compressed.id))
            source_embedding = embeddings_by_memory_id.get(source.id)
            if source_embedding is not None:
                await self._behavior_memory_embedding_repository.update(
                    BehaviorMemoryEmbeddingRecord(
                        id=source_embedding.id,
                        memory_id=source_embedding.memory_id,
                        learner_profile_id=source_embedding.learner_profile_id,
                        learner_goal_id=source_embedding.learner_goal_id,
                        behavior_key=source_embedding.behavior_key,
                        behavior_category=source_embedding.behavior_category,
                        title=source_embedding.title,
                        summary=source_embedding.summary,
                        behavior_level=source_embedding.behavior_level,
                        time_horizon=source_embedding.time_horizon,
                        importance_score=source_embedding.importance_score,
                        confidence_score=source_embedding.confidence_score,
                        freshness_score=source_embedding.freshness_score,
                        stability_score=source_embedding.stability_score,
                        goal_relevance_score=source_embedding.goal_relevance_score,
                        scope_type=source_embedding.scope_type,
                        provider=source_embedding.provider,
                        model=source_embedding.model,
                        dimensions=source_embedding.dimensions,
                        vector=source_embedding.vector,
                        status="compressed",
                        created_at=source_embedding.created_at,
                    )
                )
        await self._behavior_memory_repository.update(compressed)
        await self._behavior_memory_embedding_repository.create(
            BehaviorMemoryEmbeddingRecord.build(
                memory_id=compressed.id,
                learner_profile_id=compressed.learner_profile_id,
                learner_goal_id=compressed.learner_goal_id,
                behavior_key=compressed.behavior_key,
                behavior_category=compressed.behavior_category,
                title=compressed.title,
                summary=compressed.summary,
                behavior_level=compressed.behavior_level,
                time_horizon=compressed.time_horizon,
                importance_score=compressed.importance_score,
                confidence_score=compressed.confidence_score,
                freshness_score=compressed.freshness_score,
                stability_score=compressed.stability_score,
                goal_relevance_score=compressed.goal_relevance_score,
                scope_type=compressed.scope_type,
                provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name,
                vector=compressed_vector,
                status=compressed.status,
            )
        )
        await self._record_governance_decision(
            memory_type="behavior",
            memory_id=compressed.id,
            previous_status=None,
            new_status=compressed.status,
            decision_type="compress",
            trigger_source="compression_cycle",
            actor_type="system",
            actor_id="worker",
            reason_code="memory_cluster_compressed",
            reason_note=None,
            metrics_snapshot={"source_count": len(group)},
        )
        return 1

    async def _retrieve_memory_events(
        self,
        *,
        query_text: str,
        candidate_limit: int,
        min_score: float,
        limit: int,
        fetch,
        filter_scope: str | None,
    ) -> MemoryRetrievalResult:
        if self._embedding_provider is None or self._embedding_repository is None:
            return MemoryRetrievalResult(memories=[], provider=None, model=None, latency_ms=0, candidate_count=0)
        started_at = perf_counter()
        query_vectors = await self._embedding_provider.embed_texts([query_text])
        if not query_vectors:
            return MemoryRetrievalResult(
                memories=[],
                provider=self._embedding_provider.provider_name,
                model=self._embedding_provider.model_name,
                latency_ms=int((perf_counter() - started_at) * 1000),
                candidate_count=0,
            )
        candidates = await fetch()
        query_vector = query_vectors[0]
        scored = [
            RetrievedMemory(
                memory_event_id=item.memory_event_id,
                summary=item.summary,
                memory_scope=item.memory_scope,
                memory_level=item.memory_level,
                progress_note=None,
                struggle_note=None,
                concept_focus=None,
                score=self._cosine_similarity(query_vector, item.vector),
                created_at=item.created_at,
            )
            for item in candidates
            if item.vector and (filter_scope is None or item.memory_scope == filter_scope)
        ]
        scored.sort(key=lambda item: (item.score, item.created_at), reverse=True)
        return MemoryRetrievalResult(
            memories=[item for item in scored if item.score >= min_score][:limit],
            provider=self._embedding_provider.provider_name,
            model=self._embedding_provider.model_name,
            latency_ms=int((perf_counter() - started_at) * 1000),
            candidate_count=len(candidates),
        )

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

    async def _refresh_and_govern_knowledge(self) -> tuple[int, int]:
        if self._knowledge_memory_repository is None:
            return (0, 0)
        promoted = 0
        demoted = 0
        for profile_id in await self._knowledge_memory_repository.list_profile_ids_with_statuses({"candidate", "active", "stable"}):
            memories = await self._knowledge_memory_repository.list_by_profile(
                profile_id,
                statuses={"candidate", "active", "stable"},
            )
            for memory in memories:
                refreshed = await self._refresh_knowledge_memory(memory)
                if refreshed.status != memory.status:
                    if refreshed.status in {"active", "stable"} and memory.status in {"candidate", "active"}:
                        promoted += 1
                    elif memory.status == "stable" and refreshed.status == "active":
                        demoted += 1
        return (promoted, demoted)

    async def _refresh_and_govern_behavior(self) -> tuple[int, int]:
        if self._behavior_memory_repository is None:
            return (0, 0)
        promoted = 0
        demoted = 0
        for profile_id in await self._behavior_memory_repository.list_profile_ids_with_statuses({"candidate", "active", "stable"}):
            memories = await self._behavior_memory_repository.list_by_profile(
                profile_id,
                statuses={"candidate", "active", "stable"},
            )
            for memory in memories:
                refreshed = await self._refresh_behavior_memory(memory)
                if refreshed.status != memory.status:
                    if refreshed.status in {"active", "stable"} and memory.status in {"candidate", "active"}:
                        promoted += 1
                    elif memory.status == "stable" and refreshed.status == "active":
                        demoted += 1
        return (promoted, demoted)

    async def _refresh_knowledge_memory(self, memory: KnowledgeMemory) -> KnowledgeMemory:
        attempts = await self._list_relevant_attempts(memory.learner_goal_id, memory.knowledge_key)
        mastery = await self._get_relevant_mastery(memory.learner_goal_id, memory.knowledge_key)
        events = await self._list_relevant_events(memory.learner_profile_id, memory.knowledge_key)
        await self._sync_knowledge_evidence_links(memory=memory, attempts=attempts, mastery=mastery, events=events)
        support_score, contradiction_score, evidence_count, contradiction_count, assessment_count, task_count = (
            self._compute_knowledge_evidence(memory, attempts, mastery, events)
        )
        refreshed_importance = self._adjust_knowledge_importance(
            memory=memory,
            support_score=support_score,
            contradiction_score=contradiction_score,
            assessment_count=assessment_count,
        )
        refreshed_confidence = self._adjust_knowledge_confidence(
            memory=memory,
            evidence_count=evidence_count,
            contradiction_count=contradiction_count,
            mastery=mastery,
        )
        multiplier = self._knowledge_governance_multiplier(memory=memory, mastery=mastery, attempts=attempts)
        refreshed_importance = self._clamp_score(refreshed_importance * multiplier)
        refreshed_confidence = self._clamp_score(refreshed_confidence * multiplier)
        stability_score = self._compute_knowledge_stability(
            confidence_score=refreshed_confidence,
            support_score=support_score,
            contradiction_score=contradiction_score,
            freshness_score=memory.freshness_score,
            goal_relevance_score=memory.goal_relevance_score,
            assessment_count=assessment_count,
        )
        refreshed = memory.with_status(
            memory.status,
            support_score=support_score,
            contradiction_score=contradiction_score,
            evidence_count=evidence_count,
            contradiction_count=contradiction_count,
            stability_score=stability_score,
            assessment_evidence_count=assessment_count,
            task_evidence_count=task_count,
            importance_score=refreshed_importance,
            confidence_score=refreshed_confidence,
            last_reviewed_at=datetime.now(timezone.utc),
            last_supported_at=datetime.now(timezone.utc) if evidence_count > 0 else memory.last_supported_at,
            last_contradicted_at=datetime.now(timezone.utc) if contradiction_count > 0 else memory.last_contradicted_at,
            freshness_score=self._decay_freshness(memory.freshness_score, memory.updated_at, memory.time_horizon, memory.knowledge_level),
            validation_status=self._validation_status_for_memory(
                contradiction_score=contradiction_score,
                freshness_score=memory.freshness_score,
                evidence_count=evidence_count,
                support_score=support_score,
                scope_type=memory.scope_type,
            ),
        )
        next_status = self._govern_knowledge_status(refreshed)
        if next_status != refreshed.status:
            updated = refreshed.with_status(
                next_status,
                promotion_state_changed_at=datetime.now(timezone.utc),
                promotion_rationale=self._promotion_rationale(updated_status=next_status, memory=refreshed),
            )
            await self._knowledge_memory_repository.update(updated)
            await self._sync_knowledge_embedding(updated)
            await self._record_governance_decision(
                memory_type="knowledge",
                memory_id=updated.id,
                previous_status=memory.status,
                new_status=updated.status,
                decision_type=self._decision_type_for_transition(memory.status, updated.status),
                trigger_source="promotion_cycle" if updated.status in {"active", "stable"} else "decay_cycle",
                actor_type="system",
                actor_id="worker",
                reason_code="knowledge_governance_cycle",
                reason_note=None,
                metrics_snapshot=self._metrics_snapshot(updated),
            )
            return updated
        await self._knowledge_memory_repository.update(refreshed)
        await self._sync_knowledge_embedding(refreshed)
        if self._has_material_refresh_change(memory, refreshed):
            await self._record_governance_decision(
                memory_type="knowledge",
                memory_id=refreshed.id,
                previous_status=memory.status,
                new_status=refreshed.status,
                decision_type="refresh",
                trigger_source="evidence_refresh" if refreshed.evidence_count > 0 or refreshed.contradiction_count > 0 else "decay_cycle",
                actor_type="system",
                actor_id="worker",
                reason_code="knowledge_governance_refresh",
                reason_note=None,
                metrics_snapshot=self._metrics_snapshot(refreshed),
            )
        return refreshed

    async def _refresh_behavior_memory(self, memory: BehaviorMemory) -> BehaviorMemory:
        attempts = await self._list_relevant_attempts(memory.learner_goal_id, memory.behavior_key)
        events = await self._list_relevant_events(memory.learner_profile_id, memory.behavior_key)
        await self._sync_behavior_evidence_links(memory=memory, attempts=attempts, events=events)
        support_score, contradiction_score, evidence_count, contradiction_count, recurrence_count = (
            self._compute_behavior_evidence(memory, attempts, events)
        )
        refreshed_importance = self._adjust_behavior_importance(
            memory=memory,
            support_score=support_score,
            contradiction_score=contradiction_score,
            recurrence_count=recurrence_count,
        )
        refreshed_confidence = self._adjust_behavior_confidence(
            memory=memory,
            evidence_count=evidence_count,
            contradiction_count=contradiction_count,
            recurrence_count=recurrence_count,
        )
        multiplier = self._behavior_governance_multiplier(memory=memory, attempts=attempts)
        refreshed_importance = self._clamp_score(refreshed_importance * multiplier)
        refreshed_confidence = self._clamp_score(refreshed_confidence * multiplier)
        stability_score = self._compute_behavior_stability(
            confidence_score=refreshed_confidence,
            support_score=support_score,
            contradiction_score=contradiction_score,
            freshness_score=memory.freshness_score,
            goal_relevance_score=memory.goal_relevance_score,
            recurrence_count=recurrence_count,
            intervention_success_count=memory.intervention_success_count,
            intervention_failure_count=memory.intervention_failure_count,
        )
        refreshed = memory.with_status(
            memory.status,
            support_score=support_score,
            contradiction_score=contradiction_score,
            evidence_count=evidence_count,
            contradiction_count=contradiction_count,
            stability_score=stability_score,
            cross_session_recurrence_count=recurrence_count,
            importance_score=refreshed_importance,
            confidence_score=refreshed_confidence,
            last_reviewed_at=datetime.now(timezone.utc),
            last_supported_at=datetime.now(timezone.utc) if evidence_count > 0 else memory.last_supported_at,
            last_contradicted_at=datetime.now(timezone.utc) if contradiction_count > 0 else memory.last_contradicted_at,
            freshness_score=self._decay_freshness(memory.freshness_score, memory.updated_at, memory.time_horizon, memory.behavior_level),
            validation_status=self._validation_status_for_memory(
                contradiction_score=contradiction_score,
                freshness_score=memory.freshness_score,
                evidence_count=evidence_count,
                support_score=support_score,
                scope_type=memory.scope_type,
            ),
        )
        next_status = self._govern_behavior_status(refreshed)
        if next_status != refreshed.status:
            updated = refreshed.with_status(
                next_status,
                promotion_state_changed_at=datetime.now(timezone.utc),
                promotion_rationale=self._promotion_rationale(updated_status=next_status, memory=refreshed),
            )
            await self._behavior_memory_repository.update(updated)
            await self._sync_behavior_embedding(updated)
            await self._record_governance_decision(
                memory_type="behavior",
                memory_id=updated.id,
                previous_status=memory.status,
                new_status=updated.status,
                decision_type=self._decision_type_for_transition(memory.status, updated.status),
                trigger_source="promotion_cycle" if updated.status in {"active", "stable"} else "decay_cycle",
                actor_type="system",
                actor_id="worker",
                reason_code="behavior_governance_cycle",
                reason_note=None,
                metrics_snapshot=self._metrics_snapshot(updated),
            )
            return updated
        await self._behavior_memory_repository.update(refreshed)
        await self._sync_behavior_embedding(refreshed)
        if self._has_material_refresh_change(memory, refreshed):
            await self._record_governance_decision(
                memory_type="behavior",
                memory_id=refreshed.id,
                previous_status=memory.status,
                new_status=refreshed.status,
                decision_type="refresh",
                trigger_source="evidence_refresh" if refreshed.evidence_count > 0 or refreshed.contradiction_count > 0 else "decay_cycle",
                actor_type="system",
                actor_id="worker",
                reason_code="behavior_governance_refresh",
                reason_note=None,
                metrics_snapshot=self._metrics_snapshot(refreshed),
            )
        return refreshed

    async def _sync_knowledge_embedding(self, memory: KnowledgeMemory) -> None:
        if self._knowledge_memory_embedding_repository is None:
            return
        embedding = await self._knowledge_memory_embedding_repository.get_by_memory_id(memory.id)
        if embedding is None:
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

    async def _sync_behavior_embedding(self, memory: BehaviorMemory) -> None:
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

    async def _sync_knowledge_evidence_links(
        self,
        *,
        memory: KnowledgeMemory,
        attempts: list[TaskAttempt],
        mastery: LearnerTopicMastery | None,
        events: list[MemoryEvent],
    ) -> None:
        if self._evidence_link_repository is None:
            return
        for attempt in attempts:
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
            )
            weight = (
                KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_assessment_link
                if attempt.task_type == "assessment"
                else KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_default_link
            )
            if attempt.outcome_status == "completed" and attempt.task_type in {"practice", "review"}:
                weight = KNOWLEDGE_EVIDENCE_WEIGHTS.completed_practice_or_review_link
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="knowledge",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="task_attempt",
                    evidence_source_id=attempt.id,
                    evidence_role=evidence_role,
                    signal_type=f"{attempt.task_type}:{attempt.outcome_status}",
                    weight=weight,
                    payload={
                        "task_type": attempt.task_type,
                        "outcome_status": attempt.outcome_status,
                        "score": attempt.score,
                        "result_note": attempt.result_note,
                    },
                    observed_at=attempt.created_at,
                )
            )
        if mastery is not None:
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="knowledge",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="topic_mastery",
                    evidence_source_id=mastery.id,
                    evidence_role=MemoryNormalizer.classify_evidence_role(
                        memory_type="knowledge",
                        evidence_source_type="topic_mastery",
                    ),
                    signal_type="mastery_refresh",
                    weight=self._clamp_score(mastery.confidence),
                    payload={
                        "topic_key": mastery.topic_key,
                        "mastery_score": mastery.mastery_score,
                        "confidence": mastery.confidence,
                        "evidence_count": mastery.evidence_count,
                        "last_attempt_status": mastery.last_attempt_status,
                    },
                    observed_at=mastery.updated_at,
                )
            )
        for event in events:
            if event.memory_scope != "profile":
                continue
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="knowledge",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="session_memory_event",
                    evidence_source_id=event.id,
                    evidence_role=evidence_role,
                    signal_type=event.event_type,
                    weight=0.1 if event.progress_note is not None else 0.08 if event.struggle_note is not None else 0.05,
                    payload={
                        "memory_scope": event.memory_scope,
                        "memory_level": event.memory_level,
                        "summary": event.summary,
                        "concept_focus": event.concept_focus,
                    },
                    observed_at=event.created_at,
                )
            )

    async def _sync_behavior_evidence_links(
        self,
        *,
        memory: BehaviorMemory,
        attempts: list[TaskAttempt],
        events: list[MemoryEvent],
    ) -> None:
        if self._evidence_link_repository is None:
            return
        for attempt in attempts:
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
            )
            weight = (
                BEHAVIOR_EVIDENCE_WEIGHTS.failed_or_skipped_task_link
                if attempt.outcome_status in {"failed", "skipped"}
                else BEHAVIOR_EVIDENCE_WEIGHTS.completed_task_link
            )
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="behavior",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="task_attempt",
                    evidence_source_id=attempt.id,
                    evidence_role=evidence_role,
                    signal_type=f"{attempt.task_type}:{attempt.outcome_status}",
                    weight=weight,
                    payload={
                        "task_type": attempt.task_type,
                        "outcome_status": attempt.outcome_status,
                        "score": attempt.score,
                        "result_note": attempt.result_note,
                    },
                    observed_at=attempt.created_at,
                )
            )
        for event in events:
            if event.memory_scope != "profile":
                continue
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            await self._evidence_link_repository.upsert(
                MemoryEvidenceLink.build(
                    memory_type="behavior",
                    memory_id=memory.id,
                    learner_profile_id=memory.learner_profile_id,
                    learner_goal_id=memory.learner_goal_id,
                    evidence_source_type="session_memory_event",
                    evidence_source_id=event.id,
                    evidence_role=evidence_role,
                    signal_type=event.event_type,
                    weight=0.12 if event.struggle_note is not None else 0.06,
                    payload={
                        "memory_scope": event.memory_scope,
                        "memory_level": event.memory_level,
                        "summary": event.summary,
                        "concept_focus": event.concept_focus,
                    },
                    observed_at=event.created_at,
                )
            )

    async def upsert_session_memory_event_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        event: MemoryEvent,
    ) -> None:
        if self._evidence_link_repository is None:
            return
        if memory_type == "knowledge":
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            weight = (
                KNOWLEDGE_EVIDENCE_WEIGHTS.progress_event
                if event.progress_note is not None
                else KNOWLEDGE_EVIDENCE_WEIGHTS.struggle_event
                if event.struggle_note is not None
                else KNOWLEDGE_EVIDENCE_WEIGHTS.neutral_event_refresh
            )
        else:
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="session_memory_event",
                has_progress=event.progress_note is not None,
                has_struggle=event.struggle_note is not None,
            )
            weight = (
                BEHAVIOR_EVIDENCE_WEIGHTS.struggle_event_link
                if event.struggle_note is not None
                else BEHAVIOR_EVIDENCE_WEIGHTS.neutral_event_link
            )
        await self._evidence_link_repository.upsert(
            MemoryEvidenceLink.build(
                memory_type=memory_type,
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                evidence_source_type="session_memory_event",
                evidence_source_id=event.id,
                evidence_role=evidence_role,
                signal_type=event.event_type,
                weight=weight,
                payload={
                    "memory_scope": event.memory_scope,
                    "memory_level": event.memory_level,
                    "summary": event.summary,
                    "concept_focus": event.concept_focus,
                    "source_message_id": event.source_message_id,
                },
                observed_at=event.created_at,
            )
        )

    async def upsert_task_attempt_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        attempt: TaskAttempt,
    ) -> None:
        if self._evidence_link_repository is None:
            return
        if memory_type == "knowledge":
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="knowledge",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
            )
            weight = (
                KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_assessment_link
                if attempt.task_type == "assessment"
                else KNOWLEDGE_EVIDENCE_WEIGHTS.task_attempt_default_link
            )
        else:
            evidence_role = MemoryNormalizer.classify_evidence_role(
                memory_type="behavior",
                evidence_source_type="task_attempt",
                outcome_status=attempt.outcome_status,
            )
            weight = (
                BEHAVIOR_EVIDENCE_WEIGHTS.failed_or_skipped_task_link
                if attempt.outcome_status in {"failed", "skipped"}
                else BEHAVIOR_EVIDENCE_WEIGHTS.completed_task_link
            )
        await self._evidence_link_repository.upsert(
            MemoryEvidenceLink.build(
                memory_type=memory_type,
                memory_id=memory.id,
                learner_profile_id=memory.learner_profile_id,
                learner_goal_id=memory.learner_goal_id,
                evidence_source_type="task_attempt",
                evidence_source_id=attempt.id,
                evidence_role=evidence_role,
                signal_type=f"{attempt.task_type}:{attempt.outcome_status}",
                weight=weight,
                payload={
                    "task_type": attempt.task_type,
                    "outcome_status": attempt.outcome_status,
                    "score": attempt.score,
                    "result_note": attempt.result_note,
                    "daily_task_id": attempt.daily_task_id,
                    "workflow_run_id": attempt.workflow_run_id,
                },
                observed_at=attempt.created_at,
            )
        )

    async def upsert_reflection_outcome_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
    ) -> None:
        await self._upsert_reflection_bridge_evidence(
            memory_type=memory_type,
            memory_id=memory.id,
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            reflection=reflection,
            evaluation=evaluation,
        )

    async def _list_relevant_attempts(self, learner_goal_id: str | None, topic_key: str) -> list[TaskAttempt]:
        if learner_goal_id is None or self._task_attempt_repository is None:
            return []
        attempts = await self._task_attempt_repository.list_recent_by_goal(learner_goal_id, limit=50)
        return [
            item
            for item in attempts
            if self._topic_alignment_score(
                topic_key,
                item.topic_focus,
                title=item.result_note,
                tags=[item.task_type],
                extras=None,
            )
            >= 0.45
        ]

    async def _get_relevant_mastery(self, learner_goal_id: str | None, topic_key: str) -> LearnerTopicMastery | None:
        if learner_goal_id is None or self._learner_topic_mastery_repository is None:
            return None
        return await self._learner_topic_mastery_repository.get_by_goal_and_topic(learner_goal_id, topic_key)

    async def _list_relevant_events(self, learner_profile_id: str, topic_key: str) -> list[MemoryEvent]:
        since = datetime.now(timezone.utc) - timedelta(days=90)
        events = await self._repository.list_by_profile_since(learner_profile_id=learner_profile_id, since=since)
        return [
            item
            for item in events
            if self._topic_alignment_score(
                topic_key,
                item.concept_focus or item.summary,
                title=item.summary,
                tags=item.tags,
                extras=None,
            )
            >= 0.45
        ]

    def _compute_knowledge_evidence(
        self,
        memory: KnowledgeMemory,
        attempts: list[TaskAttempt],
        mastery: LearnerTopicMastery | None,
        events: list[MemoryEvent],
    ) -> tuple[float, float, int, int, int, int]:
        support_score = 0.0
        contradiction_score = 0.0
        evidence_count = 0
        contradiction_count = 0
        assessment_count = 0
        task_count = 0
        for attempt in attempts:
            if attempt.outcome_status == "completed":
                if attempt.task_type == "assessment":
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.completed_assessment
                    assessment_count += 1
                elif attempt.task_type in {"practice", "review"}:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.completed_practice_or_review
                else:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.completed_other_task
                evidence_count += 1
                task_count += 1
            elif attempt.outcome_status == "failed":
                contradiction_score += (
                    KNOWLEDGE_EVIDENCE_WEIGHTS.failed_assessment
                    if attempt.task_type == "assessment"
                    else KNOWLEDGE_EVIDENCE_WEIGHTS.failed_other_task
                )
                contradiction_count += 1
                task_count += 1
        for event in events:
            if event.memory_scope == "profile":
                if event.progress_note is not None:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.progress_event
                    evidence_count += 1
                if event.struggle_note is not None:
                    contradiction_score += KNOWLEDGE_EVIDENCE_WEIGHTS.struggle_event
                    contradiction_count += 1
                if event.progress_note is None and event.struggle_note is None:
                    support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.neutral_event_refresh
                    evidence_count += 1
        if mastery is not None:
            if mastery.mastery_score >= 0.7 and mastery.confidence >= 0.6:
                support_score += KNOWLEDGE_EVIDENCE_WEIGHTS.strong_mastery
                evidence_count += 1
            elif mastery.mastery_score <= 0.4 and mastery.confidence >= 0.6:
                contradiction_score += KNOWLEDGE_EVIDENCE_WEIGHTS.weak_mastery
                contradiction_count += 1
        return (
            self._clamp_score(support_score),
            self._clamp_score(contradiction_score),
            evidence_count,
            contradiction_count,
            assessment_count,
            task_count,
        )

    def _compute_behavior_evidence(
        self,
        memory: BehaviorMemory,
        attempts: list[TaskAttempt],
        events: list[MemoryEvent],
    ) -> tuple[float, float, int, int, int]:
        support_score = 0.0
        contradiction_score = 0.0
        evidence_count = 0
        contradiction_count = 0
        recurrence_count = 0
        session_ids = {event.session_id for event in events}
        recurrence_count = max(len(session_ids) - 1, 0)
        if recurrence_count > 0:
            support_score += min(
                recurrence_count * BEHAVIOR_EVIDENCE_WEIGHTS.recurrence_per_session,
                BEHAVIOR_EVIDENCE_WEIGHTS.max_recurrence_support,
            )
            evidence_count += recurrence_count
        for attempt in attempts:
            if attempt.outcome_status in {"failed", "skipped"}:
                support_score += BEHAVIOR_EVIDENCE_WEIGHTS.failed_or_skipped_task
                evidence_count += 1
            elif attempt.outcome_status == "completed":
                contradiction_score += BEHAVIOR_EVIDENCE_WEIGHTS.completed_task_contradiction
                contradiction_count += 1
        return (
            self._clamp_score(support_score),
            self._clamp_score(contradiction_score),
            evidence_count,
            contradiction_count,
            recurrence_count,
        )

    def _compute_knowledge_stability(
        self,
        *,
        confidence_score: float,
        support_score: float,
        contradiction_score: float,
        freshness_score: float,
        goal_relevance_score: float,
        assessment_count: int,
    ) -> float:
        assessment_factor = 1.0 if assessment_count > 0 else 0.0
        return self._clamp_score(
            0.3 * confidence_score
            + 0.25 * support_score
            + 0.2 * assessment_factor
            + 0.15 * freshness_score
            + 0.1 * goal_relevance_score
            - 0.3 * contradiction_score
        )

    def _compute_behavior_stability(
        self,
        *,
        confidence_score: float,
        support_score: float,
        contradiction_score: float,
        freshness_score: float,
        goal_relevance_score: float,
        recurrence_count: int,
        intervention_success_count: int,
        intervention_failure_count: int,
    ) -> float:
        recurrence_factor = self._clamp_score(recurrence_count / 3)
        intervention_factor = self._clamp_score((intervention_success_count + intervention_failure_count) / 4)
        return self._clamp_score(
            0.25 * confidence_score
            + 0.25 * support_score
            + 0.2 * recurrence_factor
            + 0.15 * intervention_factor
            + 0.15 * freshness_score
            - 0.25 * contradiction_score
            + 0.05 * goal_relevance_score
        )

    def _adjust_knowledge_importance(
        self,
        *,
        memory: KnowledgeMemory,
        support_score: float,
        contradiction_score: float,
        assessment_count: int,
    ) -> float:
        delta = support_score * 0.12 + min(assessment_count, 2) * 0.04 - contradiction_score * 0.1
        return self._clamp_score(memory.importance_score * 0.88 + delta)

    def _adjust_knowledge_confidence(
        self,
        *,
        memory: KnowledgeMemory,
        evidence_count: int,
        contradiction_count: int,
        mastery: LearnerTopicMastery | None,
    ) -> float:
        mastery_bonus = 0.08 if mastery is not None and mastery.confidence >= 0.6 else 0.0
        evidence_bonus = min(evidence_count, 5) * 0.04
        contradiction_penalty = min(contradiction_count, 4) * 0.06
        return self._clamp_score(memory.confidence_score * 0.82 + mastery_bonus + evidence_bonus - contradiction_penalty)

    def _adjust_behavior_importance(
        self,
        *,
        memory: BehaviorMemory,
        support_score: float,
        contradiction_score: float,
        recurrence_count: int,
    ) -> float:
        delta = support_score * 0.14 + min(recurrence_count, 3) * 0.05 - contradiction_score * 0.08
        return self._clamp_score(memory.importance_score * 0.9 + delta)

    def _adjust_behavior_confidence(
        self,
        *,
        memory: BehaviorMemory,
        evidence_count: int,
        contradiction_count: int,
        recurrence_count: int,
    ) -> float:
        recurrence_bonus = min(recurrence_count, 3) * 0.06
        evidence_bonus = min(evidence_count, 5) * 0.03
        contradiction_penalty = min(contradiction_count, 4) * 0.05
        return self._clamp_score(memory.confidence_score * 0.84 + recurrence_bonus + evidence_bonus - contradiction_penalty)

    def _govern_knowledge_status(self, memory: KnowledgeMemory) -> str:
        if memory.status == "suppressed":
            return "suppressed"
        if memory.status == "candidate":
            if self._knowledge_promotion_readiness(memory, self._knowledge_quality_score(memory)) == "ready":
                return "active"
            return "candidate"
        if memory.status == "active":
            if (
                memory.evidence_count >= int(self._governance_config["active_to_stable_evidence_min"])
                and memory.assessment_evidence_count >= int(self._governance_config["active_to_stable_assessment_min"])
                and memory.stability_score >= float(self._governance_config["active_to_stable_stability_min"])
                and memory.contradiction_score < float(self._governance_config["candidate_to_active_contradiction_max"])
            ):
                return "stable"
            if (
                memory.freshness_score < float(self._governance_config["archive_freshness_max"])
                and memory.goal_relevance_score < float(self._governance_config["archive_goal_relevance_max"])
            ):
                return "archived"
            return "active"
        if memory.status == "stable":
            if (
                memory.contradiction_score >= float(self._governance_config["stable_demote_contradiction_min"])
                or memory.freshness_score < float(self._governance_config["stable_demote_freshness_max"])
            ):
                return "active"
            if (
                memory.freshness_score < float(self._governance_config["archive_freshness_max"])
                and memory.goal_relevance_score < float(self._governance_config["archive_goal_relevance_max"])
            ):
                return "archived"
            return "stable"
        return memory.status

    def _govern_behavior_status(self, memory: BehaviorMemory) -> str:
        if memory.status == "suppressed":
            return "suppressed"
        if memory.status == "candidate":
            if self._behavior_promotion_readiness(memory, self._behavior_quality_score(memory)) == "ready":
                return "active"
            return "candidate"
        if memory.status == "active":
            if (
                memory.evidence_count >= int(self._governance_config["active_to_stable_evidence_min"])
                and memory.cross_session_recurrence_count >= int(self._governance_config["behavior_active_recurrence_min"])
                and memory.stability_score >= float(self._governance_config["behavior_active_to_stable_stability_min"])
            ):
                return "stable"
            if (
                memory.freshness_score < float(self._governance_config["archive_freshness_max"])
                and memory.goal_relevance_score < float(self._governance_config["archive_goal_relevance_max"])
            ):
                return "archived"
            return "active"
        if memory.status == "stable":
            if (
                memory.contradiction_score >= float(self._governance_config["stable_demote_contradiction_min"])
                or memory.freshness_score < float(self._governance_config["stable_demote_freshness_max"])
            ):
                return "active"
            if (
                memory.freshness_score < float(self._governance_config["archive_freshness_max"])
                and memory.goal_relevance_score < float(self._governance_config["archive_goal_relevance_max"])
            ):
                return "archived"
            return "stable"
        return memory.status

    async def _apply_operator_status_change(
        self,
        *,
        memory_type: str,
        memory_id: str,
        new_status: str,
        reason_code: str,
        reason_note: str | None,
        actor_id: str,
        decision_type: str,
    ) -> KnowledgeMemory | BehaviorMemory:
        memory = await self._get_memory(memory_type, memory_id)
        previous_status = memory.status
        if memory_type == "knowledge":
            updated = memory.with_status(
                new_status,
                update=KnowledgeMemoryStatusUpdate(
                    suppressed_reason_code=reason_code if new_status == "suppressed" else None,
                    suppressed_reason_note=reason_note if new_status == "suppressed" else None,
                    suppressed_by=actor_id if new_status == "suppressed" else None,
                    suppressed_at=datetime.now(timezone.utc) if new_status == "suppressed" else None,
                    promotion_state_changed_at=datetime.now(timezone.utc),
                ),
            )
            await self._knowledge_memory_repository.update(updated)
            await self._sync_knowledge_embedding(updated)
        else:
            updated = memory.with_status(
                new_status,
                update=BehaviorMemoryStatusUpdate(
                    suppressed_reason_code=reason_code if new_status == "suppressed" else None,
                    suppressed_reason_note=reason_note if new_status == "suppressed" else None,
                    suppressed_by=actor_id if new_status == "suppressed" else None,
                    suppressed_at=datetime.now(timezone.utc) if new_status == "suppressed" else None,
                    promotion_state_changed_at=datetime.now(timezone.utc),
                ),
            )
            await self._behavior_memory_repository.update(updated)
            await self._sync_behavior_embedding(updated)
        await self._record_governance_decision(
            memory_type=memory_type,
            memory_id=memory_id,
            previous_status=previous_status,
            new_status=new_status,
            decision_type=decision_type,
            trigger_source="operator_api",
            actor_type="operator",
            actor_id=actor_id,
            reason_code=reason_code,
            reason_note=reason_note,
            metrics_snapshot=self._metrics_snapshot(updated),
        )
        if self._audit_service is not None:
            await self._audit_service.record(
                event_type=f"{memory_type}_memory.{decision_type}d" if decision_type in {"suppress", "restore"} else f"{memory_type}_memory.{decision_type}",
                resource_type=f"{memory_type}_memory",
                resource_id=memory_id,
                actor="operator",
                event_data={
                    "memory_id": memory_id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "reason_code": reason_code,
                    "reason_note": reason_note,
                    "actor_id": actor_id,
                },
            )
        return updated

    async def _get_memory(self, memory_type: str, memory_id: str) -> KnowledgeMemory | BehaviorMemory:
        if memory_type == "knowledge":
            return await self.get_knowledge_memory(memory_id)
        if memory_type == "behavior":
            return await self.get_behavior_memory(memory_id)
        raise ValidationError("memory_type must be knowledge or behavior.")

    async def _record_governance_decision(
        self,
        *,
        memory_type: str,
        memory_id: str,
        previous_status: str | None,
        new_status: str,
        decision_type: str,
        trigger_source: str,
        actor_type: str,
        actor_id: str,
        reason_code: str,
        reason_note: str | None,
        metrics_snapshot: dict[str, float | int | str | None],
    ) -> None:
        if self._governance_decision_repository is not None:
            await self._governance_decision_repository.create(
                MemoryGovernanceDecision.build(
                    memory_type=memory_type,
                    memory_id=memory_id,
                    previous_status=previous_status,
                    new_status=new_status,
                    decision_type=decision_type,
                    trigger_source=trigger_source,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason_code=reason_code,
                    reason_note=reason_note,
                    metrics_snapshot=metrics_snapshot,
                )
            )
        if self._audit_service is not None:
            await self._audit_service.record(
                event_type=f"{memory_type}_memory.{decision_type}d" if decision_type in {"promote", "demote", "archive", "restore", "suppress"} else f"{memory_type}_memory.{decision_type}ed",
                resource_type=f"{memory_type}_memory",
                resource_id=memory_id,
                actor=actor_type,
                event_data={
                    "memory_id": memory_id,
                    "previous_status": previous_status,
                    "new_status": new_status,
                    "decision_type": decision_type,
                    "trigger_source": trigger_source,
                    "reason_code": reason_code,
                    "reason_note": reason_note,
                    "actor_id": actor_id,
                    "metrics_snapshot": metrics_snapshot,
                },
            )

    def _decision_type_for_transition(self, previous_status: str, new_status: str) -> str:
        if previous_status in {"candidate", "active"} and new_status in {"active", "stable"}:
            return "promote"
        if previous_status == "stable" and new_status == "active":
            return "demote"
        if new_status == "archived":
            return "archive"
        return "refresh"

    @staticmethod
    def _has_material_refresh_change(
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

    def _metrics_snapshot(self, memory: KnowledgeMemory | BehaviorMemory) -> dict[str, float | int | str | None]:
        snapshot = self._memory_quality_snapshot_sync(memory)
        return {
            "support_score": memory.support_score,
            "contradiction_score": memory.contradiction_score,
            "evidence_count": memory.evidence_count,
            "contradiction_count": memory.contradiction_count,
            "stability_score": memory.stability_score,
            "freshness_score": memory.freshness_score,
            "goal_relevance_score": memory.goal_relevance_score,
            "quality_score": snapshot["quality_score"],
            "quality_tier": snapshot["quality_tier"],
            "promotion_readiness": snapshot["promotion_readiness"],
        }

    async def _memory_quality_snapshot(
        self,
        memory_type: str,
        memory: KnowledgeMemory | BehaviorMemory,
    ) -> dict[str, object]:
        evidence_mix = await self._evidence_mix(memory_type=memory_type, memory_id=memory.id)
        snapshot = self._memory_quality_snapshot_sync(memory, evidence_mix=evidence_mix)
        observe_memory_quality_assessment(
            memory_type=memory_type,
            quality_tier=str(snapshot["quality_tier"]),
            promotion_readiness=str(snapshot["promotion_readiness"]),
        )
        return snapshot

    def _memory_quality_snapshot_sync(
        self,
        memory: KnowledgeMemory | BehaviorMemory,
        *,
        evidence_mix: dict[str, float] | None = None,
    ) -> dict[str, object]:
        if isinstance(memory, KnowledgeMemory):
            quality_score = self._knowledge_quality_score(memory)
            readiness = self._knowledge_promotion_readiness(memory, quality_score)
        else:
            quality_score = self._behavior_quality_score(memory)
            readiness = self._behavior_promotion_readiness(memory, quality_score)
        quality_tier = self._quality_tier(quality_score)
        return {
            "quality_score": quality_score,
            "quality_tier": quality_tier,
            "promotion_readiness": readiness,
            "quality_reasons": self._quality_reasons(memory=memory, quality_score=quality_score, readiness=readiness),
            "evidence_mix": evidence_mix or {},
        }

    async def _evidence_mix(self, *, memory_type: str, memory_id: str) -> dict[str, float]:
        if self._evidence_link_repository is None:
            return {}
        links = await self._evidence_link_repository.list_by_memory(memory_type=memory_type, memory_id=memory_id)
        if not links:
            return {}
        weights: dict[str, float] = {}
        total = 0.0
        for link in links:
            weights[link.evidence_source_type] = weights.get(link.evidence_source_type, 0.0) + link.weight
            total += link.weight
        if total <= 0:
            return {}
        return {key: round(value / total, 4) for key, value in sorted(weights.items())}

    def _knowledge_quality_score(self, memory: KnowledgeMemory) -> float:
        source_strength = 0.1
        if memory.source_event_ids:
            source_strength = 0.25
        if memory.task_evidence_count > 0:
            source_strength = max(source_strength, 0.55)
        if memory.assessment_evidence_count > 0:
            source_strength = max(source_strength, 0.8)
        recurrence = self._clamp_score(memory.evidence_count / 5)
        assessment_backing = self._clamp_score(memory.assessment_evidence_count / 2)
        return self._clamp_score(
            0.18 * source_strength
            + 0.18 * recurrence
            + 0.18 * assessment_backing
            + 0.14 * memory.support_score
            + 0.12 * memory.goal_relevance_score
            + 0.10 * memory.stability_score
            + 0.10 * memory.confidence_score
            - 0.18 * memory.contradiction_score
        )

    def _behavior_quality_score(self, memory: BehaviorMemory) -> float:
        source_strength = 0.1
        if memory.source_event_ids:
            source_strength = 0.25
        if memory.evidence_count > 0:
            source_strength = max(source_strength, 0.55)
        recurrence = self._clamp_score(max(memory.cross_session_recurrence_count, memory.evidence_count) / 4)
        task_backing = self._clamp_score(memory.evidence_count / 4)
        return self._clamp_score(
            0.22 * source_strength
            + 0.22 * recurrence
            + 0.18 * task_backing
            + 0.12 * memory.support_score
            + 0.12 * memory.goal_relevance_score
            + 0.08 * memory.stability_score
            + 0.08 * memory.confidence_score
            - 0.14 * memory.contradiction_score
        )

    @staticmethod
    def _quality_tier(quality_score: float) -> str:
        if quality_score >= 0.7:
            return "high"
        if quality_score >= 0.45:
            return "medium"
        return "low"

    def _knowledge_promotion_readiness(self, memory: KnowledgeMemory, quality_score: float) -> str:
        if (
            quality_score >= 0.62
            and memory.evidence_count >= int(self._governance_config["candidate_to_active_evidence_min"])
            and memory.support_score >= float(self._governance_config["candidate_to_active_support_min"])
            and memory.confidence_score >= float(self._governance_config["candidate_to_active_confidence_min"])
            and memory.contradiction_score < float(self._governance_config["candidate_to_active_contradiction_max"])
        ):
            return "ready"
        if quality_score >= 0.45:
            return "monitor"
        return "not_ready"

    def _behavior_promotion_readiness(self, memory: BehaviorMemory, quality_score: float) -> str:
        if (
            quality_score >= 0.58
            and memory.evidence_count >= int(self._governance_config["candidate_to_active_evidence_min"])
            and memory.cross_session_recurrence_count >= 2
            and memory.confidence_score >= 0.5
        ):
            return "ready"
        if quality_score >= 0.45:
            return "monitor"
        return "not_ready"

    def _quality_reasons(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        quality_score: float,
        readiness: str,
    ) -> list[str]:
        reasons: list[str] = []
        if isinstance(memory, KnowledgeMemory):
            if memory.assessment_evidence_count > 0:
                reasons.append("assessment_backed")
            elif memory.task_evidence_count > 0:
                reasons.append("task_backed")
            elif memory.source_event_ids:
                reasons.append("weak_session_only")
        else:
            if memory.cross_session_recurrence_count >= 2:
                reasons.append("cross_session_recurrence")
            elif memory.source_event_ids:
                reasons.append("weak_session_only")
        if memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
            reasons.append("high_contradiction")
        if memory.freshness_score < 0.35:
            reasons.append("low_freshness")
        if memory.goal_relevance_score >= 0.7:
            reasons.append("goal_aligned")
        if readiness == "ready":
            reasons.append("promotion_ready")
        elif readiness == "monitor":
            reasons.append("monitor_candidate")
        if not reasons:
            reasons.append("balanced")
        if quality_score >= 0.7 and "high_quality" not in reasons:
            reasons.append("high_quality")
        return reasons

    def _interpret_knowledge_memory(self, memory: KnowledgeMemory) -> MemoryInterpretationFact:
        return MemoryInterpretationFact(
            memory_type="knowledge",
            memory_id=memory.id,
            memory_key=memory.knowledge_key,
            semantic_category=memory.semantic_category,
            validation_status=memory.validation_status,
            title=memory.title,
            summary=memory.summary,
            confidence_score=memory.confidence_score,
            importance_score=memory.importance_score,
            recommended_use=self._recommended_memory_use(memory),
        )

    def _interpret_behavior_memory(self, memory: BehaviorMemory) -> MemoryInterpretationFact:
        return MemoryInterpretationFact(
            memory_type="behavior",
            memory_id=memory.id,
            memory_key=memory.behavior_key,
            semantic_category=memory.semantic_category,
            validation_status=memory.validation_status,
            title=memory.title,
            summary=memory.summary,
            confidence_score=memory.confidence_score,
            importance_score=memory.importance_score,
            recommended_use=self._recommended_memory_use(memory),
        )

    def _interpretation_constraints(
        self,
        *,
        facts: list[MemoryInterpretationFact],
        behavior_patterns: list[MemoryInterpretationFact],
        contested_items: list[MemoryInterpretationFact],
        conflicts: list[MemoryConflictSet],
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

    @staticmethod
    def _recommended_memory_use(memory: KnowledgeMemory | BehaviorMemory) -> str:
        if memory.validation_status == "contested" or memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
            return "verify_before_use"
        if memory.validation_status == "stale" or memory.freshness_score < 0.3:
            return "refresh_before_use"
        if memory.validation_status == "validated":
            return "safe_context"
        if memory.validation_status == "locally_valid":
            return "goal_scoped_context"
        return "weak_context"

    @staticmethod
    def _validation_status_for_memory(
        *,
        contradiction_score: float,
        freshness_score: float,
        evidence_count: int,
        support_score: float,
        scope_type: str,
    ) -> str:
        if contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD:
            return "contested"
        if freshness_score < 0.3:
            return "stale"
        if evidence_count >= 3 and support_score >= 0.45:
            return "locally_valid" if scope_type == "goal_scoped" else "validated"
        return "unverified"

    @staticmethod
    def _promotion_rationale(*, updated_status: str, memory: KnowledgeMemory | BehaviorMemory) -> str:
        return (
            f"status={updated_status}; evidence={memory.evidence_count}; "
            f"support={memory.support_score:.2f}; contradiction={memory.contradiction_score:.2f}; "
            f"confidence={memory.confidence_score:.2f}; stability={memory.stability_score:.2f}"
        )

    async def _build_reflection_corpus_item(
        self,
        memory_type: str,
        memory: KnowledgeMemory | BehaviorMemory,
    ) -> ReflectionCorpusMemoryItem:
        if memory_type == "knowledge":
            memory_key = getattr(memory, "knowledge_key", "")
            memory_level = getattr(memory, "knowledge_level", "")
        else:
            memory_key = getattr(memory, "behavior_key", "")
            memory_level = getattr(memory, "behavior_level", "")
        reflection_priority_score = self._reflection_priority_score(memory=memory)
        recommended_action = self._reflection_recommended_action(memory=memory, reflection_priority_score=reflection_priority_score)
        governance_pressure = self._governance_pressure(memory)
        quality_snapshot = await self._memory_quality_snapshot(memory_type, memory)
        topic_alignment_score = self._topic_alignment_score(
            memory_key,
            memory_key,
            title=memory.title,
            tags=memory.tags,
            extras=getattr(memory, "prerequisite_keys", None),
        )
        return ReflectionCorpusMemoryItem(
            memory_type=memory_type,
            memory_id=memory.id,
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            memory_key=memory_key,
            memory_level=memory_level,
            title=memory.title,
            summary=memory.summary,
            status=memory.status,
            time_horizon=memory.time_horizon,
            importance_score=memory.importance_score,
            confidence_score=memory.confidence_score,
            freshness_score=memory.freshness_score,
            stability_score=memory.stability_score,
            goal_relevance_score=memory.goal_relevance_score,
            support_score=memory.support_score,
            contradiction_score=memory.contradiction_score,
            evidence_count=memory.evidence_count,
            contradiction_count=memory.contradiction_count,
            reflection_priority_score=reflection_priority_score,
            recommended_action=recommended_action,
            rationale=self._reflection_rationale(memory=memory, recommended_action=recommended_action),
            recommended_action_reason=self._recommended_action_reason(memory=memory, recommended_action=recommended_action),
            topic_alignment_score=topic_alignment_score,
            governance_pressure=governance_pressure,
            review_recommended=self._review_recommended(memory),
            quality_score=float(quality_snapshot["quality_score"]),
            quality_tier=str(quality_snapshot["quality_tier"]),
            promotion_readiness=str(quality_snapshot["promotion_readiness"]),
            quality_reasons=list(quality_snapshot["quality_reasons"]),
            evidence_mix=dict(quality_snapshot["evidence_mix"]),
            semantic_category=memory.semantic_category,
            validation_status=memory.validation_status,
            provenance_type=memory.provenance_type,
            provenance_source_id=memory.provenance_source_id,
            scope_ref=dict(memory.scope_ref),
            promotion_rationale=memory.promotion_rationale,
            contested=memory.validation_status == "contested" or memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD,
            source_event_ids=list(memory.source_event_ids),
            source_memory_ids=list(memory.source_memory_ids),
            tags=list(memory.tags),
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )

    def _reflection_priority_score(self, *, memory: KnowledgeMemory | BehaviorMemory) -> float:
        contradiction_pressure = 1.0 - memory.contradiction_score
        freshness_pressure = 1.0 - memory.freshness_score
        evidence_pressure = self._clamp_score(memory.evidence_count / 6)
        stability_pressure = memory.stability_score
        status_bonus = {
            "candidate": 0.12,
            "active": 0.18,
            "stable": 0.14,
            "archived": 0.08,
            "compressed": 0.04,
            "suppressed": 0.0,
        }.get(memory.status, 0.05)
        return self._clamp_score(
            0.25 * memory.importance_score
            + 0.15 * memory.confidence_score
            + 0.15 * memory.support_score
            + 0.15 * contradiction_pressure
            + 0.15 * freshness_pressure
            + 0.1 * evidence_pressure
            + 0.05 * stability_pressure
            + status_bonus
        )

    def _reflection_recommended_action(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        reflection_priority_score: float,
    ) -> str:
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

    def _reflection_rationale(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        recommended_action: str,
    ) -> str:
        return (
            f"status={memory.status}; "
            f"support={memory.support_score:.2f}; "
            f"contradiction={memory.contradiction_score:.2f}; "
            f"freshness={memory.freshness_score:.2f}; "
            f"stability={memory.stability_score:.2f}; "
            f"action={recommended_action}"
        )

    @staticmethod
    def _infer_struggle_note(learner_message: str) -> str | None:
        lowered = learner_message.casefold()
        if any(token in lowered for token in ["don't understand", "dont understand", "confused", "stuck", "wrong"]):
            return learner_message[:220].strip()
        if "hint" in lowered or "help" in lowered:
            return f"Learner requested guided support: {learner_message[:180].strip()}"
        return None

    @staticmethod
    def _infer_progress_note(*, assistant_message: str, mode: str | None) -> str | None:
        if mode == "hint":
            return "Learner continued after requesting a guided hint."
        if assistant_message.strip():
            return f"Session advanced with a structured reply: {assistant_message[:180].strip()}"
        return None

    @staticmethod
    def _infer_concept_focus(learner_message: str) -> str | None:
        normalized = learner_message.replace("?", " ").replace(",", " ").split()
        if not normalized:
            return None
        return " ".join(normalized[: min(4, len(normalized))]).strip() or None

    @staticmethod
    def _build_event_summary(
        *,
        topic: str,
        concept_focus: str | None,
        struggle_note: str | None,
        progress_note: str | None,
        mode: str | None,
    ) -> str:
        summary_parts = [f"Topic: {topic}"]
        if concept_focus is not None:
            summary_parts.append(f"Concept focus: {concept_focus}")
        if struggle_note is not None:
            summary_parts.append(f"Struggle: {struggle_note}")
        if progress_note is not None:
            summary_parts.append(f"Progress: {progress_note}")
        summary_parts.append(f"Mode: {mode or 'chat'}")
        return " | ".join(summary_parts)

    @staticmethod
    def _build_profile_summary(
        *,
        topic: str,
        concept_focus: str | None,
        progress_note: str | None,
        struggle_note: str | None,
    ) -> str:
        summary = [f"Learner profile update for {topic}."]
        if concept_focus is not None:
            summary.append(f"Current concept trend: {concept_focus}.")
        if struggle_note is not None:
            summary.append(f"Recurring struggle: {struggle_note}.")
        if progress_note is not None:
            summary.append(f"Progress signal: {progress_note}.")
        return " ".join(summary)

    @staticmethod
    def _build_tags(*, mode: str | None, concept_focus: str | None, struggle_note: str | None) -> list[str]:
        tags = ["session", mode or "chat"]
        if concept_focus is not None:
            tags.append("concept")
        if struggle_note is not None:
            tags.append("struggle")
        return tags

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = sqrt(sum(a * a for a in left))
        right_norm = sqrt(sum(b * b for b in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return 0.0
        return dot / (left_norm * right_norm)

    def _score_long_term_memory(
        self,
        *,
        vector: list[float],
        query_vector: list[float],
        importance_score: float,
        confidence_score: float,
        freshness_score: float,
        stability_score: float,
        goal_relevance_score: float,
        created_at: datetime,
    ) -> float:
        similarity = self._cosine_similarity(query_vector, vector)
        freshness = freshness_score * self._freshness_decay(created_at)
        return (
            0.40 * similarity
            + 0.20 * importance_score
            + 0.15 * confidence_score
            + 0.10 * freshness
            + 0.10 * stability_score
            + 0.05 * goal_relevance_score
        )

    @staticmethod
    def _freshness_decay(created_at: datetime) -> float:
        age = datetime.now(timezone.utc) - created_at
        age_days = max(age.total_seconds() / 86400.0, 0.0)
        return max(0.1, 1.0 - age_days / 30.0)

    @staticmethod
    def _decay_freshness(current: float, updated_at: datetime, time_horizon: str, level: str) -> float:
        days = max((datetime.now(timezone.utc) - updated_at).total_seconds() / 86400.0, 0.0)
        if time_horizon == "early":
            window = 14
        elif time_horizon == "mid":
            window = 45 if level not in BEHAVIOR_LEVELS else 21
        else:
            window = 120 if level not in BEHAVIOR_LEVELS else 60
        return max(0.0, min(current, 1.0 - min(days / max(window, 1), 1.0)))

    @staticmethod
    def _clamp_score(value: float) -> float:
        return max(0.0, min(1.0, value))

    @staticmethod
    def _normalize_key(value: str) -> str:
        return MemoryNormalizer.normalize_topic_key(value)

    @classmethod
    def _topic_tokens(cls, value: str) -> list[str]:
        return MemoryNormalizer.topic_tokens(value)

    @classmethod
    def _topic_matches(cls, topic_key: str, candidate_key: str, *, title: str | None = None, tags: list[str] | None = None) -> bool:
        return cls._topic_alignment_score(
            topic_key,
            candidate_key,
            title=title,
            tags=tags,
            extras=None,
        ) >= 0.55

    @classmethod
    def _topic_alignment_score(
        cls,
        topic_key: str,
        candidate_key: str,
        *,
        title: str | None,
        tags: list[str] | None,
        extras: list[str] | None,
    ) -> float:
        normalized_topic = cls._normalize_key(topic_key)
        normalized_candidate = cls._normalize_key(candidate_key)
        if normalized_topic == normalized_candidate:
            return 1.0
        topic_tokens = set(cls._topic_tokens(topic_key))
        candidate_tokens = set(cls._topic_tokens(candidate_key))
        if not topic_tokens:
            return 0.0
        overlap = len(topic_tokens & candidate_tokens) / max(len(topic_tokens), 1)
        substring_bonus = 0.2 if normalized_topic and (
            normalized_topic in normalized_candidate or normalized_candidate in normalized_topic
        ) else 0.0
        support_tokens = set(cls._topic_tokens(title or ""))
        support_tokens.update(cls._topic_tokens(" ".join(tags or [])))
        support_tokens.update(cls._topic_tokens(" ".join(extras or [])))
        support_overlap = len(topic_tokens & support_tokens) / max(len(topic_tokens), 1) if support_tokens else 0.0
        support_bonus = 0.15 if topic_tokens & support_tokens else 0.0
        if support_overlap >= 0.5:
            support_bonus += 0.25
        return cls._clamp_score(overlap + substring_bonus + support_bonus)

    @staticmethod
    def _governance_pressure(memory: KnowledgeMemory | BehaviorMemory) -> float:
        contradiction_pressure = memory.contradiction_score
        staleness_pressure = 1.0 - memory.freshness_score
        low_relevance_pressure = 1.0 - memory.goal_relevance_score
        low_stability_pressure = 1.0 - memory.stability_score
        return min(
            1.0,
            0.35 * contradiction_pressure
            + 0.35 * staleness_pressure
            + 0.2 * low_relevance_pressure
            + 0.15 * low_stability_pressure,
        )

    @staticmethod
    def _review_recommended(memory: KnowledgeMemory | BehaviorMemory) -> bool:
        return memory.status == "candidate" and (
            memory.contradiction_score >= CONFLICT_CONTRADICTION_THRESHOLD
            or memory.freshness_score < 0.35
            or memory.goal_relevance_score >= 0.7
        )

    def _topic_bucket_summary(self, memories: list[KnowledgeMemory | BehaviorMemory]) -> list[dict[str, object]]:
        buckets: dict[str, dict[str, object]] = {}
        for memory in memories:
            topic_key = getattr(memory, "knowledge_key", "") or getattr(memory, "behavior_key", "")
            bucket = buckets.setdefault(
                topic_key,
                {
                    "topic_key": topic_key,
                    "memory_count": 0,
                    "candidate_count": 0,
                    "review_recommended": 0,
                },
            )
            bucket["memory_count"] = int(bucket["memory_count"]) + 1
            if memory.status == "candidate":
                bucket["candidate_count"] = int(bucket["candidate_count"]) + 1
            if self._review_recommended(memory):
                bucket["review_recommended"] = int(bucket["review_recommended"]) + 1
        return sorted(
            buckets.values(),
            key=lambda item: (int(item["review_recommended"]), int(item["memory_count"])),
            reverse=True,
        )[:10]

    def _is_knowledge_promotion_candidate(self, memory: KnowledgeMemory) -> bool:
        quality_score = self._knowledge_quality_score(memory)
        return memory.status == "candidate" and self._knowledge_promotion_readiness(memory, quality_score) == "ready"

    def _is_behavior_promotion_candidate(self, memory: BehaviorMemory) -> bool:
        quality_score = self._behavior_quality_score(memory)
        return memory.status == "candidate" and self._behavior_promotion_readiness(memory, quality_score) == "ready"

    def _recommended_action_reason(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        recommended_action: str,
    ) -> str:
        if recommended_action == "validate":
            return "contradiction_pressure"
        if recommended_action == "refresh":
            return "staleness_pressure"
        if recommended_action == "reinforce":
            return "promotion_candidate"
        if recommended_action == "review":
            return "archived_high_value"
        return "balanced"

    def _knowledge_governance_multiplier(
        self,
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

    def _behavior_governance_multiplier(
        self,
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

    @staticmethod
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

    @staticmethod
    def _select_highest_level(levels: list[str], *, ordered_levels: list[str]) -> str:
        order_map = {level: index for index, level in enumerate(ordered_levels)}
        return max(levels, key=lambda level: order_map.get(level, -1))

    @staticmethod
    def _build_memory_details(*, learner_message: str, assistant_message: str) -> str:
        return f"Learner: {learner_message[:280].strip()} | Assistant: {assistant_message[:280].strip()}"

    @staticmethod
    def _build_knowledge_summary(
        *,
        topic: str,
        concept_focus: str | None,
        progress_note: str | None,
        struggle_note: str | None,
        assistant_message: str,
    ) -> str:
        parts = [f"Knowledge: {topic}"]
        if concept_focus is not None:
            parts.append(f"Concept: {concept_focus}")
        if progress_note is not None:
            parts.append(f"Progress: {progress_note}")
        if struggle_note is not None:
            parts.append(f"Struggle: {struggle_note}")
        if assistant_message.strip():
            parts.append(f"Teaching: {assistant_message[:180].strip()}")
        return " | ".join(parts)

    @staticmethod
    def _build_behavior_title(*, behavior_category: str, subject: str | None, session_title: str | None) -> str:
        topic = subject or session_title or "learning session"
        return f"{behavior_category.replace('_', ' ').title()} for {topic}"

    @staticmethod
    def _build_behavior_summary(
        *,
        behavior_category: str,
        learner_message: str,
        progress_note: str | None,
        struggle_note: str | None,
    ) -> str:
        parts = [f"Behavior: {behavior_category}"]
        if struggle_note is not None:
            parts.append(f"Struggle: {struggle_note}")
        if progress_note is not None:
            parts.append(f"Progress: {progress_note}")
        parts.append(f"Learner: {learner_message[:180].strip()}")
        return " | ".join(parts)

    @staticmethod
    def _build_compressed_summary(*, prefix: str, titles: list[str], summaries: list[str]) -> str:
        title_snippet = "; ".join(titles[:3])
        summary_snippet = " / ".join(summary[:120] for summary in summaries[:3])
        return f"{prefix} cluster from {title_snippet}. {summary_snippet}"

    @staticmethod
    def _build_knowledge_tags(
        *,
        mode: str | None,
        subject: str | None,
        concept_focus: str | None,
        struggle_note: str | None,
    ) -> list[str]:
        tags = ["knowledge", mode or "chat"]
        if subject is not None:
            tags.append(subject.casefold())
        if concept_focus is not None:
            tags.append(concept_focus.casefold())
        if struggle_note is not None:
            tags.append("struggle")
        return tags

    @staticmethod
    def _build_behavior_tags(
        *,
        mode: str | None,
        subject: str | None,
        struggle_note: str | None,
        progress_note: str | None,
    ) -> list[str]:
        tags = ["behavior", mode or "chat"]
        if subject is not None:
            tags.append(subject.casefold())
        if struggle_note is not None:
            tags.append("struggle")
        if progress_note is not None:
            tags.append("progress")
        return tags

    @staticmethod
    def _build_behavior_intervention_effect(
        *,
        mode: str | None,
        progress_note: str | None,
        struggle_note: str | None,
    ) -> str | None:
        if mode == "hint":
            return "Learner responded to guided hinting."
        if progress_note is not None and struggle_note is not None:
            return "Learner advanced after a supported explanation."
        if progress_note is not None:
            return "Learner advanced with direct explanation."
        if struggle_note is not None:
            return "Learner showed a repeated struggle pattern."
        return None

    @staticmethod
    def _classify_knowledge_level(*, topic: str, assistant_message: str, learner_message: str) -> str:
        lowered = f"{topic} {assistant_message} {learner_message}".casefold()
        if any(token in lowered for token in ["definition", "basics", "intro", "introduction", "foundation"]):
            return "foundation"
        if any(token in lowered for token in ["advanced", "proof", "theorem", "deep"]):
            return "advanced"
        if any(token in lowered for token in ["apply", "application", "practice", "exercise"]):
            return "application"
        return "core"

    @staticmethod
    def _classify_knowledge_horizon(
        *,
        knowledge_level: str,
        struggle_note: str | None,
        progress_note: str | None,
    ) -> str:
        if knowledge_level == "foundation":
            return "early"
        if struggle_note is not None and progress_note is None:
            return "early"
        if knowledge_level == "application":
            return "long"
        return "mid"

    @staticmethod
    def _classify_behavior_category(
        *,
        mode: str | None,
        struggle_note: str | None,
        progress_note: str | None,
    ) -> str:
        return MemoryNormalizer.classify_behavior_category(
            mode=mode,
            struggle_note=struggle_note,
            progress_note=progress_note,
        )

    @staticmethod
    def _classify_behavior_level(
        *,
        mode: str | None,
        struggle_note: str | None,
        progress_note: str | None,
    ) -> str:
        if mode == "hint" or struggle_note is not None:
            return "recurrent"
        if progress_note is not None:
            return "surface"
        return "persistent"

    @staticmethod
    def _classify_behavior_horizon(
        *,
        behavior_level: str,
        struggle_note: str | None,
        progress_note: str | None,
    ) -> str:
        if behavior_level in {"persistent", "critical"}:
            return "long"
        if struggle_note is not None or progress_note is not None:
            return "mid"
        return "early"

    def _build_knowledge_memory(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        source_event_ids: list[str] | None = None,
        provenance_type: str | None = None,
        provenance_source_id: str | None = None,
    ) -> KnowledgeMemory | None:
        topic = subject or session_title or self._infer_concept_focus(learner_message)
        if topic is None:
            return None
        concept_focus = self._infer_concept_focus(learner_message) or topic
        struggle_note = self._infer_struggle_note(learner_message)
        progress_note = self._infer_progress_note(assistant_message=assistant_message, mode=mode)
        knowledge_level = self._classify_knowledge_level(
            topic=topic,
            assistant_message=assistant_message,
            learner_message=learner_message,
        )
        time_horizon = self._classify_knowledge_horizon(
            knowledge_level=knowledge_level,
            struggle_note=struggle_note,
            progress_note=progress_note,
        )
        semantic_category = MemoryNormalizer.classify_semantic_category(
            memory_type="knowledge",
            knowledge_level=knowledge_level,
        )
        importance_score = self._clamp_score(
            0.45
            + (0.2 if subject is not None else 0.0)
            + (0.15 if progress_note is not None else 0.0)
            + (0.15 if concept_focus and concept_focus.casefold() != topic.casefold() else 0.0)
        )
        confidence_score = self._clamp_score(
            0.4
            + (0.2 if assistant_message.strip() else 0.0)
            + (0.2 if source_message_id is not None else 0.0)
            + (0.1 if progress_note is not None else 0.0)
            + (0.1 if struggle_note is not None else 0.0)
        )
        summary = self._build_knowledge_summary(
            topic=topic,
            concept_focus=concept_focus,
            progress_note=progress_note,
            struggle_note=struggle_note,
            assistant_message=assistant_message,
        )
        prerequisite_keys = [subject.casefold()] if subject is not None and subject.casefold() != topic.casefold() else []
        memory = KnowledgeMemory.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            knowledge_key=self._normalize_key(topic),
            title=topic,
            summary=summary,
            details=self._build_memory_details(learner_message=learner_message, assistant_message=assistant_message),
            knowledge_level=knowledge_level,
            time_horizon=time_horizon,
            importance_score=importance_score,
            confidence_score=confidence_score,
            freshness_score=1.0,
            prerequisite_keys=prerequisite_keys,
            source_event_ids=list(source_event_ids if source_event_ids is not None else ([source_message_id] if source_message_id is not None else [])),
            source_memory_ids=[],
            tags=self._build_knowledge_tags(
                mode=mode,
                subject=subject,
                concept_focus=concept_focus,
                struggle_note=struggle_note,
            ),
        )
        memory_values = {
            **memory.__dict__,
            "semantic_category": semantic_category,
        }
        if provenance_type is None and provenance_source_id is None:
            return KnowledgeMemory(**memory_values)
        return KnowledgeMemory(
            **{
                **memory_values,
                "provenance_type": provenance_type or memory.provenance_type,
                "provenance_source_id": provenance_source_id,
            }
        )

    def _build_behavior_memory(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        learner_message: str,
        assistant_message: str,
        source_message_id: str | None,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
        source_event_ids: list[str] | None = None,
        provenance_type: str | None = None,
        provenance_source_id: str | None = None,
    ) -> BehaviorMemory | None:
        struggle_note = self._infer_struggle_note(learner_message)
        progress_note = self._infer_progress_note(assistant_message=assistant_message, mode=mode)
        if struggle_note is None and progress_note is None and mode != "hint":
            return None
        behavior_category = self._classify_behavior_category(mode=mode, struggle_note=struggle_note, progress_note=progress_note)
        semantic_category = MemoryNormalizer.classify_semantic_category(
            memory_type="behavior",
            behavior_category=behavior_category,
        )
        behavior_level = self._classify_behavior_level(mode=mode, struggle_note=struggle_note, progress_note=progress_note)
        time_horizon = self._classify_behavior_horizon(
            behavior_level=behavior_level,
            struggle_note=struggle_note,
            progress_note=progress_note,
        )
        importance_score = self._clamp_score(
            0.35
            + (0.25 if struggle_note is not None else 0.0)
            + (0.2 if mode == "hint" else 0.0)
            + (0.1 if progress_note is not None else 0.0)
            + (0.05 if subject is not None else 0.0)
        )
        confidence_score = self._clamp_score(
            0.35
            + (0.2 if source_message_id is not None else 0.0)
            + (0.15 if struggle_note is not None else 0.0)
            + (0.15 if progress_note is not None else 0.0)
            + (0.1 if assistant_message.strip() else 0.0)
        )
        memory = BehaviorMemory.build(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            behavior_key=self._normalize_key(f"{behavior_category}:{subject or session_title or 'session'}"),
            behavior_category=behavior_category,
            title=self._build_behavior_title(
                behavior_category=behavior_category,
                subject=subject,
                session_title=session_title,
            ),
            summary=self._build_behavior_summary(
                behavior_category=behavior_category,
                learner_message=learner_message,
                progress_note=progress_note,
                struggle_note=struggle_note,
            ),
            details=self._build_memory_details(learner_message=learner_message, assistant_message=assistant_message),
            behavior_level=behavior_level,
            time_horizon=time_horizon,
            importance_score=importance_score,
            confidence_score=confidence_score,
            freshness_score=1.0,
            source_event_ids=list(source_event_ids if source_event_ids is not None else ([source_message_id] if source_message_id is not None else [])),
            source_memory_ids=[],
            tags=self._build_behavior_tags(
                mode=mode,
                subject=subject,
                struggle_note=struggle_note,
                progress_note=progress_note,
            ),
            intervention_effect=self._build_behavior_intervention_effect(
                mode=mode,
                progress_note=progress_note,
                struggle_note=struggle_note,
            ),
        )
        memory_values = {
            **memory.__dict__,
            "semantic_category": semantic_category,
        }
        if provenance_type is None and provenance_source_id is None:
            return BehaviorMemory(**memory_values)
        return BehaviorMemory(
            **{
                **memory_values,
                "provenance_type": provenance_type or memory.provenance_type,
                "provenance_source_id": provenance_source_id,
            }
        )

    @classmethod
    def _merge_knowledge_memory(cls, *, existing: KnowledgeMemory, incoming: KnowledgeMemory) -> KnowledgeMemory:
        now = datetime.now(timezone.utc)
        source_event_ids = cls._merge_unique([existing.source_event_ids, incoming.source_event_ids])
        source_memory_ids = cls._merge_unique([existing.source_memory_ids, incoming.source_memory_ids])
        tags = cls._merge_unique([existing.tags, incoming.tags])
        prerequisite_keys = cls._merge_unique([existing.prerequisite_keys, incoming.prerequisite_keys])
        return KnowledgeMemory(
            id=existing.id,
            learner_profile_id=existing.learner_profile_id,
            learner_goal_id=existing.learner_goal_id,
            knowledge_key=existing.knowledge_key,
            title=incoming.title or existing.title,
            summary=incoming.summary or existing.summary,
            details=incoming.details or existing.details,
            knowledge_level=cls._select_highest_level(
                [existing.knowledge_level, incoming.knowledge_level],
                ordered_levels=["foundation", "core", "advanced", "application"],
            ),
            time_horizon=incoming.time_horizon,
            importance_score=cls._clamp_score(max(existing.importance_score, incoming.importance_score)),
            confidence_score=cls._clamp_score(max(existing.confidence_score, incoming.confidence_score)),
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

    @classmethod
    def _merge_behavior_memory(cls, *, existing: BehaviorMemory, incoming: BehaviorMemory) -> BehaviorMemory:
        now = datetime.now(timezone.utc)
        source_event_ids = cls._merge_unique([existing.source_event_ids, incoming.source_event_ids])
        source_memory_ids = cls._merge_unique([existing.source_memory_ids, incoming.source_memory_ids])
        tags = cls._merge_unique([existing.tags, incoming.tags])
        return BehaviorMemory(
            id=existing.id,
            learner_profile_id=existing.learner_profile_id,
            learner_goal_id=existing.learner_goal_id,
            behavior_key=existing.behavior_key,
            behavior_category=existing.behavior_category,
            title=incoming.title or existing.title,
            summary=incoming.summary or existing.summary,
            details=incoming.details or existing.details,
            behavior_level=cls._select_highest_level(
                [existing.behavior_level, incoming.behavior_level],
                ordered_levels=["surface", "recurrent", "persistent", "critical"],
            ),
            time_horizon=incoming.time_horizon,
            importance_score=cls._clamp_score(max(existing.importance_score, incoming.importance_score)),
            confidence_score=cls._clamp_score(max(existing.confidence_score, incoming.confidence_score)),
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

    @staticmethod
    def _default_governance_config() -> dict[str, float | int]:
        return {
            "candidate_to_active_evidence_min": 2,
            "candidate_to_active_support_min": 0.35,
            "candidate_to_active_confidence_min": 0.55,
            "candidate_to_active_contradiction_max": 0.25,
            "active_to_stable_evidence_min": 4,
            "active_to_stable_stability_min": 0.75,
            "active_to_stable_assessment_min": 1,
            "stable_demote_contradiction_min": 0.35,
            "stable_demote_freshness_max": 0.35,
            "archive_freshness_max": 0.1,
            "archive_goal_relevance_max": 0.35,
            "behavior_candidate_recurrence_min": 1,
            "behavior_active_recurrence_min": 2,
            "behavior_active_to_stable_stability_min": 0.7,
            "reflection_effective_weight": 0.18,
            "reflection_ineffective_weight": 0.14,
            "compression_min_group_size": 2,
        }

    @staticmethod
    def _topic_key_from_reflection(reflection: ReflectionRecord) -> str | None:
        task = reflection.evidence_payload.get("task") or {}
        workflow = reflection.evidence_payload.get("workflow") or {}
        topic_key = str(task.get("topic_focus") or workflow.get("topic_focus") or "").strip()
        return topic_key or None

    async def _upsert_reflection_bridge_evidence(
        self,
        *,
        memory_type: str,
        memory_id: str,
        learner_profile_id: str,
        learner_goal_id: str | None,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
        ) -> None:
        if self._evidence_link_repository is None:
            return
        role = MemoryNormalizer.classify_evidence_role(
            memory_type=memory_type,
            evidence_source_type="reflection_outcome",
            evaluation_status=evaluation.evaluation_status,
        )
        weight_key = "reflection_effective_weight" if role == "supporting" else "reflection_ineffective_weight"
        await self._evidence_link_repository.upsert(
            MemoryEvidenceLink.build(
                memory_type=memory_type,
                memory_id=memory_id,
                learner_profile_id=learner_profile_id,
                learner_goal_id=learner_goal_id,
                evidence_source_type="reflection_outcome",
                evidence_source_id=evaluation.id,
                evidence_role=role,
                signal_type=f"reflection:{evaluation.evaluation_status}",
                weight=float(self._governance_config[weight_key]),
                payload={
                    "reflection_record_id": reflection.id,
                    "evaluation_status": evaluation.evaluation_status,
                    "improvement_score": evaluation.improvement_score,
                },
                observed_at=evaluation.updated_at,
            )
        )
        observe_memory_evidence_upsert(
            memory_type=memory_type,
            evidence_source_type="reflection_outcome",
            evidence_role=role,
        )

    def _build_compressed_knowledge_memory(self, memories: list[KnowledgeMemory]) -> KnowledgeMemory:
        merged_source_event_ids = self._merge_unique([item.source_event_ids for item in memories])
        merged_source_memory_ids = self._merge_unique([[item.id] + item.source_memory_ids for item in memories])
        prerequisite_keys = self._merge_unique([item.prerequisite_keys for item in memories])
        compressed = KnowledgeMemory.build(
            learner_profile_id=memories[0].learner_profile_id,
            learner_goal_id=memories[0].learner_goal_id,
            knowledge_key=memories[0].knowledge_key,
            title=f"Compressed knowledge: {memories[0].title}",
            summary=self._build_compressed_summary(
                prefix="Knowledge",
                titles=[item.title for item in memories],
                summaries=[item.summary for item in memories],
            ),
            details=f"Compressed from {len(memories)} knowledge memories.",
            knowledge_level=self._select_highest_level(
                [item.knowledge_level for item in memories],
                ordered_levels=["foundation", "core", "advanced", "application"],
            ),
            time_horizon="long",
            importance_score=self._clamp_score(max(item.importance_score for item in memories)),
            confidence_score=self._clamp_score(sum(item.confidence_score for item in memories) / len(memories)),
            freshness_score=1.0,
            prerequisite_keys=prerequisite_keys,
            source_event_ids=merged_source_event_ids,
            source_memory_ids=merged_source_memory_ids,
            tags=self._merge_unique([item.tags for item in memories]) + ["compressed"],
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

    def _build_compressed_behavior_memory(self, memories: list[BehaviorMemory]) -> BehaviorMemory:
        merged_source_event_ids = self._merge_unique([item.source_event_ids for item in memories])
        merged_source_memory_ids = self._merge_unique([[item.id] + item.source_memory_ids for item in memories])
        compressed = BehaviorMemory.build(
            learner_profile_id=memories[0].learner_profile_id,
            learner_goal_id=memories[0].learner_goal_id,
            behavior_key=memories[0].behavior_key,
            behavior_category=memories[0].behavior_category,
            title=f"Compressed behavior: {memories[0].title}",
            summary=self._build_compressed_summary(
                prefix="Behavior",
                titles=[item.title for item in memories],
                summaries=[item.summary for item in memories],
            ),
            details=f"Compressed from {len(memories)} behavior memories.",
            behavior_level=self._select_highest_level(
                [item.behavior_level for item in memories],
                ordered_levels=["surface", "recurrent", "persistent", "critical"],
            ),
            time_horizon="long",
            importance_score=self._clamp_score(max(item.importance_score for item in memories)),
            confidence_score=self._clamp_score(sum(item.confidence_score for item in memories) / len(memories)),
            freshness_score=1.0,
            source_event_ids=merged_source_event_ids,
            source_memory_ids=merged_source_memory_ids,
            tags=self._merge_unique([item.tags for item in memories]) + ["compressed"],
            intervention_effect=self._build_behavior_intervention_effect(
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

    def _cluster_knowledge_memories(self, memories: list[KnowledgeMemory]) -> list[list[KnowledgeMemory]]:
        grouped: dict[tuple[str, str], list[KnowledgeMemory]] = {}
        for memory in memories:
            grouped.setdefault((memory.scope_type, memory.knowledge_key), []).append(memory)
        return [group for group in grouped.values() if len(group) > 1]

    def _cluster_behavior_memories(self, memories: list[BehaviorMemory]) -> list[list[BehaviorMemory]]:
        grouped: dict[tuple[str, str], list[BehaviorMemory]] = {}
        for memory in memories:
            grouped.setdefault((memory.scope_type, memory.behavior_key), []).append(memory)
        return [group for group in grouped.values() if len(group) > 1]
