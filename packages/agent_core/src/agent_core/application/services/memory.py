from __future__ import annotations

from typing import Any

from agent_core.infrastructure.observability.metrics import observe_memory_quality_assessment

from agent_core.application.services.audit import AuditService
from agent_core.application.services.memory_normalization import MemoryNormalizer
from agent_core.domain.entities.autonomy import LearnerTopicMastery, TaskAttempt
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    BehaviorMemoryEmbeddingRecord,
    BehaviorMemoryRetrievalResult,
    KnowledgeMemory,
    KnowledgeMemoryEmbeddingRecord,
    KnowledgeMemoryRetrievalResult,
    MemoryAnnotation,
    MemoryConflictMember,
    MemoryConflictSet,
    MemoryEvent,
    MemoryEvidenceLink,
    MemoryGovernanceDecision,
    MemoryPromotionEligibilityRecord,
    MemoryRetrievalResult,
    RetrievedBehaviorMemory,
    RetrievedKnowledgeMemory,
    RetrievedMemory,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt
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
    MemoryPromotionEligibilityRepository,
    MemoryConflictRepository,
    TaskAttemptRepository,
)
from agent_core.infrastructure.embedding.types import EmbeddingProvider

# ── learner_memory sub-package re-exports (backward-compat) ──────────────────
from agent_core.application.services.learner_memory.result_types import (
    BrowseMemoriesResult,
    LongTermMemoryUpsertResult,
    LongTermMemoryWriteResult,
    MemoryConflictMemberDetail,
    MemoryGovernanceSummary,
    MemoryInterpretationFact,
    MemoryInterpretationResult,
    MemoryMaintenanceBatchResult,
    MemoryMaintenanceResult,
    ReflectionCorpusMemoryItem,
    ReflectionCorpusResult,
    ReflectionCorpusSummary,
)
from agent_core.application.services.learner_memory.constants import (
    BEHAVIOR_EVIDENCE_WEIGHTS,
    KNOWLEDGE_EVIDENCE_WEIGHTS,
    BehaviorEvidenceWeights,
    KnowledgeEvidenceWeights,
    default_governance_config as _default_governance_config_fn,
)
from agent_core.application.services.learner_memory import quality as _quality
from agent_core.application.services.learner_memory.candidate_builders import (
    CandidateBuilderService,
    build_behavior_intervention_effect as _build_behavior_intervention_effect_fn,
    build_behavior_memory as _build_behavior_memory_fn,
    build_knowledge_memory as _build_knowledge_memory_fn,
    topic_alignment_score as _topic_alignment_score_fn,
    topic_matches as _topic_matches_fn,
)
from agent_core.application.services.learner_memory.catalog import CatalogService
from agent_core.application.services.learner_memory.conflicts import ConflictService
from agent_core.application.services.learner_memory.evidence import EvidenceService
from agent_core.application.services.learner_memory.governance import GovernanceService
from agent_core.application.services.learner_memory.governance_batches import GovernanceBatchService
from agent_core.application.services.learner_memory.interpretation import InterpretationService
from agent_core.application.services.learner_memory.observability import ObservabilityService
from agent_core.application.services.learner_memory.reflection_corpus import ReflectionCorpusService
from agent_core.application.services.learner_memory.retrieval import RetrievalService
from agent_core.application.services.learner_memory.session_events import SessionEventRecorder
from agent_core.application.services.learner_memory.upsert import (
    UpsertService,
    has_material_refresh_change as _has_material_refresh_change_fn,
    merge_knowledge_memory as _merge_knowledge_memory_fn,
    merge_behavior_memory as _merge_behavior_memory_fn,
)


class MemoryService:
    """Compatibility facade: all public methods delegate to learner_memory sub-services.

    The sub-services (CatalogService, RetrievalService, etc.) hold the real
    implementation.  This class only wires dependencies, exposes the original
    public API surface, and preserves static/class helpers that existing tests
    call directly.
    """

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
        promotion_eligibility_repository: MemoryPromotionEligibilityRepository | None = None,
        annotation_repository: MemoryAnnotationRepository | None = None,
        task_attempt_repository: TaskAttemptRepository | None = None,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None = None,
        governance_config: dict[str, float | int] | None = None,
    ) -> None:
        self._repository = repository
        self._embedding_provider = embedding_provider
        self._governance_config = governance_config or self._default_governance_config()

        self._catalog_service = CatalogService(
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
            evidence_link_repository=evidence_link_repository,
            governance_decision_repository=governance_decision_repository,
            annotation_repository=annotation_repository,
            conflict_repository=conflict_repository,
        )
        self._retrieval_service = RetrievalService(
            embedding_provider=embedding_provider,
            embedding_repository=embedding_repository,
            knowledge_memory_embedding_repository=knowledge_memory_embedding_repository,
            behavior_memory_embedding_repository=behavior_memory_embedding_repository,
            promotion_eligibility_repository=promotion_eligibility_repository,
            governance_config=self._governance_config,
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
        )
        self._interpretation_service = InterpretationService(
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
            conflict_repository=conflict_repository,
        )
        self._observability_service = ObservabilityService(
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
            conflict_repository=conflict_repository,
        )
        self._session_event_recorder = SessionEventRecorder(
            repository=repository,
            embedding_provider=embedding_provider,
            embedding_repository=embedding_repository,
            audit_service=audit_service,
        )
        self._candidate_builder = CandidateBuilderService()
        self._upsert_service = UpsertService(
            knowledge_memory_repository=knowledge_memory_repository,
            knowledge_memory_embedding_repository=knowledge_memory_embedding_repository,
            behavior_memory_repository=behavior_memory_repository,
            behavior_memory_embedding_repository=behavior_memory_embedding_repository,
            embedding_provider=embedding_provider,
            audit_service=audit_service,
        )
        self._evidence_service = EvidenceService(
            evidence_link_repository=evidence_link_repository,
            task_attempt_repository=task_attempt_repository,
            learner_topic_mastery_repository=learner_topic_mastery_repository,
            memory_event_repository=repository,
            governance_config=self._governance_config,
        )
        self._governance_service = GovernanceService(
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
            governance_decision_repository=governance_decision_repository,
            promotion_eligibility_repository=promotion_eligibility_repository,
            annotation_repository=annotation_repository,
            evidence_link_repository=evidence_link_repository,
            audit_service=audit_service,
            upsert_service=self._upsert_service,
            governance_config=self._governance_config,
        )
        self._conflict_service = ConflictService(
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
            conflict_repository=conflict_repository,
            refresh_observability_metrics=self.refresh_observability_metrics,
        )
        self._reflection_corpus_service = ReflectionCorpusService(
            knowledge_memory_repository=knowledge_memory_repository,
            behavior_memory_repository=behavior_memory_repository,
            governance_decision_repository=governance_decision_repository,
            evidence_link_repository=evidence_link_repository,
            audit_service=audit_service,
            governance_config=self._governance_config,
        )
        self._governance_batch_service = GovernanceBatchService(
            knowledge_memory_repository=knowledge_memory_repository,
            knowledge_memory_embedding_repository=knowledge_memory_embedding_repository,
            behavior_memory_repository=behavior_memory_repository,
            behavior_memory_embedding_repository=behavior_memory_embedding_repository,
            conflict_repository=conflict_repository,
            promotion_eligibility_repository=promotion_eligibility_repository,
            embedding_provider=embedding_provider,
            evidence_service=self._evidence_service,
            governance_service=self._governance_service,
            upsert_service=self._upsert_service,
            refresh_observability_metrics=self.refresh_observability_metrics,
            governance_config=self._governance_config,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def embedding_provider_name(self) -> str | None:
        return self._embedding_provider.provider_name if self._embedding_provider is not None else None

    @property
    def embedding_model_name(self) -> str | None:
        return self._embedding_provider.model_name if self._embedding_provider is not None else None

    # ── Session event recording ───────────────────────────────────────────────

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
        return await self._session_event_recorder.record_session_event(
            session_id=session_id,
            learner_profile_id=learner_profile_id,
            memory_scope=memory_scope,
            memory_level=memory_level,
            summary=summary,
            progress_note=progress_note,
            struggle_note=struggle_note,
            concept_focus=concept_focus,
            source_message_id=source_message_id,
            tags=tags,
        )

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

    def extract_learning_signals(
        self,
        *,
        learner_message: str,
        assistant_message: str,
        mode: str | None,
        subject: str | None,
        session_title: str | None,
    ) -> list[dict[str, str | list[str] | None]]:
        return self._session_event_recorder.extract_learning_signals(
            learner_message=learner_message,
            assistant_message=assistant_message,
            mode=mode,
            subject=subject,
            session_title=session_title,
        )

    # ── Candidate builders ────────────────────────────────────────────────────

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
        return self._candidate_builder.build_knowledge_memory_candidate(
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
        return self._candidate_builder.build_behavior_memory_candidate(
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

    # ── Upsert ────────────────────────────────────────────────────────────────

    async def upsert_knowledge_memory(
        self,
        memory: KnowledgeMemory,
        *,
        persist_embedding: bool = False,
    ) -> LongTermMemoryUpsertResult:
        return await self._upsert_service.upsert_knowledge_memory(
            memory, persist_embedding=persist_embedding,
        )

    async def upsert_behavior_memory(
        self,
        memory: BehaviorMemory,
        *,
        persist_embedding: bool = False,
    ) -> LongTermMemoryUpsertResult:
        return await self._upsert_service.upsert_behavior_memory(
            memory, persist_embedding=persist_embedding,
        )

    # ── Retrieval ─────────────────────────────────────────────────────────────

    async def retrieve_relevant_session_memories(
        self, *, session_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
    ) -> MemoryRetrievalResult:
        return await self._retrieval_service.retrieve_relevant_session_memories(
            session_id=session_id, query_text=query_text, limit=limit,
            candidate_limit=candidate_limit, min_score=min_score,
        )

    async def retrieve_relevant_profile_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
    ) -> MemoryRetrievalResult:
        return await self._retrieval_service.retrieve_relevant_profile_memories(
            learner_profile_id=learner_profile_id, query_text=query_text, limit=limit,
            candidate_limit=candidate_limit, min_score=min_score,
        )

    async def retrieve_relevant_knowledge_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
        surface: str = "default",
        learner_facing: bool | None = None,
    ) -> KnowledgeMemoryRetrievalResult:
        if learner_facing is not None and surface == "default":
            surface = "chat" if learner_facing else "default"
        return await self._retrieval_service.retrieve_relevant_knowledge_memories(
            learner_profile_id=learner_profile_id, query_text=query_text, limit=limit,
            candidate_limit=candidate_limit, min_score=min_score,
            surface=surface,
        )

    async def retrieve_relevant_behavior_memories(
        self, *, learner_profile_id: str, query_text: str, limit: int = 3,
        candidate_limit: int = 24, min_score: float = 0.15,
        surface: str = "default",
        learner_facing: bool | None = None,
    ) -> BehaviorMemoryRetrievalResult:
        if learner_facing is not None and surface == "default":
            surface = "chat" if learner_facing else "default"
        return await self._retrieval_service.retrieve_relevant_behavior_memories(
            learner_profile_id=learner_profile_id, query_text=query_text, limit=limit,
            candidate_limit=candidate_limit, min_score=min_score,
            surface=surface,
        )

    # ── Catalog (browse / detail / read) ─────────────────────────────────────

    async def get_knowledge_memory(self, memory_id: str) -> KnowledgeMemory:
        return await self._catalog_service.get_knowledge_memory(memory_id)

    async def get_behavior_memory(self, memory_id: str) -> BehaviorMemory:
        return await self._catalog_service.get_behavior_memory(memory_id)

    async def describe_knowledge_memory(self, memory: KnowledgeMemory) -> dict[str, Any]:
        snapshot = await self._memory_quality_snapshot("knowledge", memory)
        return {**memory.__dict__, **snapshot}

    async def describe_behavior_memory(self, memory: BehaviorMemory) -> dict[str, Any]:
        snapshot = await self._memory_quality_snapshot("behavior", memory)
        return {**memory.__dict__, **snapshot}

    async def _memory_quality_snapshot(
        self,
        memory_type: str,
        memory: KnowledgeMemory | BehaviorMemory,
    ) -> dict[str, object]:
        """Compute quality snapshot with evidence mix for describe_* methods."""
        links = await self._evidence_service.list_evidence_links(
            memory_type=memory_type, memory_id=memory.id,
        )
        evidence_mix: dict[str, float] = {}
        if links:
            weights: dict[str, float] = {}
            total = 0.0
            for link in links:
                weights[link.evidence_source_type] = weights.get(link.evidence_source_type, 0.0) + link.weight
                total += link.weight
            if total > 0:
                evidence_mix = {k: round(v / total, 4) for k, v in sorted(weights.items())}
        snapshot = _quality.memory_quality_snapshot_sync(
            memory,
            governance_config=self._governance_config,
            evidence_mix=evidence_mix,
        )
        observe_memory_quality_assessment(
            memory_type=memory_type,
            quality_tier=str(snapshot["quality_tier"]),
            promotion_readiness=str(snapshot["promotion_readiness"]),
        )
        return snapshot

    async def browse_knowledge_memories(
        self, *, learner_profile_id: str, learner_goal_id: str | None = None,
        statuses: set[str] | None = None, limit: int = 20, offset: int = 0,
    ) -> BrowseMemoriesResult:
        return await self._catalog_service.browse_knowledge_memories(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            statuses=statuses, limit=limit, offset=offset,
        )

    async def browse_behavior_memories(
        self, *, learner_profile_id: str, learner_goal_id: str | None = None,
        statuses: set[str] | None = None, limit: int = 20, offset: int = 0,
    ) -> BrowseMemoriesResult:
        return await self._catalog_service.browse_behavior_memories(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            statuses=statuses, limit=limit, offset=offset,
        )

    async def list_evidence_links(self, *, memory_type: str, memory_id: str) -> list[MemoryEvidenceLink]:
        return await self._catalog_service.list_evidence_links(memory_type=memory_type, memory_id=memory_id)

    async def list_governance_decisions(self, *, memory_type: str, memory_id: str) -> list[MemoryGovernanceDecision]:
        return await self._catalog_service.list_governance_decisions(memory_type=memory_type, memory_id=memory_id)

    async def list_annotations(self, *, memory_type: str, memory_id: str) -> list[MemoryAnnotation]:
        return await self._catalog_service.list_annotations(memory_type=memory_type, memory_id=memory_id)

    async def list_conflict_sets(
        self, *, learner_profile_id: str, learner_goal_id: str | None = None,
        status: str | None = None, limit: int = 50,
    ) -> list[MemoryConflictSet]:
        return await self._catalog_service.list_conflict_sets(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            status=status, limit=limit,
        )

    async def list_conflict_members(self, *, conflict_set_id: str) -> list[MemoryConflictMember]:
        return await self._catalog_service.list_conflict_members(conflict_set_id=conflict_set_id)

    async def list_conflict_member_details(self, *, conflict_set_id: str) -> list[MemoryConflictMemberDetail]:
        return await self._catalog_service.list_conflict_member_details(conflict_set_id=conflict_set_id)

    # ── Interpretation ────────────────────────────────────────────────────────

    async def build_interpretation(
        self, *, learner_profile_id: str, learner_goal_id: str | None = None, limit_per_type: int = 8,
    ) -> MemoryInterpretationResult:
        return await self._interpretation_service.build_interpretation(
            learner_profile_id=learner_profile_id, learner_goal_id=learner_goal_id,
            limit_per_type=limit_per_type,
        )

    # ── Reflection corpus & governance summary ────────────────────────────────

    async def build_reflection_corpus(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        limit_per_type: int = 8,
    ) -> ReflectionCorpusResult:
        return await self._reflection_corpus_service.build_reflection_corpus(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            limit_per_type=limit_per_type,
        )

    async def build_governance_summary(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
    ) -> MemoryGovernanceSummary:
        return await self._reflection_corpus_service.build_governance_summary(
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
        )

    # ── Operator governance ───────────────────────────────────────────────────

    async def suppress_memory(
        self,
        *,
        memory_type: str,
        memory_id: str,
        reason_code: str,
        note: str | None,
        actor_id: str,
    ) -> KnowledgeMemory | BehaviorMemory:
        return await self._governance_service.suppress_memory(
            memory_type=memory_type,
            memory_id=memory_id,
            reason_code=reason_code,
            note=note,
            actor_id=actor_id,
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
        return await self._governance_service.restore_memory(
            memory_type=memory_type,
            memory_id=memory_id,
            restore_to_status=restore_to_status,
            reason=reason,
            actor_id=actor_id,
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
        return await self._governance_service.annotate_memory(
            memory_type=memory_type,
            memory_id=memory_id,
            annotation_code=annotation_code,
            note=note,
            actor_id=actor_id,
        )

    # ── Evidence ──────────────────────────────────────────────────────────────

    async def upsert_session_memory_event_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        event: MemoryEvent,
    ) -> None:
        await self._evidence_service.upsert_session_memory_event_evidence(
            memory=memory,
            memory_type=memory_type,
            event=event,
        )

    async def upsert_task_attempt_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        attempt: TaskAttempt,
    ) -> None:
        await self._evidence_service.upsert_task_attempt_evidence(
            memory=memory,
            memory_type=memory_type,
            attempt=attempt,
        )

    async def upsert_quiz_answer_attempt_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        attempt: SessionQuizAnswerAttempt,
    ) -> None:
        await self._evidence_service.upsert_quiz_answer_attempt_evidence(
            memory=memory,
            memory_type=memory_type,
            attempt=attempt,
        )

    async def upsert_reflection_outcome_evidence(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        memory_type: str,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
    ) -> None:
        await self._evidence_service.upsert_reflection_bridge_evidence(
            memory_type=memory_type,
            memory_id=memory.id,
            learner_profile_id=memory.learner_profile_id,
            learner_goal_id=memory.learner_goal_id,
            reflection=reflection,
            evaluation=evaluation,
        )

    # ── Maintenance & batch governance ────────────────────────────────────────

    async def run_memory_maintenance(self, *, batch_size: int = 5) -> MemoryMaintenanceResult:
        return await self._governance_batch_service.run_memory_maintenance(
            batch_size=batch_size,
            refresh_conflict_sets=self.refresh_conflict_sets,
        )

    async def list_maintenance_profile_ids(self) -> list[str]:
        return await self._governance_batch_service.list_maintenance_profile_ids()

    async def run_knowledge_governance_batch(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._governance_batch_service.run_knowledge_governance_batch(
            learner_profile_id=learner_profile_id, cursor=cursor, batch_size=batch_size,
        )

    async def run_knowledge_promotion_eligibility_batch(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._governance_batch_service.run_knowledge_promotion_eligibility_batch(
            learner_profile_id=learner_profile_id, cursor=cursor, batch_size=batch_size,
        )

    async def run_behavior_governance_batch(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._governance_batch_service.run_behavior_governance_batch(
            learner_profile_id=learner_profile_id, cursor=cursor, batch_size=batch_size,
        )

    async def compress_knowledge_memories_for_profile(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._governance_batch_service.compress_knowledge_memories_for_profile(
            learner_profile_id=learner_profile_id,
            cursor=cursor,
            batch_size=batch_size,
        )

    async def compress_behavior_memories_for_profile(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._governance_batch_service.compress_behavior_memories_for_profile(
            learner_profile_id=learner_profile_id,
            cursor=cursor,
            batch_size=batch_size,
        )

    async def compress_knowledge_memories(self, *, batch_size: int = 5) -> int:
        return await self._governance_batch_service.compress_knowledge_memories(batch_size=batch_size)

    async def compress_behavior_memories(self, *, batch_size: int = 5) -> int:
        return await self._governance_batch_service.compress_behavior_memories(batch_size=batch_size)

    # ── Conflict management ───────────────────────────────────────────────────

    async def refresh_conflict_sets_for_profile(
        self, *, learner_profile_id: str, cursor: str | None, batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._conflict_service.refresh_conflict_sets_for_profile(
            learner_profile_id=learner_profile_id,
            cursor=cursor,
            batch_size=batch_size,
        )

    async def refresh_conflict_sets(self) -> int:
        return await self._conflict_service.refresh_conflict_sets()

    # ── Reflection bridge ─────────────────────────────────────────────────────

    async def bridge_reflection_outcome(
        self,
        *,
        reflection: ReflectionRecord,
        evaluation: ReflectionOutcomeEvaluation,
    ) -> int:
        return await self._governance_batch_service.bridge_reflection_outcome(
            reflection=reflection,
            evaluation=evaluation,
        )

    # ── Observability ─────────────────────────────────────────────────────────

    async def refresh_observability_metrics(self) -> None:
        await self._observability_service.refresh_observability_metrics()

    # ── Backward-compat static / class method wrappers ────────────────────────
    # Tests call these directly on MemoryService; keep as thin delegation.

    @classmethod
    def _topic_matches(
        cls,
        topic_key: str,
        candidate_key: str,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> bool:
        return _topic_matches_fn(topic_key, candidate_key, title=title, tags=tags)

    @classmethod
    def _topic_alignment_score(
        cls,
        topic_key: str,
        candidate_key: str,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
        extras: list[str] | None = None,
    ) -> float:
        return _topic_alignment_score_fn(
            topic_key, candidate_key, title=title, tags=tags, extras=extras,
        )

    @staticmethod
    def _default_governance_config() -> dict[str, float | int]:
        return _default_governance_config_fn()

    @staticmethod
    def _quality_tier(quality_score: float) -> str:
        return _quality.quality_tier(quality_score)

    @staticmethod
    def _governance_pressure(memory: KnowledgeMemory | BehaviorMemory) -> float:
        return _quality.governance_pressure(memory)

    @staticmethod
    def _review_recommended(memory: KnowledgeMemory | BehaviorMemory) -> bool:
        return _quality.review_recommended(memory)

    def _knowledge_quality_score(self, memory: KnowledgeMemory) -> float:
        return _quality.knowledge_quality_score(memory)

    def _behavior_quality_score(self, memory: BehaviorMemory) -> float:
        return _quality.behavior_quality_score(memory)

    def _knowledge_promotion_readiness(self, memory: KnowledgeMemory, quality_score: float) -> str:
        return _quality.knowledge_promotion_readiness(memory, quality_score, self._governance_config)

    def _behavior_promotion_readiness(self, memory: BehaviorMemory, quality_score: float) -> str:
        return _quality.behavior_promotion_readiness(memory, quality_score, self._governance_config)

    def _quality_reasons(
        self,
        *,
        memory: KnowledgeMemory | BehaviorMemory,
        quality_score: float,
        readiness: str,
    ) -> list[str]:
        """Return the list of reason codes for a memory's quality assessment."""
        return _quality.quality_reasons(memory=memory, quality_score=quality_score, readiness=readiness)

    def _is_knowledge_promotion_candidate(self, memory: KnowledgeMemory) -> bool:
        """Return True if the knowledge memory is ready for promotion.

        A memory is NOT a candidate if:
        - Promotion readiness is not ``ready``.
        - Validation status is ``contested``.
        """
        if getattr(memory, "validation_status", None) == "contested":
            return False
        quality_score = _quality.knowledge_quality_score(memory)
        readiness = _quality.knowledge_promotion_readiness(memory, quality_score, self._governance_config)
        return readiness == "ready"

    def _is_behavior_promotion_candidate(self, memory: BehaviorMemory) -> bool:
        """Return True if the behavior memory is ready for promotion.

        A memory is NOT a candidate if:
        - Promotion readiness is not ``ready``.
        - Validation status is ``contested``.
        """
        if getattr(memory, "validation_status", None) == "contested":
            return False
        quality_score = _quality.behavior_quality_score(memory)
        readiness = _quality.behavior_promotion_readiness(memory, quality_score, self._governance_config)
        return readiness == "ready"

    async def _govern_knowledge_status(
        self,
        memory: KnowledgeMemory,
        *,
        eligibility: MemoryPromotionEligibilityRecord | None = None,
        eligibility_prefetched: bool = False,
    ) -> str:
        return await self._governance_service.govern_knowledge_status(
            memory,
            eligibility=eligibility,
            eligibility_prefetched=eligibility_prefetched,
        )

    def _govern_behavior_status(self, memory: BehaviorMemory) -> str:
        return self._governance_service.govern_behavior_status(memory)

    # Thin wrappers used by LongTermMemoryMaterializationService and tests
    async def _sync_knowledge_embedding(self, memory: KnowledgeMemory, *, create_missing: bool = False) -> None:
        await self._upsert_service.sync_knowledge_embedding(memory, create_missing=create_missing)

    async def _sync_behavior_embedding(self, memory: BehaviorMemory) -> None:
        await self._upsert_service.sync_behavior_embedding(memory)

    @classmethod
    def _merge_knowledge_memory(cls, *, existing: KnowledgeMemory, incoming: KnowledgeMemory) -> KnowledgeMemory:
        return _merge_knowledge_memory_fn(existing=existing, incoming=incoming)

    @classmethod
    def _merge_behavior_memory(cls, *, existing: BehaviorMemory, incoming: BehaviorMemory) -> BehaviorMemory:
        return _merge_behavior_memory_fn(existing=existing, incoming=incoming)

    def _has_material_refresh_change(
        self,
        previous: KnowledgeMemory | BehaviorMemory,
        refreshed: KnowledgeMemory | BehaviorMemory,
    ) -> bool:
        return _has_material_refresh_change_fn(previous, refreshed)

    def _build_knowledge_memory(self, *args: object, **kwargs: object) -> KnowledgeMemory:
        return _build_knowledge_memory_fn(*args, **kwargs)  # type: ignore[arg-type]

    def _build_behavior_memory(self, *args: object, **kwargs: object) -> BehaviorMemory:
        return _build_behavior_memory_fn(*args, **kwargs)  # type: ignore[arg-type]

    def _build_behavior_intervention_effect(
        self,
        *,
        learner_message: str,
        assistant_message: str,
    ) -> str | None:
        return _build_behavior_intervention_effect_fn(
            learner_message=learner_message,
            assistant_message=assistant_message,
        )

    async def _resolve_knowledge_identity_race(
        self,
        *,
        existing: KnowledgeMemory,
        incoming: KnowledgeMemory,
    ) -> LongTermMemoryUpsertResult:
        return await self._upsert_service._resolve_knowledge_identity_race(
            existing=existing, incoming=incoming,
        )

    async def _resolve_behavior_identity_race(
        self,
        *,
        existing: BehaviorMemory,
        incoming: BehaviorMemory,
    ) -> LongTermMemoryUpsertResult:
        return await self._upsert_service._resolve_behavior_identity_race(
            existing=existing, incoming=incoming,
        )
