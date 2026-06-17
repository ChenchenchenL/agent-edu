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


class StudyPlanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: StudyPlan) -> None:
        model = StudyPlanModel(
            id=entity.id,
            learner_goal_id=entity.learner_goal_id,
            version=entity.version,
            status=entity.status,
            trigger_source=entity.trigger_source,
            plan_summary=entity.plan_summary,
            blueprint_payload=entity.blueprint_payload,
            materialized_until_date=entity.materialized_until_date,
            supersedes_plan_id=entity.supersedes_plan_id,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )
        self._session.add(model)
        await self._session.flush()

    async def list_by_goal(self, learner_goal_id: str) -> list[StudyPlan]:
        result = await self._session.execute(
            select(StudyPlanModel)
            .where(StudyPlanModel.learner_goal_id == learner_goal_id)
            .order_by(desc(StudyPlanModel.version), desc(StudyPlanModel.created_at))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def get_by_id(self, plan_id: str) -> StudyPlan | None:
        model = await self._session.get(StudyPlanModel, plan_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_active_by_goal(self, learner_goal_id: str) -> StudyPlan | None:
        result = await self._session.execute(
            select(StudyPlanModel)
            .where(
                StudyPlanModel.learner_goal_id == learner_goal_id,
                StudyPlanModel.status == "active",
            )
            .order_by(desc(StudyPlanModel.version))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def update(self, entity: StudyPlan) -> None:
        model = await self._session.get(StudyPlanModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.plan_summary = entity.plan_summary
        model.blueprint_payload = entity.blueprint_payload
        model.materialized_until_date = entity.materialized_until_date
        model.updated_at = entity.updated_at
        await self._session.flush()

    @staticmethod
    def _to_entity(model: StudyPlanModel) -> StudyPlan:
        return StudyPlan(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            version=model.version,
            status=model.status,
            trigger_source=model.trigger_source,
            plan_summary=model.plan_summary,
            blueprint_payload=dict(model.blueprint_payload or {}),
            materialized_until_date=model.materialized_until_date,
            supersedes_plan_id=model.supersedes_plan_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class PlanStageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, entities: list[PlanStage]) -> None:
        self._session.add_all(
            [
                PlanStageModel(
                    id=item.id,
                    study_plan_id=item.study_plan_id,
                    position=item.position,
                    title=item.title,
                    objective=item.objective,
                    focus_topics=item.focus_topics,
                    start_date=item.start_date,
                    end_date=item.end_date,
                )
                for item in entities
            ]
        )
        await self._session.flush()

    async def list_by_plan(self, study_plan_id: str) -> list[PlanStage]:
        result = await self._session.execute(
            select(PlanStageModel)
            .where(PlanStageModel.study_plan_id == study_plan_id)
            .order_by(PlanStageModel.position.asc(), PlanStageModel.id.asc())
        )
        return [
            PlanStage(
                id=model.id,
                study_plan_id=model.study_plan_id,
                position=model.position,
                title=model.title,
                objective=model.objective,
                focus_topics=list(model.focus_topics or []),
                start_date=model.start_date,
                end_date=model.end_date,
            )
            for model in result.scalars().all()
        ]



class DailyTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, entities: list[DailyTask]) -> None:
        self._session.add_all([self._to_model(item) for item in entities])
        await self._session.flush()

    async def get_by_id(self, task_id: str) -> DailyTask | None:
        model = await self._session.get(DailyTaskModel, task_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_goal(self, learner_goal_id: str) -> list[DailyTask]:
        result = await self._session.execute(
            select(DailyTaskModel)
            .where(DailyTaskModel.learner_goal_id == learner_goal_id)
            .order_by(DailyTaskModel.scheduled_for.asc(), DailyTaskModel.created_at.asc(), DailyTaskModel.id.asc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_filtered(
        self,
        *,
        learner_goal_id: str,
        statuses: set[str] | None = None,
        scheduled_from: datetime | None = None,
        scheduled_to: datetime | None = None,
        task_type: str | None = None,
        limit: int | None = None,
    ) -> list[DailyTask]:
        query = select(DailyTaskModel).where(DailyTaskModel.learner_goal_id == learner_goal_id)
        if statuses is not None:
            query = query.where(DailyTaskModel.status.in_(sorted(statuses)))
        if scheduled_from is not None:
            query = query.where(DailyTaskModel.scheduled_for >= scheduled_from.date())
        if scheduled_to is not None:
            query = query.where(DailyTaskModel.scheduled_for <= scheduled_to.date())
        if task_type is not None:
            query = query.where(DailyTaskModel.task_type == task_type)
        query = query.order_by(DailyTaskModel.scheduled_for.asc(), DailyTaskModel.created_at.asc(), DailyTaskModel.id.asc())
        if limit is not None:
            query = query.limit(limit)
        result = await self._session.execute(query)
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_active_future_by_goal(self, learner_goal_id: str) -> list[DailyTask]:
        result = await self._session.execute(
            select(DailyTaskModel)
            .where(
                DailyTaskModel.learner_goal_id == learner_goal_id,
                DailyTaskModel.status.in_(["pending", "in_progress"]),
            )
            .order_by(DailyTaskModel.scheduled_for.asc(), DailyTaskModel.created_at.asc(), DailyTaskModel.id.asc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_future_by_plan(self, study_plan_id: str) -> list[DailyTask]:
        result = await self._session.execute(
            select(DailyTaskModel)
            .where(
                DailyTaskModel.study_plan_id == study_plan_id,
                DailyTaskModel.status.in_(["pending", "in_progress"]),
            )
            .order_by(DailyTaskModel.scheduled_for.asc(), DailyTaskModel.id.asc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_source_task(self, source_task_id: str) -> list[DailyTask]:
        result = await self._session.execute(
            select(DailyTaskModel)
            .where(DailyTaskModel.source_task_id == source_task_id)
            .order_by(DailyTaskModel.scheduled_for.asc(), DailyTaskModel.id.asc())
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def update(self, entity: DailyTask) -> None:
        model = await self._session.get(DailyTaskModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.execution_session_id = entity.execution_session_id
        model.last_workflow_run_id = entity.last_workflow_run_id
        model.result_note = entity.result_note
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def bulk_mark_superseded(self, study_plan_id: str) -> None:
        await self._session.execute(
            update(DailyTaskModel)
            .where(
                DailyTaskModel.study_plan_id == study_plan_id,
                DailyTaskModel.status.in_(["pending", "in_progress"]),
            )
            .values(status="superseded", updated_at=datetime.now(timezone.utc))
        )
        await self._session.flush()

    @staticmethod
    def _to_model(entity: DailyTask) -> DailyTaskModel:
        return DailyTaskModel(
            id=entity.id,
            learner_goal_id=entity.learner_goal_id,
            study_plan_id=entity.study_plan_id,
            plan_stage_id=entity.plan_stage_id,
            task_origin=entity.task_origin,
            task_type=entity.task_type,
            execution_mode=entity.execution_mode,
            title=entity.title,
            instructions=entity.instructions,
            topic_focus=entity.topic_focus,
            difficulty=entity.difficulty,
            question_count=entity.question_count,
            estimated_minutes=entity.estimated_minutes,
            scheduled_for=entity.scheduled_for,
            due_on=entity.due_on,
            status=entity.status,
            source_task_id=entity.source_task_id,
            execution_session_id=entity.execution_session_id,
            last_workflow_run_id=entity.last_workflow_run_id,
            result_note=entity.result_note,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    @staticmethod
    def _to_entity(model: DailyTaskModel) -> DailyTask:
        return DailyTask(
            id=model.id,
            learner_goal_id=model.learner_goal_id,
            study_plan_id=model.study_plan_id,
            plan_stage_id=model.plan_stage_id,
            task_origin=model.task_origin,
            task_type=model.task_type,
            execution_mode=model.execution_mode,
            title=model.title,
            instructions=model.instructions,
            topic_focus=model.topic_focus,
            difficulty=model.difficulty,
            question_count=model.question_count,
            estimated_minutes=model.estimated_minutes,
            scheduled_for=model.scheduled_for,
            due_on=model.due_on,
            status=model.status,
            source_task_id=model.source_task_id,
            execution_session_id=model.execution_session_id,
            last_workflow_run_id=model.last_workflow_run_id,
            result_note=model.result_note,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )



class WorkflowRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: WorkflowRun) -> None:
        model = WorkflowRunModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()

    async def update(self, entity: WorkflowRun) -> None:
        model = await self._session.get(WorkflowRunModel, entity.id)
        if model is None:
            return
        model.status = entity.status
        model.scheduled_job_id = entity.scheduled_job_id
        model.result_resource_type = entity.result_resource_type
        model.result_resource_ids = entity.result_resource_ids
        model.error_code = entity.error_code
        model.started_at = entity.started_at
        model.finished_at = entity.finished_at
        await self._session.flush()

    async def get_by_id(self, run_id: str) -> WorkflowRun | None:
        model = await self._session.get(WorkflowRunModel, run_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def list_by_goal(self, learner_goal_id: str) -> list[WorkflowRun]:
        result = await self._session.execute(
            select(WorkflowRunModel)
            .where(WorkflowRunModel.learner_goal_id == learner_goal_id)
            .order_by(desc(WorkflowRunModel.created_at), desc(WorkflowRunModel.id))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_recent_by_goal(self, learner_goal_id: str, *, limit: int = 10) -> list[WorkflowRun]:
        result = await self._session.execute(
            select(WorkflowRunModel)
            .where(WorkflowRunModel.learner_goal_id == learner_goal_id)
            .order_by(desc(WorkflowRunModel.created_at), desc(WorkflowRunModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: WorkflowRunModel) -> WorkflowRun:
        return WorkflowRun(
            id=model.id,
            workflow_type=model.workflow_type,
            status=model.status,
            trigger_source=model.trigger_source,
            learner_goal_id=model.learner_goal_id,
            study_plan_id=model.study_plan_id,
            daily_task_id=model.daily_task_id,
            scheduled_job_id=model.scheduled_job_id,
            result_resource_type=model.result_resource_type,
            result_resource_ids=list(model.result_resource_ids or []),
            error_code=model.error_code,
            created_at=model.created_at,
            started_at=model.started_at,
            finished_at=model.finished_at,
        )


