from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, and_, cast, desc, distinct, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.autonomy import (
    GoalAutonomyState,
    LearnerAvailability,
    LearnerTopicMastery,
    ScheduledAutonomyJob,
    TaskAttempt,
)
from agent_core.domain.entities.goal import LearnerGoal
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.memory import (
    BehaviorMemory,
    BehaviorMemoryEmbeddingRecord,
    ConflictStatusImpact,
    KnowledgeMemory,
    KnowledgeMemoryEmbeddingRecord,
    MemoryAnnotation,
    MemoryConflictMember,
    MemoryConflictSet,
    MemoryEvidenceLink,
    MemoryEmbeddingRecord,
    MemoryEvent,
    MemoryGovernanceDecision,
)
from agent_core.domain.entities.memory_maintenance import MemoryMaintenanceJob
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.planning import DailyTask, PlanStage, StudyPlan, WorkflowRun
from agent_core.domain.entities.reflection_closure import (
    GoalSkillBinding,
    ReflectionProposal,
    ReflectionProposalApprovalDecision,
    ReflectionProposalEvaluation,
    ReflectionProposalRollout,
    ReflectionProposalRolloutDecision,
    ReflectionProposalRolloutObservation,
    ReflectionProposalSandboxRun,
)
from agent_core.domain.entities.reflection import ReflectionAction, ReflectionRecord
from agent_core.domain.entities.quiz import SessionQuiz, SessionQuizQuestion, StoredSessionQuiz
from agent_core.domain.entities.reflection_v2 import (
    LearnerGoalStrategyCard,
    ReflectionEvidenceSignal,
    ReflectionOutcomeEvaluation,
    ReflectionReviewDecision,
    ReflectiveMemory,
)
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.entities.skill import SkillArtifact, SkillCuratorRecommendation, SkillUsageEvent
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.quiz import QuizQuestion
from agent_core.infrastructure.db.models import (
    AuditEventModel,
    BehaviorMemoryEmbeddingModel,
    BehaviorMemoryModel,
    DailyTaskModel,
    GoalSkillBindingModel,
    GoalAutonomyStateModel,
    LearnerAvailabilityModel,
    LearnerGoalModel,
    LearnerProfileModel,
    KnowledgeMemoryEmbeddingModel,
    KnowledgeMemoryModel,
    LearnerTopicMasteryModel,
    LearningSessionModel,
    MemoryAnnotationModel,
    MemoryConflictMemberModel,
    MemoryConflictSetModel,
    MemoryEvidenceLinkModel,
    MemoryGovernanceDecisionModel,
    MemoryMaintenanceJobModel,
    PlanStageModel,
    ReflectionActionModel,
    ReflectionEvidenceSignalModel,
    ReflectionOutcomeEvaluationModel,
    ReflectionProposalEvaluationModel,
    ReflectionProposalApprovalDecisionModel,
    ReflectionProposalModel,
    ReflectionProposalRolloutDecisionModel,
    ReflectionProposalRolloutModel,
    ReflectionProposalRolloutObservationModel,
    ReflectionProposalSandboxRunModel,
    ReflectionRecordModel,
    ReflectionReviewDecisionModel,
    ReflectiveMemoryModel,
    ScheduledAutonomyJobModel,
    TaskAttemptModel,
    SessionMemoryEmbeddingModel,
    SessionMemoryEventModel,
    SessionMessageModel,
    SessionQuizModel,
    SessionQuizQuestionModel,
    SkillArtifactModel,
    SkillCuratorRecommendationModel,
    SkillUsageEventModel,
    StudyPlanModel,
    WorkflowRunModel,
    LearnerGoalStrategyCardModel,
)

CURRENT_MEMORY_IDENTITY_STATUSES = {"candidate", "active", "stable", "suppressed"}


class MemoryEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: MemoryEvent) -> None:
        model = SessionMemoryEventModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def list_by_profile_since(
        self,
        *,
        learner_profile_id: str,
        since: datetime,
    ) -> list[MemoryEvent]:
        result = await self._session.execute(
            select(SessionMemoryEventModel)
            .where(SessionMemoryEventModel.learner_profile_id == learner_profile_id)
            .where(SessionMemoryEventModel.created_at >= since)
            .order_by(desc(SessionMemoryEventModel.created_at), desc(SessionMemoryEventModel.id))
        )
        return [
            MemoryEvent(
                id=model.id,
                session_id=model.session_id,
                learner_profile_id=model.learner_profile_id,
                event_type=model.event_type,
                memory_scope=model.memory_scope,
                memory_level=model.memory_level,
                summary=model.summary,
                progress_note=model.progress_note,
                struggle_note=model.struggle_note,
                concept_focus=model.concept_focus,
                source_message_id=model.source_message_id,
                tags=list(model.tags or []),
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]

    async def list_by_session(self, session_id: str, *, limit: int = 50) -> list[MemoryEvent]:
        result = await self._session.execute(
            select(SessionMemoryEventModel)
            .where(SessionMemoryEventModel.session_id == session_id)
            .order_by(desc(SessionMemoryEventModel.created_at), desc(SessionMemoryEventModel.id))
            .limit(limit)
        )
        return [
            MemoryEvent(
                id=model.id,
                session_id=model.session_id,
                learner_profile_id=model.learner_profile_id,
                event_type=model.event_type,
                memory_scope=model.memory_scope,
                memory_level=model.memory_level,
                summary=model.summary,
                progress_note=model.progress_note,
                struggle_note=model.struggle_note,
                concept_focus=model.concept_focus,
                source_message_id=model.source_message_id,
                tags=list(model.tags or []),
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]



class MemoryEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: MemoryEmbeddingRecord) -> None:
        model = SessionMemoryEmbeddingModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def list_recent_by_session(
        self,
        *,
        session_id: str,
        limit: int,
    ) -> list[MemoryEmbeddingRecord]:
        result = await self._session.execute(
            select(SessionMemoryEmbeddingModel)
            .where(SessionMemoryEmbeddingModel.session_id == session_id)
            .order_by(desc(SessionMemoryEmbeddingModel.created_at), desc(SessionMemoryEmbeddingModel.id))
            .limit(limit)
        )
        models = result.scalars().all()
        return [
            MemoryEmbeddingRecord(
                id=model.id,
                memory_event_id=model.memory_event_id,
                session_id=model.session_id,
                learner_profile_id=model.learner_profile_id,
                memory_scope=model.memory_scope,
                memory_level=model.memory_level,
                provider=model.provider,
                model=model.model,
                dimensions=model.dimensions,
                vector=list(model.vector or []),
                summary=model.summary,
                created_at=model.created_at,
            )
            for model in models
        ]

    async def list_recent_by_profile(
        self,
        *,
        learner_profile_id: str,
        limit: int,
    ) -> list[MemoryEmbeddingRecord]:
        result = await self._session.execute(
            select(SessionMemoryEmbeddingModel)
            .where(SessionMemoryEmbeddingModel.learner_profile_id == learner_profile_id)
            .order_by(desc(SessionMemoryEmbeddingModel.created_at), desc(SessionMemoryEmbeddingModel.id))
            .limit(limit)
        )
        models = result.scalars().all()
        return [
            MemoryEmbeddingRecord(
                id=model.id,
                memory_event_id=model.memory_event_id,
                session_id=model.session_id,
                learner_profile_id=model.learner_profile_id,
                memory_scope=model.memory_scope,
                memory_level=model.memory_level,
                provider=model.provider,
                model=model.model,
                dimensions=model.dimensions,
                vector=list(model.vector or []),
                summary=model.summary,
                created_at=model.created_at,
            )
            for model in models
        ]



class KnowledgeMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: KnowledgeMemory) -> KnowledgeMemory | None:
        try:
            async with self._session.begin_nested():
                model = KnowledgeMemoryModel(**entity.__dict__)
                self._session.add(model)
                await self._session.flush()
        except IntegrityError:
            if entity.status != "candidate":
                raise
            existing = await self.get_by_identity(
                learner_profile_id=entity.learner_profile_id,
                learner_goal_id=entity.learner_goal_id,
                knowledge_key=entity.knowledge_key,
                semantic_category=entity.semantic_category,
                statuses=CURRENT_MEMORY_IDENTITY_STATUSES,
            )
            if existing is None:
                raise
            return existing
        return None

    async def update(self, entity: KnowledgeMemory) -> None:
        model = await self._session.get(KnowledgeMemoryModel, entity.id)
        if model is None:
            return
        model.learner_profile_id = entity.learner_profile_id
        model.learner_goal_id = entity.learner_goal_id
        model.knowledge_key = entity.knowledge_key
        model.title = entity.title
        model.summary = entity.summary
        model.details = entity.details
        model.knowledge_level = entity.knowledge_level
        model.time_horizon = entity.time_horizon
        model.importance_score = entity.importance_score
        model.confidence_score = entity.confidence_score
        model.freshness_score = entity.freshness_score
        model.scope_type = entity.scope_type
        model.stability_score = entity.stability_score
        model.goal_relevance_score = entity.goal_relevance_score
        model.support_score = entity.support_score
        model.contradiction_score = entity.contradiction_score
        model.evidence_count = entity.evidence_count
        model.contradiction_count = entity.contradiction_count
        model.last_supported_at = entity.last_supported_at
        model.last_contradicted_at = entity.last_contradicted_at
        model.promotion_state_changed_at = entity.promotion_state_changed_at
        model.suppressed_reason_code = entity.suppressed_reason_code
        model.suppressed_reason_note = entity.suppressed_reason_note
        model.suppressed_by = entity.suppressed_by
        model.suppressed_at = entity.suppressed_at
        model.prerequisite_keys = list(entity.prerequisite_keys)
        model.source_event_ids = list(entity.source_event_ids)
        model.source_memory_ids = list(entity.source_memory_ids)
        model.tags = list(entity.tags)
        model.status = entity.status
        model.compressed_into_id = entity.compressed_into_id
        model.last_reviewed_at = entity.last_reviewed_at
        model.prerequisite_weight = entity.prerequisite_weight
        model.assessment_evidence_count = entity.assessment_evidence_count
        model.task_evidence_count = entity.task_evidence_count
        model.semantic_category = entity.semantic_category
        model.validation_status = entity.validation_status
        model.provenance_type = entity.provenance_type
        model.provenance_source_id = entity.provenance_source_id
        model.scope_ref = dict(entity.scope_ref)
        model.promotion_rationale = entity.promotion_rationale
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_id(self, memory_id: str) -> KnowledgeMemory | None:
        model = await self._session.get(KnowledgeMemoryModel, memory_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_ids(self, memory_ids: list[str]) -> list[KnowledgeMemory]:
        if not memory_ids:
            return []
        result = await self._session.execute(
            select(KnowledgeMemoryModel).where(KnowledgeMemoryModel.id.in_(memory_ids))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        knowledge_key: str,
        semantic_category: str,
        statuses: set[str] | None = None,
    ) -> KnowledgeMemory | None:
        query = select(KnowledgeMemoryModel).where(
            KnowledgeMemoryModel.learner_profile_id == learner_profile_id,
            KnowledgeMemoryModel.learner_goal_id.is_(None)
            if learner_goal_id is None
            else KnowledgeMemoryModel.learner_goal_id == learner_goal_id,
            KnowledgeMemoryModel.knowledge_key == knowledge_key,
            KnowledgeMemoryModel.semantic_category == semantic_category,
        )
        if statuses is not None:
            query = query.where(KnowledgeMemoryModel.status.in_(sorted(statuses)))
        query = query.order_by(desc(KnowledgeMemoryModel.updated_at), desc(KnowledgeMemoryModel.id)).limit(1)
        result = await self._session.execute(query)
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_profile(
        self,
        learner_profile_id: str,
        *,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[KnowledgeMemory]:
        query = (
            select(KnowledgeMemoryModel)
            .where(KnowledgeMemoryModel.learner_profile_id == learner_profile_id)
            .order_by(desc(KnowledgeMemoryModel.importance_score), desc(KnowledgeMemoryModel.updated_at))
        )
        if learner_goal_id is not None:
            query = query.where(KnowledgeMemoryModel.learner_goal_id == learner_goal_id)
        if statuses is not None:
            query = query.where(KnowledgeMemoryModel.status.in_(sorted(statuses)))
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_profile_after_id(
        self,
        *,
        learner_profile_id: str,
        statuses: set[str],
        after_id: str | None,
        limit: int,
    ) -> list[KnowledgeMemory]:
        query = (
            select(KnowledgeMemoryModel)
            .where(KnowledgeMemoryModel.learner_profile_id == learner_profile_id)
            .where(KnowledgeMemoryModel.status.in_(sorted(statuses)))
            .order_by(KnowledgeMemoryModel.id.asc())
            .limit(limit)
        )
        if after_id is not None:
            query = query.where(KnowledgeMemoryModel.id > after_id)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_profile_ids_with_statuses(self, statuses: set[str]) -> list[str]:
        result = await self._session.execute(
            select(distinct(KnowledgeMemoryModel.learner_profile_id)).where(
                KnowledgeMemoryModel.status.in_(sorted(statuses))
            )
        )
        return [value for value in result.scalars().all() if value is not None]

    async def list_profile_ids_with_active_memories(self) -> list[str]:
        return await self.list_profile_ids_with_statuses({"active", "stable"})

    async def count_by_status(self) -> dict[str, int]:
        result = await self._session.execute(
            select(KnowledgeMemoryModel.status, func.count(KnowledgeMemoryModel.id)).group_by(KnowledgeMemoryModel.status)
        )
        return {status: int(count) for status, count in result.all()}

    @staticmethod
    def _to_entity(model: KnowledgeMemoryModel) -> KnowledgeMemory:
        return KnowledgeMemory(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            knowledge_key=model.knowledge_key,
            title=model.title,
            summary=model.summary,
            details=model.details,
            knowledge_level=model.knowledge_level,
            time_horizon=model.time_horizon,
            importance_score=model.importance_score,
            confidence_score=model.confidence_score,
            freshness_score=model.freshness_score,
            scope_type=model.scope_type,
            stability_score=model.stability_score,
            goal_relevance_score=model.goal_relevance_score,
            support_score=model.support_score,
            contradiction_score=model.contradiction_score,
            evidence_count=model.evidence_count,
            contradiction_count=model.contradiction_count,
            last_supported_at=model.last_supported_at,
            last_contradicted_at=model.last_contradicted_at,
            promotion_state_changed_at=model.promotion_state_changed_at,
            suppressed_reason_code=model.suppressed_reason_code,
            suppressed_reason_note=model.suppressed_reason_note,
            suppressed_by=model.suppressed_by,
            suppressed_at=model.suppressed_at,
            prerequisite_keys=list(model.prerequisite_keys or []),
            source_event_ids=list(model.source_event_ids or []),
            source_memory_ids=list(model.source_memory_ids or []),
            tags=list(model.tags or []),
            status=model.status,
            compressed_into_id=model.compressed_into_id,
            last_reviewed_at=model.last_reviewed_at,
            prerequisite_weight=model.prerequisite_weight,
            assessment_evidence_count=model.assessment_evidence_count,
            task_evidence_count=model.task_evidence_count,
            semantic_category=model.semantic_category,
            validation_status=model.validation_status,
            provenance_type=model.provenance_type,
            provenance_source_id=model.provenance_source_id,
            scope_ref=dict(model.scope_ref or {}),
            promotion_rationale=model.promotion_rationale,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class KnowledgeMemoryEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: KnowledgeMemoryEmbeddingRecord) -> None:
        model = KnowledgeMemoryEmbeddingModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def update(self, entity: KnowledgeMemoryEmbeddingRecord) -> None:
        model = await self._session.get(KnowledgeMemoryEmbeddingModel, entity.id)
        if model is None:
            return
        model.memory_id = entity.memory_id
        model.learner_profile_id = entity.learner_profile_id
        model.learner_goal_id = entity.learner_goal_id
        model.knowledge_key = entity.knowledge_key
        model.title = entity.title
        model.summary = entity.summary
        model.knowledge_level = entity.knowledge_level
        model.time_horizon = entity.time_horizon
        model.importance_score = entity.importance_score
        model.confidence_score = entity.confidence_score
        model.freshness_score = entity.freshness_score
        model.stability_score = entity.stability_score
        model.goal_relevance_score = entity.goal_relevance_score
        model.scope_type = entity.scope_type
        model.provider = entity.provider
        model.model = entity.model
        model.dimensions = entity.dimensions
        model.vector = list(entity.vector)
        model.status = entity.status
        await self._session.flush()

    async def get_by_memory_id(self, memory_id: str) -> KnowledgeMemoryEmbeddingRecord | None:
        result = await self._session.execute(
            select(KnowledgeMemoryEmbeddingModel).where(KnowledgeMemoryEmbeddingModel.memory_id == memory_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_recent_by_profile(
        self,
        *,
        learner_profile_id: str,
        limit: int,
        statuses: set[str] | None = None,
    ) -> list[KnowledgeMemoryEmbeddingRecord]:
        result = await self._session.execute(
            select(KnowledgeMemoryEmbeddingModel)
            .where(KnowledgeMemoryEmbeddingModel.learner_profile_id == learner_profile_id)
            .where(KnowledgeMemoryEmbeddingModel.status.in_(sorted(statuses or {"active", "stable"})))
            .order_by(desc(KnowledgeMemoryEmbeddingModel.created_at), desc(KnowledgeMemoryEmbeddingModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_profile(self, *, learner_profile_id: str) -> list[KnowledgeMemoryEmbeddingRecord]:
        result = await self._session.execute(
            select(KnowledgeMemoryEmbeddingModel)
            .where(KnowledgeMemoryEmbeddingModel.learner_profile_id == learner_profile_id)
            .order_by(desc(KnowledgeMemoryEmbeddingModel.created_at), desc(KnowledgeMemoryEmbeddingModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: KnowledgeMemoryEmbeddingModel) -> KnowledgeMemoryEmbeddingRecord:
        return KnowledgeMemoryEmbeddingRecord(
            id=model.id,
            memory_id=model.memory_id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            knowledge_key=model.knowledge_key,
            title=model.title,
            summary=model.summary,
            knowledge_level=model.knowledge_level,
            time_horizon=model.time_horizon,
            importance_score=model.importance_score,
            confidence_score=model.confidence_score,
            freshness_score=model.freshness_score,
            stability_score=model.stability_score,
            goal_relevance_score=model.goal_relevance_score,
            scope_type=model.scope_type,
            provider=model.provider,
            model=model.model,
            dimensions=model.dimensions,
            vector=list(model.vector or []),
            status=model.status,
            created_at=model.created_at,
        )



class BehaviorMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: BehaviorMemory) -> BehaviorMemory | None:
        try:
            async with self._session.begin_nested():
                model = BehaviorMemoryModel(**entity.__dict__)
                self._session.add(model)
                await self._session.flush()
        except IntegrityError:
            if entity.status != "candidate":
                raise
            existing = await self.get_by_identity(
                learner_profile_id=entity.learner_profile_id,
                learner_goal_id=entity.learner_goal_id,
                behavior_key=entity.behavior_key,
                behavior_category=entity.behavior_category,
                statuses=CURRENT_MEMORY_IDENTITY_STATUSES,
            )
            if existing is None:
                raise
            return existing
        return None

    async def update(self, entity: BehaviorMemory) -> None:
        model = await self._session.get(BehaviorMemoryModel, entity.id)
        if model is None:
            return
        model.learner_profile_id = entity.learner_profile_id
        model.learner_goal_id = entity.learner_goal_id
        model.behavior_key = entity.behavior_key
        model.behavior_category = entity.behavior_category
        model.title = entity.title
        model.summary = entity.summary
        model.details = entity.details
        model.behavior_level = entity.behavior_level
        model.time_horizon = entity.time_horizon
        model.importance_score = entity.importance_score
        model.confidence_score = entity.confidence_score
        model.freshness_score = entity.freshness_score
        model.scope_type = entity.scope_type
        model.stability_score = entity.stability_score
        model.goal_relevance_score = entity.goal_relevance_score
        model.support_score = entity.support_score
        model.contradiction_score = entity.contradiction_score
        model.evidence_count = entity.evidence_count
        model.contradiction_count = entity.contradiction_count
        model.last_supported_at = entity.last_supported_at
        model.last_contradicted_at = entity.last_contradicted_at
        model.promotion_state_changed_at = entity.promotion_state_changed_at
        model.suppressed_reason_code = entity.suppressed_reason_code
        model.suppressed_reason_note = entity.suppressed_reason_note
        model.suppressed_by = entity.suppressed_by
        model.suppressed_at = entity.suppressed_at
        model.source_event_ids = list(entity.source_event_ids)
        model.source_memory_ids = list(entity.source_memory_ids)
        model.tags = list(entity.tags)
        model.intervention_effect = entity.intervention_effect
        model.status = entity.status
        model.compressed_into_id = entity.compressed_into_id
        model.last_reviewed_at = entity.last_reviewed_at
        model.intervention_success_count = entity.intervention_success_count
        model.intervention_failure_count = entity.intervention_failure_count
        model.cross_session_recurrence_count = entity.cross_session_recurrence_count
        model.semantic_category = entity.semantic_category
        model.validation_status = entity.validation_status
        model.provenance_type = entity.provenance_type
        model.provenance_source_id = entity.provenance_source_id
        model.scope_ref = dict(entity.scope_ref)
        model.promotion_rationale = entity.promotion_rationale
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_id(self, memory_id: str) -> BehaviorMemory | None:
        model = await self._session.get(BehaviorMemoryModel, memory_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_ids(self, memory_ids: list[str]) -> list[BehaviorMemory]:
        if not memory_ids:
            return []
        result = await self._session.execute(
            select(BehaviorMemoryModel).where(BehaviorMemoryModel.id.in_(memory_ids))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_identity(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None,
        behavior_key: str,
        behavior_category: str,
        statuses: set[str] | None = None,
    ) -> BehaviorMemory | None:
        query = select(BehaviorMemoryModel).where(
            BehaviorMemoryModel.learner_profile_id == learner_profile_id,
            BehaviorMemoryModel.learner_goal_id.is_(None)
            if learner_goal_id is None
            else BehaviorMemoryModel.learner_goal_id == learner_goal_id,
            BehaviorMemoryModel.behavior_key == behavior_key,
            BehaviorMemoryModel.behavior_category == behavior_category,
        )
        if statuses is not None:
            query = query.where(BehaviorMemoryModel.status.in_(sorted(statuses)))
        query = query.order_by(desc(BehaviorMemoryModel.updated_at), desc(BehaviorMemoryModel.id)).limit(1)
        result = await self._session.execute(query)
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_profile(
        self,
        learner_profile_id: str,
        *,
        learner_goal_id: str | None = None,
        statuses: set[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[BehaviorMemory]:
        query = (
            select(BehaviorMemoryModel)
            .where(BehaviorMemoryModel.learner_profile_id == learner_profile_id)
            .order_by(desc(BehaviorMemoryModel.importance_score), desc(BehaviorMemoryModel.updated_at))
        )
        if learner_goal_id is not None:
            query = query.where(BehaviorMemoryModel.learner_goal_id == learner_goal_id)
        if statuses is not None:
            query = query.where(BehaviorMemoryModel.status.in_(sorted(statuses)))
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_profile_after_id(
        self,
        *,
        learner_profile_id: str,
        statuses: set[str],
        after_id: str | None,
        limit: int,
    ) -> list[BehaviorMemory]:
        query = (
            select(BehaviorMemoryModel)
            .where(BehaviorMemoryModel.learner_profile_id == learner_profile_id)
            .where(BehaviorMemoryModel.status.in_(sorted(statuses)))
            .order_by(BehaviorMemoryModel.id.asc())
            .limit(limit)
        )
        if after_id is not None:
            query = query.where(BehaviorMemoryModel.id > after_id)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_profile_ids_with_statuses(self, statuses: set[str]) -> list[str]:
        result = await self._session.execute(
            select(distinct(BehaviorMemoryModel.learner_profile_id)).where(
                BehaviorMemoryModel.status.in_(sorted(statuses))
            )
        )
        return [value for value in result.scalars().all() if value is not None]

    async def list_profile_ids_with_active_memories(self) -> list[str]:
        return await self.list_profile_ids_with_statuses({"active", "stable"})

    async def count_by_status(self) -> dict[str, int]:
        result = await self._session.execute(
            select(BehaviorMemoryModel.status, func.count(BehaviorMemoryModel.id)).group_by(BehaviorMemoryModel.status)
        )
        return {status: int(count) for status, count in result.all()}

    @staticmethod
    def _to_entity(model: BehaviorMemoryModel) -> BehaviorMemory:
        return BehaviorMemory(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            behavior_key=model.behavior_key,
            behavior_category=model.behavior_category,
            title=model.title,
            summary=model.summary,
            details=model.details,
            behavior_level=model.behavior_level,
            time_horizon=model.time_horizon,
            importance_score=model.importance_score,
            confidence_score=model.confidence_score,
            freshness_score=model.freshness_score,
            scope_type=model.scope_type,
            stability_score=model.stability_score,
            goal_relevance_score=model.goal_relevance_score,
            support_score=model.support_score,
            contradiction_score=model.contradiction_score,
            evidence_count=model.evidence_count,
            contradiction_count=model.contradiction_count,
            last_supported_at=model.last_supported_at,
            last_contradicted_at=model.last_contradicted_at,
            promotion_state_changed_at=model.promotion_state_changed_at,
            suppressed_reason_code=model.suppressed_reason_code,
            suppressed_reason_note=model.suppressed_reason_note,
            suppressed_by=model.suppressed_by,
            suppressed_at=model.suppressed_at,
            source_event_ids=list(model.source_event_ids or []),
            source_memory_ids=list(model.source_memory_ids or []),
            tags=list(model.tags or []),
            intervention_effect=model.intervention_effect,
            status=model.status,
            compressed_into_id=model.compressed_into_id,
            last_reviewed_at=model.last_reviewed_at,
            intervention_success_count=model.intervention_success_count,
            intervention_failure_count=model.intervention_failure_count,
            cross_session_recurrence_count=model.cross_session_recurrence_count,
            semantic_category=model.semantic_category,
            validation_status=model.validation_status,
            provenance_type=model.provenance_type,
            provenance_source_id=model.provenance_source_id,
            scope_ref=dict(model.scope_ref or {}),
            promotion_rationale=model.promotion_rationale,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class BehaviorMemoryEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: BehaviorMemoryEmbeddingRecord) -> None:
        model = BehaviorMemoryEmbeddingModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def update(self, entity: BehaviorMemoryEmbeddingRecord) -> None:
        model = await self._session.get(BehaviorMemoryEmbeddingModel, entity.id)
        if model is None:
            return
        model.memory_id = entity.memory_id
        model.learner_profile_id = entity.learner_profile_id
        model.learner_goal_id = entity.learner_goal_id
        model.behavior_key = entity.behavior_key
        model.behavior_category = entity.behavior_category
        model.title = entity.title
        model.summary = entity.summary
        model.behavior_level = entity.behavior_level
        model.time_horizon = entity.time_horizon
        model.importance_score = entity.importance_score
        model.confidence_score = entity.confidence_score
        model.freshness_score = entity.freshness_score
        model.stability_score = entity.stability_score
        model.goal_relevance_score = entity.goal_relevance_score
        model.scope_type = entity.scope_type
        model.provider = entity.provider
        model.model = entity.model
        model.dimensions = entity.dimensions
        model.vector = list(entity.vector)
        model.status = entity.status
        await self._session.flush()

    async def get_by_memory_id(self, memory_id: str) -> BehaviorMemoryEmbeddingRecord | None:
        result = await self._session.execute(
            select(BehaviorMemoryEmbeddingModel).where(BehaviorMemoryEmbeddingModel.memory_id == memory_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_recent_by_profile(
        self,
        *,
        learner_profile_id: str,
        limit: int,
        statuses: set[str] | None = None,
    ) -> list[BehaviorMemoryEmbeddingRecord]:
        result = await self._session.execute(
            select(BehaviorMemoryEmbeddingModel)
            .where(BehaviorMemoryEmbeddingModel.learner_profile_id == learner_profile_id)
            .where(BehaviorMemoryEmbeddingModel.status.in_(sorted(statuses or {"active", "stable"})))
            .order_by(desc(BehaviorMemoryEmbeddingModel.created_at), desc(BehaviorMemoryEmbeddingModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_profile(self, *, learner_profile_id: str) -> list[BehaviorMemoryEmbeddingRecord]:
        result = await self._session.execute(
            select(BehaviorMemoryEmbeddingModel)
            .where(BehaviorMemoryEmbeddingModel.learner_profile_id == learner_profile_id)
            .order_by(desc(BehaviorMemoryEmbeddingModel.created_at), desc(BehaviorMemoryEmbeddingModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: BehaviorMemoryEmbeddingModel) -> BehaviorMemoryEmbeddingRecord:
        return BehaviorMemoryEmbeddingRecord(
            id=model.id,
            memory_id=model.memory_id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            behavior_key=model.behavior_key,
            behavior_category=model.behavior_category,
            title=model.title,
            summary=model.summary,
            behavior_level=model.behavior_level,
            time_horizon=model.time_horizon,
            importance_score=model.importance_score,
            confidence_score=model.confidence_score,
            freshness_score=model.freshness_score,
            stability_score=model.stability_score,
            goal_relevance_score=model.goal_relevance_score,
            scope_type=model.scope_type,
            provider=model.provider,
            model=model.model,
            dimensions=model.dimensions,
            vector=list(model.vector or []),
            status=model.status,
            created_at=model.created_at,
        )



class MemoryEvidenceLinkRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, entity: MemoryEvidenceLink) -> None:
        model = await self._get_link_model(entity)
        if model is None:
            try:
                async with self._session.begin_nested():
                    self._session.add(MemoryEvidenceLinkModel(**entity.__dict__))
                    await self._session.flush()
                return
            except IntegrityError:
                model = await self._get_link_model(entity)
                if model is None:
                    raise
        model.learner_profile_id = entity.learner_profile_id
        model.learner_goal_id = entity.learner_goal_id
        model.signal_type = entity.signal_type
        model.weight = entity.weight
        model.payload = dict(entity.payload)
        model.observed_at = entity.observed_at
        await self._session.flush()

    async def _get_link_model(self, entity: MemoryEvidenceLink) -> MemoryEvidenceLinkModel | None:
        result = await self._session.execute(
            select(MemoryEvidenceLinkModel).where(
                MemoryEvidenceLinkModel.memory_type == entity.memory_type,
                MemoryEvidenceLinkModel.memory_id == entity.memory_id,
                MemoryEvidenceLinkModel.evidence_source_type == entity.evidence_source_type,
                MemoryEvidenceLinkModel.evidence_source_id == entity.evidence_source_id,
                MemoryEvidenceLinkModel.evidence_role == entity.evidence_role,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_memory(self, *, memory_type: str, memory_id: str) -> list[MemoryEvidenceLink]:
        result = await self._session.execute(
            select(MemoryEvidenceLinkModel)
            .where(
                MemoryEvidenceLinkModel.memory_type == memory_type,
                MemoryEvidenceLinkModel.memory_id == memory_id,
            )
            .order_by(desc(MemoryEvidenceLinkModel.observed_at), desc(MemoryEvidenceLinkModel.id))
        )
        return [
            MemoryEvidenceLink(
                id=model.id,
                memory_type=model.memory_type,
                memory_id=model.memory_id,
                learner_profile_id=model.learner_profile_id,
                learner_goal_id=model.learner_goal_id,
                evidence_source_type=model.evidence_source_type,
                evidence_source_id=model.evidence_source_id,
                evidence_role=model.evidence_role,
                signal_type=model.signal_type,
                weight=model.weight,
                payload=dict(model.payload or {}),
                observed_at=model.observed_at,
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]

    async def list_by_profile(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryEvidenceLink]:
        query = (
            select(MemoryEvidenceLinkModel)
            .where(MemoryEvidenceLinkModel.learner_profile_id == learner_profile_id)
            .order_by(desc(MemoryEvidenceLinkModel.observed_at), desc(MemoryEvidenceLinkModel.id))
            .limit(limit)
        )
        if learner_goal_id is not None:
            query = query.where(MemoryEvidenceLinkModel.learner_goal_id == learner_goal_id)
        result = await self._session.execute(query)
        return [
            MemoryEvidenceLink(
                id=model.id,
                memory_type=model.memory_type,
                memory_id=model.memory_id,
                learner_profile_id=model.learner_profile_id,
                learner_goal_id=model.learner_goal_id,
                evidence_source_type=model.evidence_source_type,
                evidence_source_id=model.evidence_source_id,
                evidence_role=model.evidence_role,
                signal_type=model.signal_type,
                weight=model.weight,
                payload=dict(model.payload or {}),
                observed_at=model.observed_at,
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]



class MemoryGovernanceDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: MemoryGovernanceDecision) -> None:
        self._session.add(MemoryGovernanceDecisionModel(**entity.__dict__))
        await self._session.flush()

    async def list_by_memory(self, *, memory_type: str, memory_id: str) -> list[MemoryGovernanceDecision]:
        result = await self._session.execute(
            select(MemoryGovernanceDecisionModel)
            .where(
                MemoryGovernanceDecisionModel.memory_type == memory_type,
                MemoryGovernanceDecisionModel.memory_id == memory_id,
            )
            .order_by(desc(MemoryGovernanceDecisionModel.created_at), desc(MemoryGovernanceDecisionModel.id))
        )
        return [
            MemoryGovernanceDecision(
                id=model.id,
                memory_type=model.memory_type,
                memory_id=model.memory_id,
                previous_status=model.previous_status,
                new_status=model.new_status,
                decision_type=model.decision_type,
                trigger_source=model.trigger_source,
                actor_type=model.actor_type,
                actor_id=model.actor_id,
                reason_code=model.reason_code,
                reason_note=model.reason_note,
                metrics_snapshot=dict(model.metrics_snapshot or {}),
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]

    async def list_by_profile(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        limit: int = 100,
    ) -> list[MemoryGovernanceDecision]:
        knowledge_query = select(KnowledgeMemoryModel.id).where(KnowledgeMemoryModel.learner_profile_id == learner_profile_id)
        behavior_query = select(BehaviorMemoryModel.id).where(BehaviorMemoryModel.learner_profile_id == learner_profile_id)
        if learner_goal_id is not None:
            knowledge_query = knowledge_query.where(KnowledgeMemoryModel.learner_goal_id == learner_goal_id)
            behavior_query = behavior_query.where(BehaviorMemoryModel.learner_goal_id == learner_goal_id)
        knowledge_ids = [item[0] for item in (await self._session.execute(knowledge_query)).all()]
        behavior_ids = [item[0] for item in (await self._session.execute(behavior_query)).all()]
        if not knowledge_ids and not behavior_ids:
            return []
        clauses = []
        if knowledge_ids:
            clauses.append(
                and_(
                    MemoryGovernanceDecisionModel.memory_type == "knowledge",
                    MemoryGovernanceDecisionModel.memory_id.in_(knowledge_ids),
                )
            )
        if behavior_ids:
            clauses.append(
                and_(
                    MemoryGovernanceDecisionModel.memory_type == "behavior",
                    MemoryGovernanceDecisionModel.memory_id.in_(behavior_ids),
                )
            )
        result = await self._session.execute(
            select(MemoryGovernanceDecisionModel)
            .where(or_(*clauses))
            .order_by(desc(MemoryGovernanceDecisionModel.created_at), desc(MemoryGovernanceDecisionModel.id))
            .limit(limit)
        )
        return [
            MemoryGovernanceDecision(
                id=model.id,
                memory_type=model.memory_type,
                memory_id=model.memory_id,
                previous_status=model.previous_status,
                new_status=model.new_status,
                decision_type=model.decision_type,
                trigger_source=model.trigger_source,
                actor_type=model.actor_type,
                actor_id=model.actor_id,
                reason_code=model.reason_code,
                reason_note=model.reason_note,
                metrics_snapshot=dict(model.metrics_snapshot or {}),
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]



class MemoryAnnotationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: MemoryAnnotation) -> None:
        self._session.add(MemoryAnnotationModel(**entity.__dict__))
        await self._session.flush()

    async def list_by_memory(self, *, memory_type: str, memory_id: str) -> list[MemoryAnnotation]:
        result = await self._session.execute(
            select(MemoryAnnotationModel)
            .where(
                MemoryAnnotationModel.memory_type == memory_type,
                MemoryAnnotationModel.memory_id == memory_id,
            )
            .order_by(desc(MemoryAnnotationModel.created_at), desc(MemoryAnnotationModel.id))
        )
        return [
            MemoryAnnotation(
                id=model.id,
                memory_type=model.memory_type,
                memory_id=model.memory_id,
                annotation_code=model.annotation_code,
                note=model.note,
                created_by=model.created_by,
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]



class MemoryConflictRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_set(
        self,
        *,
        conflict_set: MemoryConflictSet,
        members: list[MemoryConflictMember],
    ) -> tuple[MemoryConflictSet, bool]:
        model = await self._get_open_set_model(conflict_set)
        if model is None:
            try:
                async with self._session.begin_nested():
                    self._session.add(self._set_model_from_entity(conflict_set))
                    for member in members:
                        self._session.add(MemoryConflictMemberModel(**member.__dict__))
                    await self._session.flush()
                return conflict_set, True
            except IntegrityError:
                model = await self._get_open_set_model(conflict_set)
                if model is None:
                    raise
        refreshed = await self._refresh_open_set(model=model, conflict_set=conflict_set, members=members)
        return refreshed, False

    async def _get_open_set_model(self, conflict_set: MemoryConflictSet) -> MemoryConflictSetModel | None:
        result = await self._session.execute(
            select(MemoryConflictSetModel).where(
                MemoryConflictSetModel.learner_profile_id == conflict_set.learner_profile_id,
                MemoryConflictSetModel.learner_goal_id == conflict_set.learner_goal_id,
                MemoryConflictSetModel.topic_key == conflict_set.topic_key,
                MemoryConflictSetModel.conflict_type == conflict_set.conflict_type,
                MemoryConflictSetModel.status == "open",
            )
        )
        return result.scalar_one_or_none()

    async def _refresh_open_set(
        self,
        *,
        model: MemoryConflictSetModel,
        conflict_set: MemoryConflictSet,
        members: list[MemoryConflictMember],
    ) -> MemoryConflictSet:
        model.severity_score = conflict_set.severity_score
        model.summary = conflict_set.summary
        model.reason_code = conflict_set.reason_code
        model.reason_note = conflict_set.reason_note
        model.handling_result = conflict_set.handling_result
        model.status_impact = conflict_set.status_impact.to_payload()
        model.updated_at = conflict_set.updated_at
        await self._session.execute(
            update(MemoryConflictMemberModel)
            .where(MemoryConflictMemberModel.conflict_set_id == model.id)
            .values(stance="superseded")
        )
        for member in members:
            self._session.add(
                MemoryConflictMemberModel(
                    **{
                        **member.__dict__,
                        "conflict_set_id": model.id,
                    }
                )
            )
        await self._session.flush()
        return self._set_to_entity(model)

    async def list_sets_by_profile(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[MemoryConflictSet]:
        query = select(MemoryConflictSetModel).where(
            MemoryConflictSetModel.learner_profile_id == learner_profile_id
        )
        if learner_goal_id is not None:
            query = query.where(MemoryConflictSetModel.learner_goal_id == learner_goal_id)
        if status is not None:
            query = query.where(MemoryConflictSetModel.status == status)
        query = query.order_by(
            desc(MemoryConflictSetModel.severity_score),
            desc(MemoryConflictSetModel.updated_at),
        ).limit(limit)
        result = await self._session.execute(query)
        return [self._set_to_entity(model) for model in result.scalars().all()]

    async def list_open_sets(self) -> list[MemoryConflictSet]:
        result = await self._session.execute(
            select(MemoryConflictSetModel)
            .where(MemoryConflictSetModel.status == "open")
            .order_by(desc(MemoryConflictSetModel.updated_at), desc(MemoryConflictSetModel.id))
        )
        return [self._set_to_entity(model) for model in result.scalars().all()]

    async def list_profile_ids_with_open_sets(self) -> list[str]:
        result = await self._session.execute(
            select(distinct(MemoryConflictSetModel.learner_profile_id)).where(
                MemoryConflictSetModel.status == "open"
            )
        )
        return [value for value in result.scalars().all() if value is not None]

    async def count_open_by_type(self) -> dict[str, int]:
        result = await self._session.execute(
            select(MemoryConflictSetModel.conflict_type, func.count(MemoryConflictSetModel.id))
            .where(MemoryConflictSetModel.status == "open")
            .group_by(MemoryConflictSetModel.conflict_type)
        )
        return {conflict_type: int(count) for conflict_type, count in result.all()}

    async def list_open_sets_by_profile_after_id(
        self,
        *,
        learner_profile_id: str,
        after_id: str | None,
        limit: int,
    ) -> list[MemoryConflictSet]:
        query = (
            select(MemoryConflictSetModel)
            .where(MemoryConflictSetModel.learner_profile_id == learner_profile_id)
            .where(MemoryConflictSetModel.status == "open")
            .order_by(MemoryConflictSetModel.id.asc())
            .limit(limit)
        )
        if after_id is not None:
            query = query.where(MemoryConflictSetModel.id > after_id)
        result = await self._session.execute(query)
        return [self._set_to_entity(model) for model in result.scalars().all()]

    async def list_open_sets_by_goal_topics(
        self,
        *,
        learner_goal_id: str,
        topic_keys: set[str] | None = None,
        updated_at_from: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryConflictSet]:
        query = (
            select(MemoryConflictSetModel)
            .where(MemoryConflictSetModel.learner_goal_id == learner_goal_id)
            .where(MemoryConflictSetModel.status == "open")
        )
        if topic_keys:
            query = query.where(MemoryConflictSetModel.topic_key.in_(sorted(topic_keys)))
        if updated_at_from is not None:
            query = query.where(MemoryConflictSetModel.updated_at >= updated_at_from)
        query = query.order_by(
            desc(MemoryConflictSetModel.severity_score),
            desc(MemoryConflictSetModel.updated_at),
            desc(MemoryConflictSetModel.id),
        ).limit(limit)
        result = await self._session.execute(query)
        return [self._set_to_entity(model) for model in result.scalars().all()]

    async def close_open_set(
        self,
        *,
        conflict_set_id: str,
        status: str,
        summary: str | None = None,
        reason_code: str | None = None,
        reason_note: str | None = None,
        handling_result: str | None = None,
        status_impact: ConflictStatusImpact | None = None,
    ) -> None:
        if status not in {"resolved", "stale", "closed"}:
            raise ValidationError("Unsupported memory conflict closure status.")
        model = await self._session.get(MemoryConflictSetModel, conflict_set_id)
        if model is None or model.status != "open":
            return
        model.status = status
        if summary is not None:
            model.summary = summary
        if reason_code is not None:
            model.reason_code = reason_code
        if reason_note is not None:
            model.reason_note = reason_note
        if handling_result is not None:
            model.handling_result = handling_result
        if status_impact is not None:
            model.status_impact = status_impact.to_payload()
        model.updated_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def list_members(self, *, conflict_set_id: str) -> list[MemoryConflictMember]:
        result = await self._session.execute(
            select(MemoryConflictMemberModel)
            .where(MemoryConflictMemberModel.conflict_set_id == conflict_set_id)
            .order_by(desc(MemoryConflictMemberModel.contradiction_score), desc(MemoryConflictMemberModel.created_at))
        )
        return [self._member_to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _set_model_from_entity(entity: MemoryConflictSet) -> MemoryConflictSetModel:
        return MemoryConflictSetModel(
            id=entity.id,
            learner_profile_id=entity.learner_profile_id,
            learner_goal_id=entity.learner_goal_id,
            topic_key=entity.topic_key,
            conflict_type=entity.conflict_type,
            severity_score=entity.severity_score,
            status=entity.status,
            summary=entity.summary,
            reason_code=entity.reason_code,
            reason_note=entity.reason_note,
            handling_result=entity.handling_result,
            status_impact=entity.status_impact.to_payload(),
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _set_to_entity(model: MemoryConflictSetModel) -> MemoryConflictSet:
        return MemoryConflictSet(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            topic_key=model.topic_key,
            conflict_type=model.conflict_type,
            severity_score=model.severity_score,
            status=model.status,
            summary=model.summary,
            created_at=model.created_at,
            updated_at=model.updated_at,
            reason_code=model.reason_code,
            reason_note=model.reason_note,
            handling_result=model.handling_result,
            status_impact=ConflictStatusImpact.from_payload(dict(model.status_impact or {})),
        )

    @staticmethod
    def _member_to_entity(model: MemoryConflictMemberModel) -> MemoryConflictMember:
        return MemoryConflictMember(
            id=model.id,
            conflict_set_id=model.conflict_set_id,
            memory_type=model.memory_type,
            memory_id=model.memory_id,
            memory_key=model.memory_key,
            stance=model.stance,
            support_score=model.support_score,
            contradiction_score=model.contradiction_score,
            created_at=model.created_at,
        )



class MemoryMaintenanceJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: MemoryMaintenanceJob) -> MemoryMaintenanceJob:
        existing = await self.get_by_idempotency_key(entity.idempotency_key)
        if existing is not None:
            return existing
        try:
            async with self._session.begin_nested():
                self._session.add(MemoryMaintenanceJobModel(**entity.__dict__))
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_by_idempotency_key(entity.idempotency_key)
            if existing is None:
                raise
            return existing
        return entity

    async def get_by_idempotency_key(self, idempotency_key: str) -> MemoryMaintenanceJob | None:
        result = await self._session.execute(
            select(MemoryMaintenanceJobModel).where(MemoryMaintenanceJobModel.idempotency_key == idempotency_key)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_id(self, job_id: str) -> MemoryMaintenanceJob | None:
        model = await self._session.get(MemoryMaintenanceJobModel, job_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_due(self, *, now: datetime, limit: int) -> list[MemoryMaintenanceJob]:
        result = await self._session.execute(
            select(MemoryMaintenanceJobModel)
            .where(
                or_(
                    and_(
                        MemoryMaintenanceJobModel.status == "scheduled",
                        MemoryMaintenanceJobModel.due_at <= now,
                    ),
                    and_(
                        MemoryMaintenanceJobModel.status == "claimed",
                        MemoryMaintenanceJobModel.lease_expires_at.is_not(None),
                        MemoryMaintenanceJobModel.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(MemoryMaintenanceJobModel.due_at.asc(), MemoryMaintenanceJobModel.created_at.asc())
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def claim(
        self,
        entity: MemoryMaintenanceJob,
        *,
        lease_owner: str,
        lease_seconds: int,
    ) -> MemoryMaintenanceJob:
        now = datetime.now(timezone.utc)
        lease_expires_at = now + timedelta(seconds=max(lease_seconds, 1))
        result = await self._session.execute(
            update(MemoryMaintenanceJobModel)
            .where(
                MemoryMaintenanceJobModel.id == entity.id,
                or_(
                    and_(
                        MemoryMaintenanceJobModel.status == "scheduled",
                        MemoryMaintenanceJobModel.due_at <= now,
                    ),
                    and_(
                        MemoryMaintenanceJobModel.status == "claimed",
                        MemoryMaintenanceJobModel.lease_expires_at.is_not(None),
                        MemoryMaintenanceJobModel.lease_expires_at <= now,
                    ),
                ),
            )
            .values(
                status="claimed",
                lease_owner=lease_owner,
                lease_expires_at=lease_expires_at,
                error_code=None,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            raise ValidationError("Memory maintenance job cannot be claimed.")
        model = await self._session.get(MemoryMaintenanceJobModel, entity.id, populate_existing=True)
        if model is None:
            raise ValidationError("Memory maintenance job cannot be claimed.")
        await self._session.flush()
        return self._to_entity(model)

    async def update(self, entity: MemoryMaintenanceJob) -> None:
        model = await self._session.get(MemoryMaintenanceJobModel, entity.id)
        if model is None:
            return
        model.job_type = entity.job_type
        model.status = entity.status
        model.learner_profile_id = entity.learner_profile_id
        model.cursor = entity.cursor
        model.payload = dict(entity.payload)
        model.due_at = entity.due_at
        model.lease_owner = entity.lease_owner
        model.lease_expires_at = entity.lease_expires_at
        model.attempt_count = entity.attempt_count
        model.max_attempts = entity.max_attempts
        model.idempotency_key = entity.idempotency_key
        model.error_code = entity.error_code
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: MemoryMaintenanceJobModel) -> MemoryMaintenanceJob:
        return MemoryMaintenanceJob(
            id=model.id,
            job_type=model.job_type,
            status=model.status,
            learner_profile_id=model.learner_profile_id,
            cursor=model.cursor,
            payload=dict(model.payload or {}),
            due_at=model.due_at,
            lease_owner=model.lease_owner,
            lease_expires_at=model.lease_expires_at,
            attempt_count=model.attempt_count,
            max_attempts=model.max_attempts,
            idempotency_key=model.idempotency_key,
            error_code=model.error_code,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


