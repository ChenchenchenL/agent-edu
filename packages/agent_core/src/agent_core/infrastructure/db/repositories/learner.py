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


class LearnerProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: LearnerProfile) -> None:
        model = LearnerProfileModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def list_profiles(self) -> list[LearnerProfile]:
        result = await self._session.execute(
            select(LearnerProfileModel).order_by(desc(LearnerProfileModel.created_at), desc(LearnerProfileModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_id(self, profile_id: str) -> LearnerProfile | None:
        model = await self._session.get(LearnerProfileModel, profile_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_access_key_hash(self, access_key_hash: str) -> LearnerProfile | None:
        result = await self._session.execute(
            select(LearnerProfileModel).where(LearnerProfileModel.access_key_hash == access_key_hash)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def update(self, entity: LearnerProfile) -> None:
        model = await self._session.get(LearnerProfileModel, entity.id)
        if model is None:
            return
        model.access_key_hash = entity.access_key_hash
        model.access_key_created_at = entity.access_key_created_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: LearnerProfileModel) -> LearnerProfile:
        return LearnerProfile(
            id=model.id,
            created_at=model.created_at,
            updated_at=model.updated_at,
            access_key_hash=model.access_key_hash,
            access_key_created_at=model.access_key_created_at,
        )



class LearnerGoalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: LearnerGoal) -> None:
        model = LearnerGoalModel(
            id=entity.id,
            learner_profile_id=entity.learner_profile_id,
            title=entity.title,
            subject=entity.subject,
            target_outcome=entity.target_outcome,
            baseline_note=entity.baseline_note,
            deadline_date=entity.deadline_date,
            weekly_study_minutes=entity.weekly_study_minutes,
            status=entity.status,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
        self._session.add(model)
        await self._session.flush()

    async def list_by_profile(self, learner_profile_id: str) -> list[LearnerGoal]:
        result = await self._session.execute(
            select(LearnerGoalModel)
            .where(LearnerGoalModel.learner_profile_id == learner_profile_id)
            .order_by(desc(LearnerGoalModel.created_at), desc(LearnerGoalModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_id(self, goal_id: str) -> LearnerGoal | None:
        model = await self._session.get(LearnerGoalModel, goal_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def update(self, entity: LearnerGoal) -> None:
        model = await self._session.get(LearnerGoalModel, entity.id)
        if model is None:
            return
        model.title = entity.title
        model.subject = entity.subject
        model.target_outcome = entity.target_outcome
        model.baseline_note = entity.baseline_note
        model.deadline_date = entity.deadline_date
        model.weekly_study_minutes = entity.weekly_study_minutes
        model.status = entity.status
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: LearnerGoalModel) -> LearnerGoal:
        return LearnerGoal(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            title=model.title,
            subject=model.subject,
            target_outcome=model.target_outcome,
            baseline_note=model.baseline_note,
            deadline_date=model.deadline_date,
            weekly_study_minutes=model.weekly_study_minutes,
            status=model.status,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class GoalAutonomyStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: GoalAutonomyState) -> None:
        self._session.add(
            GoalAutonomyStateModel(
                id=entity.id,
                learner_goal_id=entity.learner_goal_id,
                phase=entity.phase,
                current_plan_id=entity.current_plan_id,
                next_due_at=entity.next_due_at,
                availability_snapshot=entity.availability_snapshot,
                mastery_snapshot=entity.mastery_snapshot,
                last_transition_reason=entity.last_transition_reason,
                last_transition_at=entity.last_transition_at,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
        )
        await self._session.flush()

    async def get_by_goal(self, learner_goal_id: str) -> GoalAutonomyState | None:
        result = await self._session.execute(
            select(GoalAutonomyStateModel).where(GoalAutonomyStateModel.learner_goal_id == learner_goal_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def update(self, entity: GoalAutonomyState) -> None:
        model = await self._session.get(GoalAutonomyStateModel, entity.id)
        if model is None:
            return
        model.phase = entity.phase
        model.current_plan_id = entity.current_plan_id
        model.next_due_at = entity.next_due_at
        model.availability_snapshot = entity.availability_snapshot
        model.mastery_snapshot = entity.mastery_snapshot
        model.last_transition_reason = entity.last_transition_reason
        model.last_transition_at = entity.last_transition_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: GoalAutonomyStateModel) -> GoalAutonomyState:
        return GoalAutonomyState(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            phase=model.phase,
            current_plan_id=model.current_plan_id,
            next_due_at=model.next_due_at,
            availability_snapshot=dict(model.availability_snapshot or {}),
            mastery_snapshot=dict(model.mastery_snapshot or {}),
            last_transition_reason=model.last_transition_reason,
            last_transition_at=model.last_transition_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class ScheduledAutonomyJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: ScheduledAutonomyJob) -> ScheduledAutonomyJob:
        existing = await self.get_by_idempotency_key(entity.idempotency_key)
        if existing is not None:
            return existing
        self._session.add(
            ScheduledAutonomyJobModel(
                id=entity.id,
                learner_goal_id=entity.learner_goal_id,
                job_type=entity.job_type,
                status=entity.status,
                trigger_source=entity.trigger_source,
                due_at=entity.due_at,
                lease_owner=entity.lease_owner,
                lease_expires_at=entity.lease_expires_at,
                attempt_count=entity.attempt_count,
                max_attempts=entity.max_attempts,
                idempotency_key=entity.idempotency_key,
                payload=entity.payload,
                workflow_run_id=entity.workflow_run_id,
                error_code=entity.error_code,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
        )
        await self._session.flush()
        return entity

    async def get_by_idempotency_key(self, idempotency_key: str) -> ScheduledAutonomyJob | None:
        result = await self._session.execute(
            select(ScheduledAutonomyJobModel).where(ScheduledAutonomyJobModel.idempotency_key == idempotency_key)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_id(self, job_id: str) -> ScheduledAutonomyJob | None:
        model = await self._session.get(ScheduledAutonomyJobModel, job_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_goal(self, learner_goal_id: str) -> list[ScheduledAutonomyJob]:
        result = await self._session.execute(
            select(ScheduledAutonomyJobModel)
            .where(ScheduledAutonomyJobModel.learner_goal_id == learner_goal_id)
            .order_by(desc(ScheduledAutonomyJobModel.created_at), desc(ScheduledAutonomyJobModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_active_by_goal(self, learner_goal_id: str, *, job_types: set[str] | None = None) -> list[ScheduledAutonomyJob]:
        query = select(ScheduledAutonomyJobModel).where(
            ScheduledAutonomyJobModel.learner_goal_id == learner_goal_id,
            ScheduledAutonomyJobModel.status.in_(["scheduled", "claimed"]),
        )
        if job_types is not None:
            query = query.where(ScheduledAutonomyJobModel.job_type.in_(sorted(job_types)))
        query = query.order_by(ScheduledAutonomyJobModel.due_at.asc(), ScheduledAutonomyJobModel.created_at.asc())
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_due(self, *, now: datetime, limit: int) -> list[ScheduledAutonomyJob]:
        result = await self._session.execute(
            select(ScheduledAutonomyJobModel)
            .where(
                or_(
                    and_(
                        ScheduledAutonomyJobModel.status == "scheduled",
                        ScheduledAutonomyJobModel.due_at <= now,
                    ),
                    and_(
                        ScheduledAutonomyJobModel.status == "claimed",
                        ScheduledAutonomyJobModel.lease_expires_at.is_not(None),
                        ScheduledAutonomyJobModel.lease_expires_at <= now,
                    ),
                )
            )
            .order_by(ScheduledAutonomyJobModel.due_at.asc(), ScheduledAutonomyJobModel.created_at.asc())
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def claim(self, entity: ScheduledAutonomyJob, *, lease_owner: str, lease_seconds: int) -> ScheduledAutonomyJob:
        model = await self._session.get(ScheduledAutonomyJobModel, entity.id)
        if model is None:
            raise ValidationError("Scheduled autonomy job cannot be claimed.")
        claimed = entity.claim(lease_owner=lease_owner, lease_seconds=lease_seconds)
        model.status = claimed.status
        model.lease_owner = claimed.lease_owner
        model.lease_expires_at = claimed.lease_expires_at
        model.attempt_count = claimed.attempt_count
        model.updated_at = claimed.updated_at
        await self._session.flush()
        return claimed

    async def update(self, entity: ScheduledAutonomyJob) -> None:
        model = await self._session.get(ScheduledAutonomyJobModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.lease_owner = entity.lease_owner
        model.lease_expires_at = entity.lease_expires_at
        model.attempt_count = entity.attempt_count
        model.max_attempts = entity.max_attempts
        model.payload = entity.payload
        model.workflow_run_id = entity.workflow_run_id
        model.error_code = entity.error_code
        model.due_at = entity.due_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: ScheduledAutonomyJobModel) -> ScheduledAutonomyJob:
        return ScheduledAutonomyJob(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            job_type=model.job_type,
            status=model.status,
            trigger_source=model.trigger_source,
            due_at=model.due_at,
            lease_owner=model.lease_owner,
            lease_expires_at=model.lease_expires_at,
            attempt_count=model.attempt_count,
            max_attempts=model.max_attempts,
            idempotency_key=model.idempotency_key,
            payload=dict(model.payload or {}),
            workflow_run_id=model.workflow_run_id,
            error_code=model.error_code,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class LearnerAvailabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, entity: LearnerAvailability) -> None:
        result = await self._session.execute(
            select(LearnerAvailabilityModel).where(LearnerAvailabilityModel.learner_goal_id == entity.learner_goal_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            self._session.add(
                LearnerAvailabilityModel(
                    id=entity.id,
                    learner_goal_id=entity.learner_goal_id,
                    timezone=entity.timezone,
                    available_days=entity.available_days,
                    time_windows=entity.time_windows,
                    max_daily_minutes=entity.max_daily_minutes,
                    preferred_session_length_minutes=entity.preferred_session_length_minutes,
                    created_at=entity.created_at,
                    updated_at=entity.updated_at,
                )
            )
        else:
            model.timezone = entity.timezone
            model.available_days = entity.available_days
            model.time_windows = entity.time_windows
            model.max_daily_minutes = entity.max_daily_minutes
            model.preferred_session_length_minutes = entity.preferred_session_length_minutes
            model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_goal(self, learner_goal_id: str) -> LearnerAvailability | None:
        result = await self._session.execute(
            select(LearnerAvailabilityModel).where(LearnerAvailabilityModel.learner_goal_id == learner_goal_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return LearnerAvailability(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            timezone=model.timezone,
            available_days=list(model.available_days or []),
            time_windows=[dict(item) for item in model.time_windows or []],
            max_daily_minutes=model.max_daily_minutes,
            preferred_session_length_minutes=model.preferred_session_length_minutes,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class LearnerTopicMasteryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, entity: LearnerTopicMastery) -> None:
        result = await self._session.execute(
            select(LearnerTopicMasteryModel).where(
                LearnerTopicMasteryModel.learner_goal_id == entity.learner_goal_id,
                LearnerTopicMasteryModel.topic_key == entity.topic_key,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            self._session.add(
                LearnerTopicMasteryModel(
                    id=entity.id,
                    learner_goal_id=entity.learner_goal_id,
                    topic_key=entity.topic_key,
                    mastery_score=entity.mastery_score,
                    confidence=entity.confidence,
                    evidence_count=entity.evidence_count,
                    last_attempt_status=entity.last_attempt_status,
                    last_assessed_at=entity.last_assessed_at,
                    created_at=entity.created_at,
                    updated_at=entity.updated_at,
                )
            )
        else:
            model.mastery_score = entity.mastery_score
            model.confidence = entity.confidence
            model.evidence_count = entity.evidence_count
            model.last_attempt_status = entity.last_attempt_status
            model.last_assessed_at = entity.last_assessed_at
            model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_goal_and_topic(self, learner_goal_id: str, topic_key: str) -> LearnerTopicMastery | None:
        result = await self._session.execute(
            select(LearnerTopicMasteryModel).where(
                LearnerTopicMasteryModel.learner_goal_id == learner_goal_id,
                LearnerTopicMasteryModel.topic_key == topic_key,
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_goal(self, learner_goal_id: str) -> list[LearnerTopicMastery]:
        result = await self._session.execute(
            select(LearnerTopicMasteryModel)
            .where(LearnerTopicMasteryModel.learner_goal_id == learner_goal_id)
            .order_by(desc(LearnerTopicMasteryModel.mastery_score), desc(LearnerTopicMasteryModel.updated_at))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: LearnerTopicMasteryModel) -> LearnerTopicMastery:
        return LearnerTopicMastery(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            topic_key=model.topic_key,
            mastery_score=model.mastery_score,
            confidence=model.confidence,
            evidence_count=model.evidence_count,
            last_attempt_status=model.last_attempt_status,
            last_assessed_at=model.last_assessed_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class TaskAttemptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: TaskAttempt) -> None:
        self._session.add(
            TaskAttemptModel(
                id=entity.id,
                learner_goal_id=entity.learner_goal_id,
                daily_task_id=entity.daily_task_id,
                workflow_run_id=entity.workflow_run_id,
                execution_session_id=entity.execution_session_id,
                task_type=entity.task_type,
                topic_focus=entity.topic_focus,
                outcome_status=entity.outcome_status,
                score=entity.score,
                result_note=entity.result_note,
                created_at=entity.created_at,
            )
        )
        await self._session.flush()

    async def get_by_id(self, attempt_id: str) -> TaskAttempt | None:
        model = await self._session.get(TaskAttemptModel, attempt_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_recent_by_goal(self, learner_goal_id: str, *, limit: int = 20) -> list[TaskAttempt]:
        result = await self._session.execute(
            select(TaskAttemptModel)
            .where(TaskAttemptModel.learner_goal_id == learner_goal_id)
            .order_by(desc(TaskAttemptModel.created_at), desc(TaskAttemptModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: TaskAttemptModel) -> TaskAttempt:
        return TaskAttempt(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            daily_task_id=model.daily_task_id,
            workflow_run_id=model.workflow_run_id,
            execution_session_id=model.execution_session_id,
            task_type=model.task_type,
            topic_focus=model.topic_focus,
            outcome_status=model.outcome_status,
            score=model.score,
            result_note=model.result_note,
            created_at=model.created_at,
        )


