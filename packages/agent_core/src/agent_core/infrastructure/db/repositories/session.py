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


class SessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: LearningSession) -> None:
        model = LearningSessionModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def list_sessions(self) -> list[LearningSession]:
        result = await self._session.execute(
            select(LearningSessionModel).order_by(
                desc(LearningSessionModel.last_activity_at),
                desc(LearningSessionModel.created_at),
            )
        )
        models = result.scalars().all()
        return [self._to_entity(model) for model in models]

    async def list_by_goal(self, learner_goal_id: str, *, limit: int | None = None) -> list[LearningSession]:
        query = (
            select(LearningSessionModel)
            .where(LearningSessionModel.learner_goal_id == learner_goal_id)
            .order_by(
                desc(LearningSessionModel.last_activity_at),
                desc(LearningSessionModel.created_at),
            )
        )
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_recent_by_goal(
        self,
        learner_goal_id: str | None,
        *,
        limit: int = 10,
        exclude_id: str | None = None,
    ) -> list[LearningSession]:
        if learner_goal_id is None:
            return []
        query = (
            select(LearningSessionModel)
            .where(LearningSessionModel.learner_goal_id == learner_goal_id)
            .order_by(
                desc(LearningSessionModel.last_activity_at),
                desc(LearningSessionModel.created_at),
            )
            .limit(limit)
        )
        if exclude_id is not None:
            query = query.where(LearningSessionModel.id != exclude_id)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_id(self, session_id: str) -> LearningSession | None:
        result = await self._session.execute(
            select(LearningSessionModel).where(LearningSessionModel.id == session_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return self._to_entity(model)

    async def update(self, entity: LearningSession) -> None:
        model = await self._session.get(LearningSessionModel, entity.id)
        if model is None:
            return

        model.learner_goal_id = entity.learner_goal_id
        model.daily_task_id = entity.daily_task_id
        model.title = entity.title
        model.subject = entity.subject
        model.status = entity.status
        model.message_count = entity.message_count
        model.last_activity_at = entity.last_activity_at
        model.summary = entity.summary
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: LearningSessionModel) -> LearningSession:
        return LearningSession(
            id=model.id,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            daily_task_id=model.daily_task_id,
            title=model.title,
            subject=model.subject,
            status=model.status,
            message_count=model.message_count,
            last_activity_at=model.last_activity_at,
            summary=model.summary,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class SessionMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: SessionMessage) -> None:
        model = SessionMessageModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def get_by_id(self, message_id: str) -> SessionMessage | None:
        model = await self._session.get(SessionMessageModel, message_id)
        if model is None:
            return None
        return SessionMessage(
            id=model.id,
            session_id=model.session_id,
            role=model.role,
            content=model.content,
            content_payload=model.content_payload,
            mode=model.mode,
            skill_trace=list(model.skill_trace or []),
            created_at=model.created_at,
        )

    async def count_by_session(self, session_id: str) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(SessionMessageModel).where(
                SessionMessageModel.session_id == session_id
            )
        )
        return int(result.scalar_one())

    async def list_history(
        self,
        *,
        session_id: str,
        limit: int,
        before_id: str | None,
    ) -> list[SessionMessage]:
        query = select(SessionMessageModel).where(SessionMessageModel.session_id == session_id)

        if before_id is not None:
            cursor = await self._session.get(SessionMessageModel, before_id)
            if cursor is None or cursor.session_id != session_id:
                raise ValidationError("Invalid before_id for the requested session.")

            query = query.where(
                or_(
                    SessionMessageModel.created_at < cursor.created_at,
                    and_(
                        SessionMessageModel.created_at == cursor.created_at,
                        SessionMessageModel.id < cursor.id,
                    ),
                )
            )

        result = await self._session.execute(
            query.order_by(
                desc(SessionMessageModel.created_at),
                desc(SessionMessageModel.id),
            ).limit(limit + 1)
        )
        models = list(result.scalars().all())
        models.reverse()
        return [
            SessionMessage(
                id=model.id,
                session_id=model.session_id,
                role=model.role,
                content=model.content,
                content_payload=model.content_payload,
                mode=model.mode,
                skill_trace=list(model.skill_trace or []),
                created_at=model.created_at,
            )
            for model in models
        ]



class SessionQuizRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_quiz(self, entity: SessionQuiz) -> None:
        model = SessionQuizModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def create_questions(self, entities: list[SessionQuizQuestion]) -> None:
        self._session.add_all([SessionQuizQuestionModel(**entity.__dict__) for entity in entities])
        await self._session.flush()

    async def list_by_session(self, session_id: str) -> list[SessionQuiz]:
        result = await self._session.execute(
            select(SessionQuizModel)
            .where(SessionQuizModel.session_id == session_id)
            .order_by(desc(SessionQuizModel.created_at), desc(SessionQuizModel.id))
        )
        models = result.scalars().all()
        return [self._to_quiz_entity(model) for model in models]

    async def get_quiz_with_questions(self, *, session_id: str, quiz_id: str) -> StoredSessionQuiz:
        quiz_result = await self._session.execute(
            select(SessionQuizModel).where(
                SessionQuizModel.id == quiz_id,
                SessionQuizModel.session_id == session_id,
            )
        )
        quiz_model = quiz_result.scalar_one_or_none()
        if quiz_model is None:
            raise NotFoundError(f"Quiz '{quiz_id}' was not found in session '{session_id}'.")

        questions_result = await self._session.execute(
            select(SessionQuizQuestionModel)
            .where(SessionQuizQuestionModel.quiz_id == quiz_id)
            .order_by(SessionQuizQuestionModel.position.asc(), SessionQuizQuestionModel.id.asc())
        )
        question_models = questions_result.scalars().all()
        return StoredSessionQuiz(
            quiz=self._to_quiz_entity(quiz_model),
            questions=[
                QuizQuestion(prompt=model.prompt, answer=model.answer)
                for model in question_models
            ],
        )

    @staticmethod
    def _to_quiz_entity(model: SessionQuizModel) -> SessionQuiz:
        return SessionQuiz(
            id=model.id,
            session_id=model.session_id,
            topic=model.topic,
            difficulty=model.difficulty,
            question_count=model.question_count,
            skill_trace=list(model.skill_trace or []),
            created_at=model.created_at,
        )


