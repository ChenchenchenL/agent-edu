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


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: AuditEvent) -> None:
        model = AuditEventModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def list_recent(
        self,
        *,
        event_type: str | None = None,
        resource_type: str | None = None,
        limit: int = 50,
    ) -> list[AuditEvent]:
        stmt = select(AuditEventModel).order_by(desc(AuditEventModel.created_at))
        if event_type:
            stmt = stmt.where(AuditEventModel.event_type == event_type)
        if resource_type:
            stmt = stmt.where(AuditEventModel.resource_type == resource_type)
        stmt = stmt.limit(limit)
        result = await self._session.execute(stmt)
        return [
            AuditEvent(
                id=row.id,
                event_type=row.event_type,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                actor=row.actor,
                event_data=row.event_data,
                created_at=row.created_at,
            )
            for row in result.scalars().all()
        ]

    async def list_quiz_adaptive_policy_trail(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditEvent]:
        bounded = max(1, min(limit, 1000))
        stmt = (
            select(AuditEventModel)
            .where(
                (AuditEventModel.event_type.like("quiz.adaptive_policy%"))
                | (AuditEventModel.event_type == "quiz.generated")
            )
            .order_by(desc(AuditEventModel.created_at))
            .limit(bounded)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return [
            AuditEvent(
                id=row.id,
                event_type=row.event_type,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                actor=row.actor,
                event_data=row.event_data,
                created_at=row.created_at,
            )
            for row in result.scalars().all()
        ]

    async def get_by_resource(
        self,
        *,
        resource_id: str,
        event_type: str | None = None,
    ) -> AuditEvent | None:
        stmt = select(AuditEventModel).where(
            AuditEventModel.resource_id == resource_id
        )
        if event_type:
            stmt = stmt.where(AuditEventModel.event_type == event_type)
        stmt = stmt.order_by(desc(AuditEventModel.created_at)).limit(1)
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        if row is None:
            return None
        return AuditEvent(
            id=row.id,
            event_type=row.event_type,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            actor=row.actor,
            event_data=row.event_data,
            created_at=row.created_at,
        )


