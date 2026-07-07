from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, and_, cast, desc, distinct, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

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
from agent_core.domain.value_objects.pagination import bounded_limit
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


class ReflectionRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionRecord) -> ReflectionRecord:
        existing = await self.get_by_dedupe_key(entity.dedupe_key)
        if existing is not None:
            return existing
        self._session.add(
            ReflectionRecordModel(
                id=entity.id,
                learner_profile_id=entity.learner_profile_id,
                learner_goal_id=entity.learner_goal_id,
                daily_task_id=entity.daily_task_id,
                workflow_run_id=entity.workflow_run_id,
                study_plan_id=entity.study_plan_id,
                scope=entity.scope,
                target_type=entity.target_type,
                target_id=entity.target_id,
                trigger_source=entity.trigger_source,
                status=entity.status,
                reflection_depth=entity.reflection_depth,
                dedupe_key=entity.dedupe_key,
                aggregation_key=entity.aggregation_key,
                duplicate_count=entity.duplicate_count,
                priority_score=entity.priority_score,
                last_duplicate_at=entity.last_duplicate_at,
                cooldown_until=entity.cooldown_until,
                primary_root_cause=entity.primary_root_cause,
                secondary_root_causes=entity.secondary_root_causes,
                severity=entity.severity,
                confidence_score=entity.confidence_score,
                summary=entity.summary,
                evidence_summary=entity.evidence_summary,
                recommended_next_step=entity.recommended_next_step,
                evidence_payload=entity.evidence_payload,
                llm_provider=entity.llm_provider,
                llm_model=entity.llm_model,
                llm_latency_ms=entity.llm_latency_ms,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
                processed_at=entity.processed_at,
            )
        )
        await self._session.flush()
        return entity

    async def get_by_id(self, reflection_id: str) -> ReflectionRecord | None:
        model = await self._session.get(ReflectionRecordModel, reflection_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_dedupe_key(self, dedupe_key: str) -> ReflectionRecord | None:
        result = await self._session.execute(
            select(ReflectionRecordModel).where(ReflectionRecordModel.dedupe_key == dedupe_key)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_latest_by_aggregation_key(self, aggregation_key: str) -> ReflectionRecord | None:
        result = await self._session.execute(
            select(ReflectionRecordModel)
            .where(ReflectionRecordModel.aggregation_key == aggregation_key)
            .order_by(desc(ReflectionRecordModel.updated_at), desc(ReflectionRecordModel.id))
            .limit(1)
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def update(self, entity: ReflectionRecord) -> None:
        model = await self._session.get(ReflectionRecordModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.aggregation_key = entity.aggregation_key
        model.duplicate_count = entity.duplicate_count
        model.priority_score = entity.priority_score
        model.last_duplicate_at = entity.last_duplicate_at
        model.cooldown_until = entity.cooldown_until
        model.summary = entity.summary
        model.evidence_summary = entity.evidence_summary
        model.recommended_next_step = entity.recommended_next_step
        model.evidence_payload = entity.evidence_payload
        model.llm_provider = entity.llm_provider
        model.llm_model = entity.llm_model
        model.llm_latency_ms = entity.llm_latency_ms
        model.updated_at = entity.updated_at
        model.processed_at = entity.processed_at
        await self._session.flush()

    async def list_by_goal(
        self,
        learner_goal_id: str,
        *,
        scopes: set[str] | None = None,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ReflectionRecord]:
        query = select(ReflectionRecordModel).where(ReflectionRecordModel.learner_goal_id == learner_goal_id)
        if scopes:
            query = query.where(ReflectionRecordModel.scope.in_(sorted(scopes)))
        if statuses:
            query = query.where(ReflectionRecordModel.status.in_(sorted(statuses)))
        query = query.order_by(desc(ReflectionRecordModel.created_at), desc(ReflectionRecordModel.id)).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def count_by_goal(
        self,
        learner_goal_id: str,
        *,
        scopes: set[str] | None = None,
        statuses: set[str] | None = None,
    ) -> int:
        query = select(func.count()).select_from(ReflectionRecordModel).where(ReflectionRecordModel.learner_goal_id == learner_goal_id)
        if scopes:
            query = query.where(ReflectionRecordModel.scope.in_(sorted(scopes)))
        if statuses:
            query = query.where(ReflectionRecordModel.status.in_(sorted(statuses)))
        result = await self._session.execute(query)
        return int(result.scalar_one())

    async def list_by_task(
        self,
        daily_task_id: str,
        *,
        statuses: set[str] | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ReflectionRecord]:
        query = select(ReflectionRecordModel).where(ReflectionRecordModel.daily_task_id == daily_task_id)
        if statuses:
            query = query.where(ReflectionRecordModel.status.in_(sorted(statuses)))
        query = query.order_by(desc(ReflectionRecordModel.created_at), desc(ReflectionRecordModel.id)).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def count_by_task(self, daily_task_id: str, *, statuses: set[str] | None = None) -> int:
        query = select(func.count()).select_from(ReflectionRecordModel).where(ReflectionRecordModel.daily_task_id == daily_task_id)
        if statuses:
            query = query.where(ReflectionRecordModel.status.in_(sorted(statuses)))
        result = await self._session.execute(query)
        return int(result.scalar_one())

    async def list_review_queue(
        self,
        *,
        statuses: set[str] | None = None,
        priority_min: float = 0.0,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ReflectionRecord]:
        query = select(ReflectionRecordModel).where(ReflectionRecordModel.priority_score >= priority_min)
        if statuses:
            query = query.where(ReflectionRecordModel.status.in_(sorted(statuses)))
        else:
            query = query.where(ReflectionRecordModel.status.in_(["needs_review", "completed", "actioned"]))
        query = query.order_by(
            desc(ReflectionRecordModel.priority_score),
            desc(ReflectionRecordModel.created_at),
            desc(ReflectionRecordModel.id),
        ).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def count_review_queue(
        self,
        *,
        statuses: set[str] | None = None,
        priority_min: float = 0.0,
    ) -> int:
        query = select(func.count()).select_from(ReflectionRecordModel).where(ReflectionRecordModel.priority_score >= priority_min)
        if statuses:
            query = query.where(ReflectionRecordModel.status.in_(sorted(statuses)))
        else:
            query = query.where(ReflectionRecordModel.status.in_(["needs_review", "completed", "actioned"]))
        result = await self._session.execute(query)
        return int(result.scalar_one())

    @staticmethod
    def _to_entity(model: ReflectionRecordModel) -> ReflectionRecord:
        return ReflectionRecord(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            daily_task_id=model.daily_task_id,
            workflow_run_id=model.workflow_run_id,
            study_plan_id=model.study_plan_id,
            scope=model.scope,
            target_type=model.target_type,
            target_id=model.target_id,
            trigger_source=model.trigger_source,
            status=model.status,
            reflection_depth=model.reflection_depth,
            dedupe_key=model.dedupe_key,
            aggregation_key=model.aggregation_key,
            duplicate_count=model.duplicate_count,
            priority_score=model.priority_score,
            last_duplicate_at=model.last_duplicate_at,
            cooldown_until=model.cooldown_until,
            primary_root_cause=model.primary_root_cause,
            secondary_root_causes=list(model.secondary_root_causes or []),
            severity=model.severity,
            confidence_score=model.confidence_score,
            summary=model.summary,
            evidence_summary=model.evidence_summary,
            recommended_next_step=model.recommended_next_step,
            evidence_payload=dict(model.evidence_payload or {}),
            llm_provider=model.llm_provider,
            llm_model=model.llm_model,
            llm_latency_ms=model.llm_latency_ms,
            created_at=model.created_at,
            updated_at=model.updated_at,
            processed_at=model.processed_at,
        )



class ReflectionActionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionAction) -> None:
        self._session.add(
            ReflectionActionModel(
                id=entity.id,
                reflection_record_id=entity.reflection_record_id,
                action_type=entity.action_type,
                risk_level=entity.risk_level,
                status=entity.status,
                approval_required=entity.approval_required,
                payload=entity.payload,
                execution_result=entity.execution_result,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
                executed_at=entity.executed_at,
            )
        )
        await self._session.flush()

    async def update(self, entity: ReflectionAction) -> None:
        model = await self._session.get(ReflectionActionModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.execution_result = entity.execution_result
        model.updated_at = entity.updated_at
        model.executed_at = entity.executed_at
        await self._session.flush()

    async def get_by_id(self, action_id: str) -> ReflectionAction | None:
        model = await self._session.get(ReflectionActionModel, action_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_reflection(self, reflection_record_id: str) -> list[ReflectionAction]:
        result = await self._session.execute(
            select(ReflectionActionModel)
            .where(ReflectionActionModel.reflection_record_id == reflection_record_id)
            .order_by(ReflectionActionModel.created_at.asc(), ReflectionActionModel.id.asc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: ReflectionActionModel) -> ReflectionAction:
        return ReflectionAction(
            id=model.id,
            reflection_record_id=model.reflection_record_id,
            action_type=model.action_type,
            risk_level=model.risk_level,
            status=model.status,
            approval_required=model.approval_required,
            payload=dict(model.payload or {}),
            execution_result=dict(model.execution_result or {}),
            created_at=model.created_at,
            updated_at=model.updated_at,
            executed_at=model.executed_at,
        )



class ReflectionEvidenceSignalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionEvidenceSignal) -> None:
        self._session.add(ReflectionEvidenceSignalModel(**entity.__dict__))
        await self._session.flush()

    async def list_by_goal(self, learner_goal_id: str, *, topic_key: str | None = None, limit: int = 20) -> list[ReflectionEvidenceSignal]:
        query = select(ReflectionEvidenceSignalModel).where(ReflectionEvidenceSignalModel.learner_goal_id == learner_goal_id)
        if topic_key is not None:
            query = query.where(ReflectionEvidenceSignalModel.topic_key == topic_key)
        query = query.order_by(desc(ReflectionEvidenceSignalModel.observed_at), desc(ReflectionEvidenceSignalModel.id)).limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_session(self, session_id: str, *, limit: int = 20) -> list[ReflectionEvidenceSignal]:
        result = await self._session.execute(
            select(ReflectionEvidenceSignalModel)
            .where(ReflectionEvidenceSignalModel.session_id == session_id)
            .order_by(desc(ReflectionEvidenceSignalModel.observed_at), desc(ReflectionEvidenceSignalModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: ReflectionEvidenceSignalModel) -> ReflectionEvidenceSignal:
        return ReflectionEvidenceSignal(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            session_id=model.session_id,
            daily_task_id=model.daily_task_id,
            workflow_run_id=model.workflow_run_id,
            source_type=model.source_type,
            signal_code=model.signal_code,
            topic_key=model.topic_key,
            severity_score=model.severity_score,
            confidence_score=model.confidence_score,
            payload=dict(model.payload or {}),
            observed_at=model.observed_at,
            created_at=model.created_at,
        )



class ReflectionOutcomeEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionOutcomeEvaluation) -> None:
        self._session.add(ReflectionOutcomeEvaluationModel(**entity.__dict__))
        await self._session.flush()

    async def get_by_reflection(self, reflection_record_id: str) -> ReflectionOutcomeEvaluation | None:
        result = await self._session.execute(
            select(ReflectionOutcomeEvaluationModel).where(
                ReflectionOutcomeEvaluationModel.reflection_record_id == reflection_record_id
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_id(self, evaluation_id: str) -> ReflectionOutcomeEvaluation | None:
        model = await self._session.get(ReflectionOutcomeEvaluationModel, evaluation_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_goal_topics(
        self,
        *,
        learner_goal_id: str,
        topic_keys: set[str] | None = None,
        statuses: set[str] | None = None,
        updated_at_from: datetime | None = None,
        limit: int = 20,
    ) -> list[ReflectionOutcomeEvaluation]:
        query = select(ReflectionOutcomeEvaluationModel).where(
            ReflectionOutcomeEvaluationModel.learner_goal_id == learner_goal_id
        )
        if topic_keys:
            query = query.where(ReflectionOutcomeEvaluationModel.topic_key.in_(sorted(topic_keys)))
        if statuses:
            query = query.where(ReflectionOutcomeEvaluationModel.evaluation_status.in_(sorted(statuses)))
        if updated_at_from is not None:
            query = query.where(ReflectionOutcomeEvaluationModel.updated_at >= updated_at_from)
        query = query.order_by(
            desc(ReflectionOutcomeEvaluationModel.updated_at),
            desc(ReflectionOutcomeEvaluationModel.id),
        ).limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, entity: ReflectionOutcomeEvaluation) -> None:
        model = await self._session.get(ReflectionOutcomeEvaluationModel, entity.id)
        if model is None:
            return
        model.evaluation_status = entity.evaluation_status
        model.observed_attempt_count = entity.observed_attempt_count
        model.outcome_snapshot = entity.outcome_snapshot
        model.improvement_score = entity.improvement_score
        model.evaluation_note = entity.evaluation_note
        model.evaluated_at = entity.evaluated_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ReflectionOutcomeEvaluationModel) -> ReflectionOutcomeEvaluation:
        return ReflectionOutcomeEvaluation(
            id=model.id,
            reflection_record_id=model.reflection_record_id,
            learner_goal_id=model.learner_goal_id,
            topic_key=model.topic_key,
            evaluation_status=model.evaluation_status,
            window_size=model.window_size,
            observed_attempt_count=model.observed_attempt_count,
            baseline_snapshot=dict(model.baseline_snapshot or {}),
            outcome_snapshot=dict(model.outcome_snapshot or {}),
            improvement_score=model.improvement_score,
            evaluation_note=model.evaluation_note,
            evaluated_at=model.evaluated_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ReflectionReviewDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionReviewDecision) -> None:
        self._session.add(
            ReflectionReviewDecisionModel(
                id=entity.id,
                reflection_record_id=entity.reflection_record_id,
                decision_type=entity.decision_type,
                previous_status=entity.previous_status,
                new_status=entity.new_status,
                previous_root_cause=entity.previous_root_cause,
                new_root_cause=entity.new_root_cause,
                previous_action_payload=entity.previous_action_payload,
                new_action_payload=entity.new_action_payload,
                reason_code=entity.reason_code,
                reason_note=entity.reason_note,
                operator_id=entity.operator_id,
                created_at=entity.created_at,
            )
        )
        await self._session.flush()

    async def list_by_reflection(self, reflection_record_id: str) -> list[ReflectionReviewDecision]:
        result = await self._session.execute(
            select(ReflectionReviewDecisionModel)
            .where(ReflectionReviewDecisionModel.reflection_record_id == reflection_record_id)
            .order_by(desc(ReflectionReviewDecisionModel.created_at), desc(ReflectionReviewDecisionModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: ReflectionReviewDecisionModel) -> ReflectionReviewDecision:
        return ReflectionReviewDecision(
            id=model.id,
            reflection_record_id=model.reflection_record_id,
            decision_type=model.decision_type,
            previous_status=model.previous_status,
            new_status=model.new_status,
            previous_root_cause=model.previous_root_cause,
            new_root_cause=model.new_root_cause,
            previous_action_payload=dict(model.previous_action_payload) if model.previous_action_payload is not None else None,
            new_action_payload=dict(model.new_action_payload) if model.new_action_payload is not None else None,
            reason_code=model.reason_code,
            reason_note=model.reason_note,
            operator_id=model.operator_id,
            created_at=model.created_at,
        )



class LearnerGoalStrategyCardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: LearnerGoalStrategyCard) -> None:
        self._session.add(LearnerGoalStrategyCardModel(**entity.__dict__))
        await self._session.flush()

    async def get_active_by_goal(self, learner_goal_id: str) -> LearnerGoalStrategyCard | None:
        result = await self._session.execute(
            select(LearnerGoalStrategyCardModel)
            .where(
                LearnerGoalStrategyCardModel.learner_goal_id == learner_goal_id,
                LearnerGoalStrategyCardModel.status == "active",
            )
            .order_by(desc(LearnerGoalStrategyCardModel.version))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_goal(self, learner_goal_id: str) -> list[LearnerGoalStrategyCard]:
        result = await self._session.execute(
            select(LearnerGoalStrategyCardModel)
            .where(LearnerGoalStrategyCardModel.learner_goal_id == learner_goal_id)
            .order_by(desc(LearnerGoalStrategyCardModel.version))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, entity: LearnerGoalStrategyCard) -> None:
        model = await self._session.get(LearnerGoalStrategyCardModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.source_reflection_ids = entity.source_reflection_ids
        model.primary_instruction_mode = entity.primary_instruction_mode
        model.difficulty_bias = entity.difficulty_bias
        model.review_bias = entity.review_bias
        model.replan_bias = entity.replan_bias
        model.assessment_bias = entity.assessment_bias
        model.intervention_policy = entity.intervention_policy
        model.rationale = entity.rationale
        model.confidence_score = entity.confidence_score
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: LearnerGoalStrategyCardModel) -> LearnerGoalStrategyCard:
        return LearnerGoalStrategyCard(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            version=model.version,
            status=model.status,
            source_reflection_ids=list(model.source_reflection_ids or []),
            primary_instruction_mode=model.primary_instruction_mode,
            difficulty_bias=model.difficulty_bias,
            review_bias=model.review_bias,
            replan_bias=model.replan_bias,
            assessment_bias=model.assessment_bias,
            intervention_policy=dict(model.intervention_policy or {}),
            rationale=model.rationale,
            confidence_score=model.confidence_score,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ReflectiveMemoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectiveMemory) -> None:
        self._session.add(ReflectiveMemoryModel(**entity.__dict__))
        await self._session.flush()

    async def list_by_goal(self, learner_goal_id: str, *, statuses: set[str] | None = None) -> list[ReflectiveMemory]:
        query = select(ReflectiveMemoryModel).where(ReflectiveMemoryModel.learner_goal_id == learner_goal_id)
        if statuses:
            query = query.where(ReflectiveMemoryModel.status.in_(sorted(statuses)))
        query = query.order_by(desc(ReflectiveMemoryModel.updated_at), desc(ReflectiveMemoryModel.id))
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, entity: ReflectiveMemory) -> None:
        model = await self._session.get(ReflectiveMemoryModel, entity.id)
        if model is None:
            return
        model.importance_score = entity.importance_score
        model.confidence_score = entity.confidence_score
        model.freshness_score = entity.freshness_score
        model.evidence_count = entity.evidence_count
        model.status = entity.status
        model.summary = entity.summary
        model.details = entity.details
        model.tags = entity.tags
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ReflectiveMemoryModel) -> ReflectiveMemory:
        return ReflectiveMemory(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            reflection_record_id=model.reflection_record_id,
            memory_key=model.memory_key,
            title=model.title,
            summary=model.summary,
            details=model.details,
            memory_level=model.memory_level,
            importance_score=model.importance_score,
            confidence_score=model.confidence_score,
            freshness_score=model.freshness_score,
            evidence_count=model.evidence_count,
            status=model.status,
            source_reflection_ids=list(model.source_reflection_ids or []),
            source_action_ids=list(model.source_action_ids or []),
            tags=list(model.tags or []),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ReflectionProposalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    _AUTO_STAGE_COMPLETED_ARTIFACT_STATUSES = (
        "staged",
        "active",
        "stable",
        "deprecated",
        "archived",
        "suppressed",
    )

    async def create(self, entity: ReflectionProposal) -> None:
        self._session.add(ReflectionProposalModel(**entity.__dict__))
        await self._session.flush()

    async def get_by_id(self, proposal_id: str) -> ReflectionProposal | None:
        model = await self._session.get(ReflectionProposalModel, proposal_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_reflection(self, reflection_record_id: str) -> list[ReflectionProposal]:
        result = await self._session.execute(
            select(ReflectionProposalModel)
            .where(ReflectionProposalModel.reflection_record_id == reflection_record_id)
            .order_by(desc(ReflectionProposalModel.created_at), desc(ReflectionProposalModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_queue(
        self,
        *,
        statuses: set[str] | None = None,
        learner_goal_id: str | None = None,
        proposal_type: str | None = None,
        target_scope: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[ReflectionProposal]:
        query = select(ReflectionProposalModel)
        if statuses:
            query = query.where(ReflectionProposalModel.status.in_(sorted(statuses)))
        else:
            query = query.where(ReflectionProposalModel.status.in_(["proposed", "sandbox_queued", "sandbox_running", "sandbox_completed"]))
        if learner_goal_id is not None:
            query = query.where(ReflectionProposalModel.learner_goal_id == learner_goal_id)
        if proposal_type is not None:
            query = query.where(ReflectionProposalModel.proposal_type == proposal_type)
        if target_scope is not None:
            query = query.where(ReflectionProposalModel.target_scope == target_scope)
        query = query.order_by(
            desc(ReflectionProposalModel.priority_score),
            desc(ReflectionProposalModel.created_at),
            desc(ReflectionProposalModel.id),
        ).limit(limit).offset(offset)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_pending_skill_patch_realizations(self, *, limit: int = 20) -> list[ReflectionProposal]:
        """List approved patch requests that have not produced a governed package yet.

        Args:
            limit: Maximum number of proposals to return.

        Returns:
            A bounded list of patch-request proposals ready for realization.
        """
        source = ReflectionProposalModel
        derived = aliased(ReflectionProposalModel)
        query = (
            select(source)
            .where(
                source.proposal_type == "skill_patch_request",
                source.status == "approved",
                source.evaluation_status == "effective",
                ~select(derived.id)
                .where(
                    derived.proposal_type == "skill_package",
                    derived.evidence_snapshot["source_skill_patch_request_id"].as_string() == source.id,
                )
                .exists(),
            )
            .order_by(
                desc(source.priority_score),
                desc(source.created_at),
                desc(source.id),
            )
            .limit(bounded_limit(limit))
        )
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_pending_skill_package_sandbox(self, *, limit: int = 20) -> list[ReflectionProposal]:
        """List proposed skill-package proposals awaiting sandbox admission review.

        Args:
            limit: Maximum number of proposals to return.

        Returns:
            A bounded list of proposed skill-package proposals.
        """
        query = (
            select(ReflectionProposalModel)
            .where(
                ReflectionProposalModel.proposal_type == "skill_package",
                ReflectionProposalModel.status == "proposed",
            )
            .order_by(
                desc(ReflectionProposalModel.priority_score),
                desc(ReflectionProposalModel.created_at),
                desc(ReflectionProposalModel.id),
            )
            .limit(bounded_limit(limit))
        )
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_pending_skill_package_auto_stage(self, *, limit: int = 20) -> list[ReflectionProposal]:
        """List skill-package proposals awaiting bounded auto-staging review.

        Args:
            limit: Maximum number of proposals to return.

        Returns:
            A bounded list of sandbox-completed or approved proposals that do not
            already own a staged-or-beyond artifact.
        """
        proposal = ReflectionProposalModel
        artifact = aliased(SkillArtifactModel)
        query = (
            select(proposal)
            .where(
                proposal.proposal_type == "skill_package",
                proposal.status.in_(("sandbox_completed", "approved")),
                ~select(artifact.id)
                .where(
                    artifact.source_proposal_id == proposal.id,
                    artifact.status.in_(self._AUTO_STAGE_COMPLETED_ARTIFACT_STATUSES),
                )
                .exists(),
            )
            .order_by(
                desc(proposal.priority_score),
                desc(proposal.updated_at),
                desc(proposal.id),
            )
            .limit(bounded_limit(limit))
        )
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def count_queue(
        self,
        *,
        statuses: set[str] | None = None,
        learner_goal_id: str | None = None,
        proposal_type: str | None = None,
        target_scope: str | None = None,
    ) -> int:
        query = select(func.count()).select_from(ReflectionProposalModel)
        if statuses:
            query = query.where(ReflectionProposalModel.status.in_(sorted(statuses)))
        else:
            query = query.where(ReflectionProposalModel.status.in_(["proposed", "sandbox_queued", "sandbox_running", "sandbox_completed"]))
        if learner_goal_id is not None:
            query = query.where(ReflectionProposalModel.learner_goal_id == learner_goal_id)
        if proposal_type is not None:
            query = query.where(ReflectionProposalModel.proposal_type == proposal_type)
        if target_scope is not None:
            query = query.where(ReflectionProposalModel.target_scope == target_scope)
        result = await self._session.execute(query)
        return int(result.scalar_one())

    async def update(self, entity: ReflectionProposal) -> None:
        model = await self._session.get(ReflectionProposalModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.priority_score = entity.priority_score
        model.evaluation_status = entity.evaluation_status
        model.evaluation_summary = entity.evaluation_summary
        model.latest_sandbox_run_id = entity.latest_sandbox_run_id
        model.approved_at = entity.approved_at
        model.approved_by = entity.approved_by
        model.approval_reason_code = entity.approval_reason_code
        model.approval_note = entity.approval_note
        model.proposal_bundle_id = entity.proposal_bundle_id
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ReflectionProposalModel) -> ReflectionProposal:
        return ReflectionProposal(
            id=model.id,
            reflection_record_id=model.reflection_record_id,
            learner_goal_id=model.learner_goal_id,
            proposal_type=model.proposal_type,
            target_scope=model.target_scope,
            status=model.status,
            priority_score=model.priority_score,
            hypothesis=model.hypothesis,
            change_summary=model.change_summary,
            structured_patch_payload=dict(model.structured_patch_payload or {}),
            expected_improvement=model.expected_improvement,
            risk_level=model.risk_level,
            evidence_snapshot=dict(model.evidence_snapshot or {}),
            evaluation_status=model.evaluation_status,
            evaluation_summary=model.evaluation_summary,
            latest_sandbox_run_id=model.latest_sandbox_run_id,
            approved_at=model.approved_at,
            approved_by=model.approved_by,
            approval_reason_code=model.approval_reason_code,
            approval_note=model.approval_note,
            proposal_bundle_id=model.proposal_bundle_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ReflectionProposalEvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionProposalEvaluation) -> None:
        self._session.add(ReflectionProposalEvaluationModel(**entity.__dict__))
        await self._session.flush()

    async def get_by_proposal(self, proposal_id: str) -> ReflectionProposalEvaluation | None:
        result = await self._session.execute(
            select(ReflectionProposalEvaluationModel).where(
                ReflectionProposalEvaluationModel.proposal_id == proposal_id
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def update(self, entity: ReflectionProposalEvaluation) -> None:
        model = await self._session.get(ReflectionProposalEvaluationModel, entity.id)
        if model is None:
            return
        model.evaluation_status = entity.evaluation_status
        model.simulated_outcome_summary = entity.simulated_outcome_summary
        model.score_delta = entity.score_delta
        model.sandbox_run_id = entity.sandbox_run_id
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ReflectionProposalEvaluationModel) -> ReflectionProposalEvaluation:
        return ReflectionProposalEvaluation(
            id=model.id,
            proposal_id=model.proposal_id,
            evaluation_status=model.evaluation_status,
            comparison_window_size=model.comparison_window_size,
            baseline_policy_snapshot=dict(model.baseline_policy_snapshot or {}),
            candidate_policy_snapshot=dict(model.candidate_policy_snapshot or {}),
            simulated_outcome_summary=dict(model.simulated_outcome_summary or {}),
            score_delta=model.score_delta,
            evaluator_type=model.evaluator_type,
            sandbox_run_id=model.sandbox_run_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ReflectionProposalSandboxRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionProposalSandboxRun) -> None:
        self._session.add(ReflectionProposalSandboxRunModel(**entity.__dict__))
        await self._session.flush()

    async def get_by_id(self, sandbox_run_id: str) -> ReflectionProposalSandboxRun | None:
        model = await self._session.get(ReflectionProposalSandboxRunModel, sandbox_run_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_proposal(self, proposal_id: str) -> list[ReflectionProposalSandboxRun]:
        result = await self._session.execute(
            select(ReflectionProposalSandboxRunModel)
            .where(ReflectionProposalSandboxRunModel.proposal_id == proposal_id)
            .order_by(desc(ReflectionProposalSandboxRunModel.created_at), desc(ReflectionProposalSandboxRunModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, entity: ReflectionProposalSandboxRun) -> None:
        model = await self._session.get(ReflectionProposalSandboxRunModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.sample_count = entity.sample_count
        model.provider = entity.provider
        model.model = entity.model
        model.result_summary = entity.result_summary
        model.score_delta = entity.score_delta
        model.error_code = entity.error_code
        model.started_at = entity.started_at
        model.completed_at = entity.completed_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ReflectionProposalSandboxRunModel) -> ReflectionProposalSandboxRun:
        return ReflectionProposalSandboxRun(
            id=model.id,
            proposal_id=model.proposal_id,
            learner_goal_id=model.learner_goal_id,
            status=model.status,
            sample_source_type=model.sample_source_type,
            sample_count=model.sample_count,
            provider=model.provider,
            model=model.model,
            evaluator_type=model.evaluator_type,
            baseline_snapshot=dict(model.baseline_snapshot or {}),
            candidate_snapshot=dict(model.candidate_snapshot or {}),
            result_summary=dict(model.result_summary or {}),
            score_delta=model.score_delta,
            error_code=model.error_code,
            started_at=model.started_at,
            completed_at=model.completed_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ReflectionProposalApprovalDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionProposalApprovalDecision) -> None:
        self._session.add(ReflectionProposalApprovalDecisionModel(**entity.__dict__))
        await self._session.flush()

    async def list_by_proposal(self, proposal_id: str) -> list[ReflectionProposalApprovalDecision]:
        result = await self._session.execute(
            select(ReflectionProposalApprovalDecisionModel)
            .where(ReflectionProposalApprovalDecisionModel.proposal_id == proposal_id)
            .order_by(desc(ReflectionProposalApprovalDecisionModel.created_at), desc(ReflectionProposalApprovalDecisionModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: ReflectionProposalApprovalDecisionModel) -> ReflectionProposalApprovalDecision:
        return ReflectionProposalApprovalDecision(
            id=model.id,
            proposal_id=model.proposal_id,
            decision_type=model.decision_type,
            previous_status=model.previous_status,
            new_status=model.new_status,
            reason_code=model.reason_code,
            reason_note=model.reason_note,
            operator_id=model.operator_id,
            created_at=model.created_at,
        )



class ReflectionProposalRolloutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionProposalRollout) -> None:
        self._session.add(ReflectionProposalRolloutModel(**entity.__dict__))
        await self._session.flush()

    async def get_by_id(self, rollout_id: str) -> ReflectionProposalRollout | None:
        model = await self._session.get(ReflectionProposalRolloutModel, rollout_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_proposal(self, proposal_id: str) -> ReflectionProposalRollout | None:
        result = await self._session.execute(
            select(ReflectionProposalRolloutModel).where(
                ReflectionProposalRolloutModel.proposal_id == proposal_id
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ) -> ReflectionProposalRollout | None:
        statuses = ["staged", "rolled_out"] if include_staged else ["rolled_out"]
        result = await self._session.execute(
            select(ReflectionProposalRolloutModel)
            .where(
                ReflectionProposalRolloutModel.learner_goal_id == learner_goal_id,
                ReflectionProposalRolloutModel.surface == surface,
                ReflectionProposalRolloutModel.status.in_(statuses),
            )
            .order_by(desc(ReflectionProposalRolloutModel.created_at), desc(ReflectionProposalRolloutModel.id))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_proposal(self, proposal_id: str) -> list[ReflectionProposalRollout]:
        result = await self._session.execute(
            select(ReflectionProposalRolloutModel)
            .where(ReflectionProposalRolloutModel.proposal_id == proposal_id)
            .order_by(desc(ReflectionProposalRolloutModel.created_at), desc(ReflectionProposalRolloutModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_proposal_and_statuses(
        self,
        proposal_id: str,
        *,
        statuses: list[str],
    ) -> list[ReflectionProposalRollout]:
        result = await self._session.execute(
            select(ReflectionProposalRolloutModel)
            .where(
                ReflectionProposalRolloutModel.proposal_id == proposal_id,
                ReflectionProposalRolloutModel.status.in_(statuses),
            )
            .order_by(desc(ReflectionProposalRolloutModel.created_at), desc(ReflectionProposalRolloutModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, entity: ReflectionProposalRollout) -> None:
        model = await self._session.get(ReflectionProposalRolloutModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.baseline_snapshot = entity.baseline_snapshot
        model.runtime_overlay_payload = entity.runtime_overlay_payload
        model.latest_observation_id = entity.latest_observation_id
        model.staged_plan_id = entity.staged_plan_id
        model.rollback_restored_plan_id = entity.rollback_restored_plan_id
        model.promoted_at = entity.promoted_at
        model.rolled_back_at = entity.rolled_back_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ReflectionProposalRolloutModel) -> ReflectionProposalRollout:
        return ReflectionProposalRollout(
            id=model.id,
            proposal_id=model.proposal_id,
            learner_goal_id=model.learner_goal_id,
            surface=model.surface,
            status=model.status,
            baseline_snapshot=dict(model.baseline_snapshot or {}),
            runtime_overlay_payload=dict(model.runtime_overlay_payload or {}),
            latest_observation_id=model.latest_observation_id,
            staged_plan_id=model.staged_plan_id,
            rollback_restored_plan_id=model.rollback_restored_plan_id,
            activated_by=model.activated_by,
            activated_at=model.activated_at,
            promoted_at=model.promoted_at,
            rolled_back_at=model.rolled_back_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ReflectionProposalRolloutObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionProposalRolloutObservation) -> None:
        self._session.add(ReflectionProposalRolloutObservationModel(**entity.__dict__))
        await self._session.flush()

    async def get_by_id(self, observation_id: str) -> ReflectionProposalRolloutObservation | None:
        model = await self._session.get(ReflectionProposalRolloutObservationModel, observation_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_rollout(self, rollout_id: str) -> list[ReflectionProposalRolloutObservation]:
        result = await self._session.execute(
            select(ReflectionProposalRolloutObservationModel)
            .where(ReflectionProposalRolloutObservationModel.rollout_id == rollout_id)
            .order_by(desc(ReflectionProposalRolloutObservationModel.created_at), desc(ReflectionProposalRolloutObservationModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: ReflectionProposalRolloutObservationModel) -> ReflectionProposalRolloutObservation:
        return ReflectionProposalRolloutObservation(
            id=model.id,
            rollout_id=model.rollout_id,
            proposal_id=model.proposal_id,
            learner_goal_id=model.learner_goal_id,
            surface=model.surface,
            recommendation=model.recommendation,
            observed_sample_count=model.observed_sample_count,
            positive_score=model.positive_score,
            negative_score=model.negative_score,
            signal_summary=dict(model.signal_summary or {}),
            reason_codes=list(model.reason_codes or []),
            created_at=model.created_at,
        )



class ReflectionProposalRolloutDecisionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ReflectionProposalRolloutDecision) -> None:
        self._session.add(ReflectionProposalRolloutDecisionModel(**entity.__dict__))
        await self._session.flush()

    async def list_by_rollout(self, rollout_id: str) -> list[ReflectionProposalRolloutDecision]:
        result = await self._session.execute(
            select(ReflectionProposalRolloutDecisionModel)
            .where(ReflectionProposalRolloutDecisionModel.rollout_id == rollout_id)
            .order_by(desc(ReflectionProposalRolloutDecisionModel.created_at), desc(ReflectionProposalRolloutDecisionModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: ReflectionProposalRolloutDecisionModel) -> ReflectionProposalRolloutDecision:
        return ReflectionProposalRolloutDecision(
            id=model.id,
            rollout_id=model.rollout_id,
            proposal_id=model.proposal_id,
            decision_type=model.decision_type,
            previous_status=model.previous_status,
            new_status=model.new_status,
            reason_code=model.reason_code,
            reason_note=model.reason_note,
            operator_id=model.operator_id,
            created_at=model.created_at,
        )



class GoalSkillBindingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: GoalSkillBinding) -> None:
        self._session.add(GoalSkillBindingModel(**entity.__dict__))
        await self._session.flush()

    async def get_by_id(self, binding_id: str) -> GoalSkillBinding | None:
        model = await self._session.get(GoalSkillBindingModel, binding_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_rollout(self, rollout_id: str) -> GoalSkillBinding | None:
        result = await self._session.execute(
            select(GoalSkillBindingModel).where(GoalSkillBindingModel.rollout_id == rollout_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ) -> GoalSkillBinding | None:
        bindings = await self.list_active_by_goal_and_surface(
            learner_goal_id,
            surface,
            include_staged=include_staged,
        )
        return bindings[0] if bindings else None

    async def list_active_by_goal_and_surface(
        self,
        learner_goal_id: str,
        surface: str,
        *,
        include_staged: bool = True,
    ) -> list[GoalSkillBinding]:
        statuses = ["staged", "rolled_out"] if include_staged else ["rolled_out"]
        result = await self._session.execute(
            select(GoalSkillBindingModel)
            .where(
                GoalSkillBindingModel.learner_goal_id == learner_goal_id,
                GoalSkillBindingModel.surface == surface,
                GoalSkillBindingModel.status.in_(statuses),
            )
            .order_by(desc(GoalSkillBindingModel.priority_score), desc(GoalSkillBindingModel.updated_at))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_goal(self, learner_goal_id: str) -> list[GoalSkillBinding]:
        result = await self._session.execute(
            select(GoalSkillBindingModel)
            .where(GoalSkillBindingModel.learner_goal_id == learner_goal_id)
            .order_by(desc(GoalSkillBindingModel.updated_at), desc(GoalSkillBindingModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_proposal_and_statuses(
        self,
        proposal_id: str,
        *,
        statuses: list[str],
    ) -> list[GoalSkillBinding]:
        result = await self._session.execute(
            select(GoalSkillBindingModel)
            .where(
                GoalSkillBindingModel.proposal_id == proposal_id,
                GoalSkillBindingModel.status.in_(statuses),
            )
            .order_by(desc(GoalSkillBindingModel.updated_at), desc(GoalSkillBindingModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, entity: GoalSkillBinding) -> None:
        model = await self._session.get(GoalSkillBindingModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.priority_score = entity.priority_score
        model.match_rules = entity.match_rules
        model.runtime_directives = entity.runtime_directives
        model.tool_plan = entity.tool_plan
        model.updated_at = entity.updated_at
        model.activated_at = entity.activated_at
        model.rolled_back_at = entity.rolled_back_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: GoalSkillBindingModel) -> GoalSkillBinding:
        return GoalSkillBinding(
            id=model.id,
            proposal_id=model.proposal_id,
            rollout_id=model.rollout_id,
            learner_goal_id=model.learner_goal_id,
            surface=model.surface,
            status=model.status,
            priority_score=model.priority_score,
            match_rules=dict(model.match_rules or {}),
            runtime_directives=dict(model.runtime_directives or {}),
            tool_plan=[dict(item) for item in (model.tool_plan or [])],
            created_at=model.created_at,
            updated_at=model.updated_at,
            activated_at=model.activated_at,
            rolled_back_at=model.rolled_back_at,
        )
