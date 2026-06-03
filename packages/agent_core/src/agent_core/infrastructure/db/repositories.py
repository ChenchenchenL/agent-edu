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
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent
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


class SkillArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: SkillArtifact) -> None:
        self._session.add(
            SkillArtifactModel(
                id=entity.id,
                name=entity.name,
                version=entity.version,
                lineage_id=entity.lineage_id,
                parent_artifact_id=entity.parent_artifact_id,
                supersedes_artifact_id=entity.supersedes_artifact_id,
                skill_type=entity.skill_type,
                scope=entity.scope,
                status=entity.status,
                description=entity.description,
                definition=entity.definition,
                runtime_directives=entity.runtime_directives,
                tool_plan=entity.tool_plan,
                compatibility_contract=entity.compatibility_contract,
                source_reflection_ids=entity.source_reflection_ids,
                source_memory_ids=entity.source_memory_ids,
                source_proposal_id=entity.source_proposal_id,
                quality_score=entity.quality_score,
                created_by=entity.created_by,
                approved_by=entity.approved_by,
                approved_at=entity.approved_at,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
        )
        await self._session.flush()

    async def update(self, entity: SkillArtifact) -> None:
        model = await self._session.get(SkillArtifactModel, entity.id)
        if model is None:
            return
        model.name = entity.name
        model.version = entity.version
        model.lineage_id = entity.lineage_id
        model.parent_artifact_id = entity.parent_artifact_id
        model.supersedes_artifact_id = entity.supersedes_artifact_id
        model.skill_type = entity.skill_type
        model.scope = entity.scope
        model.status = entity.status
        model.description = entity.description
        model.definition = dict(entity.definition)
        model.runtime_directives = dict(entity.runtime_directives)
        model.tool_plan = [dict(item) for item in entity.tool_plan]
        model.compatibility_contract = dict(entity.compatibility_contract)
        model.source_reflection_ids = list(entity.source_reflection_ids)
        model.source_memory_ids = list(entity.source_memory_ids)
        model.source_proposal_id = entity.source_proposal_id
        model.quality_score = entity.quality_score
        model.created_by = entity.created_by
        model.approved_by = entity.approved_by
        model.approved_at = entity.approved_at
        model.created_at = entity.created_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_id(self, artifact_id: str) -> SkillArtifact | None:
        model = await self._session.get(SkillArtifactModel, artifact_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_source_proposal_id(self, proposal_id: str) -> SkillArtifact | None:
        result = await self._session.execute(
            select(SkillArtifactModel)
            .where(SkillArtifactModel.source_proposal_id == proposal_id)
            .order_by(desc(SkillArtifactModel.created_at), desc(SkillArtifactModel.id))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_selectable_by_name_scope(self, *, name: str, scope: str) -> SkillArtifact | None:
        stable = await self._get_latest_by_name_scope_status(name=name, scope=scope, status="stable")
        if stable is not None:
            return stable
        return await self._get_latest_by_name_scope_status(name=name, scope=scope, status="active")

    async def _get_latest_by_name_scope_status(self, *, name: str, scope: str, status: str) -> SkillArtifact | None:
        result = await self._session.execute(
            select(SkillArtifactModel)
            .where(
                SkillArtifactModel.name == name,
                SkillArtifactModel.scope == scope,
                SkillArtifactModel.status == status,
            )
            .order_by(desc(SkillArtifactModel.updated_at), desc(SkillArtifactModel.id))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_suppressed_by_name_scope(self, *, name: str, scope: str) -> SkillArtifact | None:
        result = await self._session.execute(
            select(SkillArtifactModel)
            .where(
                SkillArtifactModel.name == name,
                SkillArtifactModel.scope == scope,
                SkillArtifactModel.status == "suppressed",
            )
            .order_by(desc(SkillArtifactModel.updated_at), desc(SkillArtifactModel.id))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_artifacts(
        self,
        *,
        status: str | None = None,
        name: str | None = None,
        scope: str | None = None,
        lineage_id: str | None = None,
        limit: int = 50,
    ) -> list[SkillArtifact]:
        query = select(SkillArtifactModel)
        if status is not None:
            query = query.where(SkillArtifactModel.status == status)
        if name is not None:
            query = query.where(SkillArtifactModel.name == name)
        if scope is not None:
            query = query.where(SkillArtifactModel.scope == scope)
        if lineage_id is not None:
            query = query.where(SkillArtifactModel.lineage_id == lineage_id)
        result = await self._session.execute(
            query.order_by(desc(SkillArtifactModel.updated_at), desc(SkillArtifactModel.id)).limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_by_name(self, name: str, *, limit: int = 200) -> list[SkillArtifact]:
        result = await self._session.execute(
            select(SkillArtifactModel)
            .where(SkillArtifactModel.name == name)
            .order_by(desc(SkillArtifactModel.created_at), desc(SkillArtifactModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def max_candidate_patch_version(self, name: str) -> int:
        result = await self._session.execute(
            select(func.max(cast(func.substr(SkillArtifactModel.version, 5), Integer))).where(
                SkillArtifactModel.name == name,
                SkillArtifactModel.version.like("0.1.%"),
            )
        )
        max_patch = result.scalar_one()
        return int(max_patch) if max_patch is not None else -1

    async def list_by_lineage(self, lineage_id: str, *, limit: int = 50) -> list[SkillArtifact]:
        result = await self._session.execute(
            select(SkillArtifactModel)
            .where(SkillArtifactModel.lineage_id == lineage_id)
            .order_by(desc(SkillArtifactModel.updated_at), desc(SkillArtifactModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: SkillArtifactModel) -> SkillArtifact:
        return SkillArtifact(
            id=model.id,
            name=model.name,
            version=model.version,
            lineage_id=model.lineage_id,
            parent_artifact_id=model.parent_artifact_id,
            supersedes_artifact_id=model.supersedes_artifact_id,
            skill_type=model.skill_type,
            scope=model.scope,
            status=model.status,
            description=model.description,
            definition=dict(model.definition or {}),
            runtime_directives=dict(model.runtime_directives or {}),
            tool_plan=[dict(item) for item in model.tool_plan or []],
            compatibility_contract=dict(model.compatibility_contract or {}),
            source_reflection_ids=list(model.source_reflection_ids or []),
            source_memory_ids=list(model.source_memory_ids or []),
            source_proposal_id=model.source_proposal_id,
            quality_score=model.quality_score,
            created_by=model.created_by,
            approved_by=model.approved_by,
            approved_at=model.approved_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SkillUsageEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: SkillUsageEvent) -> None:
        model = SkillUsageEventModel(
            id=entity.id,
            skill_artifact_id=entity.skill_artifact_id,
            skill_name=entity.skill_name,
            skill_version=entity.skill_version,
            skill_status_at_use=entity.skill_status_at_use,
            learner_profile_id=entity.learner_profile_id,
            learner_goal_id=entity.learner_goal_id,
            session_id=entity.session_id,
            daily_task_id=entity.daily_task_id,
            workflow_run_id=entity.workflow_run_id,
            surface=entity.surface,
            topic_key=entity.topic_key,
            trigger_source=entity.trigger_source,
            outcome_status=entity.outcome_status,
            latency_ms=entity.latency_ms,
            cost_units=entity.cost_units,
            input_summary=entity.input_summary,
            input_fingerprint=entity.input_fingerprint,
            output_summary=entity.output_summary,
            output_fingerprint=entity.output_fingerprint,
            error_code=entity.error_code,
            resolver_status=entity.resolver_status,
            selection_reason=entity.selection_reason,
            outcome_signals=entity.outcome_signals,
            usage_metadata=entity.metadata,
            created_at=entity.created_at,
        )
        self._session.add(model)
        await self._session.flush()

    async def list_by_artifact(self, artifact_id: str, *, limit: int = 50) -> list[SkillUsageEvent]:
        result = await self._session.execute(
            select(SkillUsageEventModel)
            .where(SkillUsageEventModel.skill_artifact_id == artifact_id)
            .order_by(desc(SkillUsageEventModel.created_at), desc(SkillUsageEventModel.id))
            .limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_events(
        self,
        *,
        artifact_id: str | None = None,
        skill_name: str | None = None,
        learner_goal_id: str | None = None,
        session_id: str | None = None,
        surface: str | None = None,
        outcome_status: str | None = None,
        resolver_status: str | None = None,
        created_at_from: datetime | None = None,
        limit: int = 50,
    ) -> list[SkillUsageEvent]:
        query = select(SkillUsageEventModel)
        if artifact_id is not None:
            query = query.where(SkillUsageEventModel.skill_artifact_id == artifact_id)
        if skill_name is not None:
            query = query.where(SkillUsageEventModel.skill_name == skill_name)
        if learner_goal_id is not None:
            query = query.where(SkillUsageEventModel.learner_goal_id == learner_goal_id)
        if session_id is not None:
            query = query.where(SkillUsageEventModel.session_id == session_id)
        if surface is not None:
            query = query.where(SkillUsageEventModel.surface == surface)
        if outcome_status is not None:
            query = query.where(SkillUsageEventModel.outcome_status == outcome_status)
        if resolver_status is not None:
            query = query.where(SkillUsageEventModel.resolver_status == resolver_status)
        if created_at_from is not None:
            query = query.where(SkillUsageEventModel.created_at >= created_at_from)
        result = await self._session.execute(
            query.order_by(desc(SkillUsageEventModel.created_at), desc(SkillUsageEventModel.id)).limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    @staticmethod
    def _to_entity(model: SkillUsageEventModel) -> SkillUsageEvent:
        return SkillUsageEvent(
            id=model.id,
            skill_artifact_id=model.skill_artifact_id,
            skill_name=model.skill_name,
            skill_version=model.skill_version,
            skill_status_at_use=model.skill_status_at_use,
            learner_profile_id=model.learner_profile_id,
            learner_goal_id=model.learner_goal_id,
            session_id=model.session_id,
            daily_task_id=model.daily_task_id,
            workflow_run_id=model.workflow_run_id,
            surface=model.surface,
            topic_key=model.topic_key,
            trigger_source=model.trigger_source,
            outcome_status=model.outcome_status,
            latency_ms=model.latency_ms,
            cost_units=model.cost_units,
            input_summary=model.input_summary,
            input_fingerprint=model.input_fingerprint,
            output_summary=model.output_summary,
            output_fingerprint=model.output_fingerprint,
            error_code=model.error_code,
            resolver_status=model.resolver_status,
            selection_reason=model.selection_reason,
            outcome_signals=dict(model.outcome_signals or {}),
            metadata=dict(model.usage_metadata or {}),
            created_at=model.created_at,
        )


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


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: AuditEvent) -> None:
        model = AuditEventModel(**entity.__dict__)
        self._session.add(model)
        await self._session.flush()


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


class ReflectionProposalRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
