from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, and_, asc, cast, desc, distinct, func, or_, select, update
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


class SkillArtifactRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    _AUTO_STAGED_ARTIFACT_STATUSES = (
        "staged",
        "active",
        "stable",
        "deprecated",
        "archived",
        "suppressed",
    )

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
                deprecated_by=entity.deprecated_by,
                deprecated_at=entity.deprecated_at,
                suppressed_reason_code=entity.suppressed_reason_code,
                suppressed_reason_note=entity.suppressed_reason_note,
                suppressed_by=entity.suppressed_by,
                suppressed_at=entity.suppressed_at,
                suppressed_previous_status=entity.suppressed_previous_status,
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
        model.deprecated_by = entity.deprecated_by
        model.deprecated_at = entity.deprecated_at
        model.suppressed_reason_code = entity.suppressed_reason_code
        model.suppressed_reason_note = entity.suppressed_reason_note
        model.suppressed_by = entity.suppressed_by
        model.suppressed_at = entity.suppressed_at
        model.suppressed_previous_status = entity.suppressed_previous_status
        model.created_at = entity.created_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_id(self, artifact_id: str) -> SkillArtifact | None:
        model = await self._session.get(SkillArtifactModel, artifact_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_id_for_update(self, artifact_id: str) -> SkillArtifact | None:
        result = await self._session.execute(
            select(SkillArtifactModel)
            .where(SkillArtifactModel.id == artifact_id)
            .with_for_update()
        )
        model = result.scalars().first()
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

    async def get_selectable_by_name_scope_for_update(self, *, name: str, scope: str) -> SkillArtifact | None:
        stable = await self._get_latest_by_name_scope_status(name=name, scope=scope, status="stable", for_update=True)
        if stable is not None:
            return stable
        return await self._get_latest_by_name_scope_status(name=name, scope=scope, status="active", for_update=True)

    async def _get_latest_by_name_scope_status(
        self,
        *,
        name: str,
        scope: str,
        status: str,
        for_update: bool = False,
    ) -> SkillArtifact | None:
        query = (
            select(SkillArtifactModel)
            .where(
                SkillArtifactModel.name == name,
                SkillArtifactModel.scope == scope,
                SkillArtifactModel.status == status,
            )
            .order_by(desc(SkillArtifactModel.updated_at), desc(SkillArtifactModel.id))
        )
        if for_update:
            query = query.with_for_update()
        result = await self._session.execute(
            query
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def get_suppressed_by_name_scope(self, *, name: str, scope: str) -> SkillArtifact | None:
        return await self._get_latest_by_name_scope_status(name=name, scope=scope, status="suppressed")

    async def get_suppressed_by_name_scope_for_update(self, *, name: str, scope: str) -> SkillArtifact | None:
        return await self._get_latest_by_name_scope_status(
            name=name,
            scope=scope,
            status="suppressed",
            for_update=True,
        )

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

    async def count_by_status(self) -> dict[str, int]:
        result = await self._session.execute(
            select(SkillArtifactModel.status, func.count(SkillArtifactModel.id)).group_by(SkillArtifactModel.status)
        )
        return {str(status): int(count) for status, count in result.all()}

    async def count_recent_system_staged_replacements_for_goal(
        self,
        *,
        learner_goal_id: str,
        created_at_from: datetime,
    ) -> int:
        """Count recent system-created staged replacement artifacts for one goal.

        Args:
            learner_goal_id: Learner goal identifier.
            created_at_from: Inclusive lower bound for artifact creation time.

        Returns:
            The number of recent staged-or-beyond artifacts created by `system`
            from proposals linked to the target goal.
        """
        result = await self._session.execute(
            select(func.count(distinct(SkillArtifactModel.id)))
            .select_from(SkillArtifactModel)
            .join(
                ReflectionProposalModel,
                ReflectionProposalModel.id == SkillArtifactModel.source_proposal_id,
            )
            .where(
                ReflectionProposalModel.learner_goal_id == learner_goal_id,
                SkillArtifactModel.created_at >= created_at_from,
                SkillArtifactModel.created_by == "system",
                SkillArtifactModel.status.in_(self._AUTO_STAGED_ARTIFACT_STATUSES),
            )
        )
        return int(result.scalar_one())

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
            deprecated_by=model.deprecated_by,
            deprecated_at=model.deprecated_at,
            suppressed_reason_code=model.suppressed_reason_code,
            suppressed_reason_note=model.suppressed_reason_note,
            suppressed_by=model.suppressed_by,
            suppressed_at=model.suppressed_at,
            suppressed_previous_status=model.suppressed_previous_status,
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



class SkillCuratorRecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, entity: SkillCuratorRecommendation) -> None:
        self._session.add(
            SkillCuratorRecommendationModel(
                id=entity.id,
                artifact_id=entity.artifact_id,
                skill_name=entity.skill_name,
                skill_version=entity.skill_version,
                artifact_status=entity.artifact_status,
                lineage_id=entity.lineage_id,
                scope=entity.scope,
                surface=entity.surface,
                recommendation_type=entity.recommendation_type,
                recommended_action=entity.recommended_action,
                status=entity.status,
                reason_code=entity.reason_code,
                reason_note=entity.reason_note,
                evidence_snapshot=entity.evidence_snapshot,
                metrics_snapshot=entity.metrics_snapshot,
                related_artifact_ids=entity.related_artifact_ids,
                source_job_id=entity.source_job_id,
                created_by=entity.created_by,
                accepted_by=entity.accepted_by,
                accepted_at=entity.accepted_at,
                dismissed_by=entity.dismissed_by,
                dismissed_at=entity.dismissed_at,
                decision_reason_code=entity.decision_reason_code,
                decision_reason_note=entity.decision_reason_note,
                action_result=entity.action_result,
                created_at=entity.created_at,
                updated_at=entity.updated_at,
            )
        )
        await self._session.flush()

    async def update(self, entity: SkillCuratorRecommendation) -> None:
        model = await self._session.get(SkillCuratorRecommendationModel, entity.id)
        if model is None:
            return
        model.artifact_id = entity.artifact_id
        model.skill_name = entity.skill_name
        model.skill_version = entity.skill_version
        model.artifact_status = entity.artifact_status
        model.lineage_id = entity.lineage_id
        model.scope = entity.scope
        model.surface = entity.surface
        model.recommendation_type = entity.recommendation_type
        model.recommended_action = entity.recommended_action
        model.status = entity.status
        model.reason_code = entity.reason_code
        model.reason_note = entity.reason_note
        model.evidence_snapshot = dict(entity.evidence_snapshot)
        model.metrics_snapshot = dict(entity.metrics_snapshot)
        model.related_artifact_ids = list(entity.related_artifact_ids)
        model.source_job_id = entity.source_job_id
        model.created_by = entity.created_by
        model.accepted_by = entity.accepted_by
        model.accepted_at = entity.accepted_at
        model.dismissed_by = entity.dismissed_by
        model.dismissed_at = entity.dismissed_at
        model.decision_reason_code = entity.decision_reason_code
        model.decision_reason_note = entity.decision_reason_note
        model.action_result = dict(entity.action_result)
        model.created_at = entity.created_at
        model.updated_at = entity.updated_at
        await self._session.flush()

    async def get_by_id(self, recommendation_id: str) -> SkillCuratorRecommendation | None:
        model = await self._session.get(SkillCuratorRecommendationModel, recommendation_id)
        if model is None:
            return None
        return self._to_entity(model)

    async def get_by_source_job_id(self, source_job_id: str) -> SkillCuratorRecommendation | None:
        result = await self._session.execute(
            select(SkillCuratorRecommendationModel)
            .where(SkillCuratorRecommendationModel.source_job_id == source_job_id)
            .order_by(desc(SkillCuratorRecommendationModel.created_at), desc(SkillCuratorRecommendationModel.id))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def find_pending_duplicate(
        self,
        *,
        artifact_id: str | None,
        skill_name: str,
        scope: str,
        surface: str,
        recommendation_type: str,
        recommended_action: str,
        reason_code: str,
    ) -> SkillCuratorRecommendation | None:
        query = select(SkillCuratorRecommendationModel).where(
            SkillCuratorRecommendationModel.skill_name == skill_name,
            SkillCuratorRecommendationModel.scope == scope,
            SkillCuratorRecommendationModel.surface == surface,
            SkillCuratorRecommendationModel.recommendation_type == recommendation_type,
            SkillCuratorRecommendationModel.recommended_action == recommended_action,
            SkillCuratorRecommendationModel.reason_code == reason_code,
            SkillCuratorRecommendationModel.status == "pending",
        )
        if artifact_id is None:
            query = query.where(SkillCuratorRecommendationModel.artifact_id.is_(None))
        else:
            query = query.where(SkillCuratorRecommendationModel.artifact_id == artifact_id)
        result = await self._session.execute(
            query.order_by(desc(SkillCuratorRecommendationModel.created_at), desc(SkillCuratorRecommendationModel.id))
        )
        model = result.scalars().first()
        if model is None:
            return None
        return self._to_entity(model)

    async def list_recommendations(
        self,
        *,
        status: str | None = None,
        recommendation_type: str | None = None,
        recommended_action: str | None = None,
        artifact_id: str | None = None,
        skill_name: str | None = None,
        scope: str | None = None,
        surface: str | None = None,
        limit: int = 50,
    ) -> list[SkillCuratorRecommendation]:
        query = select(SkillCuratorRecommendationModel)
        if status is not None:
            query = query.where(SkillCuratorRecommendationModel.status == status)
        if recommendation_type is not None:
            query = query.where(SkillCuratorRecommendationModel.recommendation_type == recommendation_type)
        if recommended_action is not None:
            query = query.where(SkillCuratorRecommendationModel.recommended_action == recommended_action)
        if artifact_id is not None:
            query = query.where(SkillCuratorRecommendationModel.artifact_id == artifact_id)
        if skill_name is not None:
            query = query.where(SkillCuratorRecommendationModel.skill_name == skill_name)
        if scope is not None:
            query = query.where(SkillCuratorRecommendationModel.scope == scope)
        if surface is not None:
            query = query.where(SkillCuratorRecommendationModel.surface == surface)
        result = await self._session.execute(
            query.order_by(desc(SkillCuratorRecommendationModel.created_at), desc(SkillCuratorRecommendationModel.id)).limit(limit)
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def list_pending_auto_execution_candidates(
        self,
        *,
        limit: int = 20,
        surfaces: set[str] | None = None,
    ) -> list[SkillCuratorRecommendation]:
        query = select(SkillCuratorRecommendationModel).where(
            SkillCuratorRecommendationModel.status == "pending",
            SkillCuratorRecommendationModel.created_by == "skill_curator_job",
            SkillCuratorRecommendationModel.recommendation_type.in_(["activate_candidate", "replace_candidate"]),
            SkillCuratorRecommendationModel.recommended_action.in_(["activate_staged", "replace_selectable"]),
        )
        if surfaces is not None:
            query = query.where(SkillCuratorRecommendationModel.surface.in_(sorted(surfaces)))
        result = await self._session.execute(
            query.order_by(
                asc(SkillCuratorRecommendationModel.created_at),
                asc(SkillCuratorRecommendationModel.id),
            ).limit(bounded_limit(limit))
        )
        return [self._to_entity(model) for model in result.scalars().all()]

    async def count_recent_system_auto_executed_for_goal(
        self,
        *,
        learner_goal_id: str,
        accepted_at_from: datetime,
        accepted_by: str,
    ) -> int:
        result = await self._session.execute(
            select(func.count(distinct(SkillCuratorRecommendationModel.id)))
            .select_from(SkillCuratorRecommendationModel)
            .join(SkillArtifactModel, SkillArtifactModel.id == SkillCuratorRecommendationModel.artifact_id)
            .join(ReflectionProposalModel, ReflectionProposalModel.id == SkillArtifactModel.source_proposal_id)
            .where(
                ReflectionProposalModel.learner_goal_id == learner_goal_id,
                SkillCuratorRecommendationModel.status == "accepted",
                SkillCuratorRecommendationModel.accepted_by == accepted_by,
                SkillCuratorRecommendationModel.accepted_at.is_not(None),
                SkillCuratorRecommendationModel.accepted_at >= accepted_at_from,
                SkillCuratorRecommendationModel.recommended_action.in_(["activate_staged", "replace_selectable"]),
            )
        )
        return int(result.scalar_one())

    async def count_pending_by_type(self) -> dict[str, int]:
        result = await self._session.execute(
            select(
                SkillCuratorRecommendationModel.recommendation_type,
                func.count(SkillCuratorRecommendationModel.id),
            )
            .where(SkillCuratorRecommendationModel.status == "pending")
            .group_by(SkillCuratorRecommendationModel.recommendation_type)
        )
        return {str(recommendation_type): int(count) for recommendation_type, count in result.all()}

    @staticmethod
    def _to_entity(model: SkillCuratorRecommendationModel) -> SkillCuratorRecommendation:
        return SkillCuratorRecommendation(
            id=model.id,
            artifact_id=model.artifact_id,
            skill_name=model.skill_name,
            skill_version=model.skill_version,
            artifact_status=model.artifact_status,
            lineage_id=model.lineage_id,
            scope=model.scope,
            surface=model.surface,
            recommendation_type=model.recommendation_type,
            recommended_action=model.recommended_action,
            status=model.status,
            reason_code=model.reason_code,
            reason_note=model.reason_note,
            evidence_snapshot=dict(model.evidence_snapshot or {}),
            metrics_snapshot=dict(model.metrics_snapshot or {}),
            related_artifact_ids=list(model.related_artifact_ids or []),
            source_job_id=model.source_job_id,
            created_by=model.created_by,
            accepted_by=model.accepted_by,
            accepted_at=model.accepted_at,
            dismissed_by=model.dismissed_by,
            dismissed_at=model.dismissed_at,
            decision_reason_code=model.decision_reason_code,
            decision_reason_note=model.decision_reason_note,
            action_result=dict(model.action_result or {}),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

