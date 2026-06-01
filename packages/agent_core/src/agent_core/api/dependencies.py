from __future__ import annotations

from functools import lru_cache
import secrets

from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from agent_core.api.access_control import AccessContext
from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.chat import ChatService
from agent_core.application.services.goal import LearnerGoalService
from agent_core.application.services.goal_skill_binding_resolver import GoalSkillBindingResolver
from agent_core.application.services.long_term_memory_materialization import LongTermMemoryMaterializationService
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayExecutor,
    LongTermMemoryMaterializationReplayScheduler,
)
from agent_core.application.services.memory import MemoryService
from agent_core.application.services.memory_maintenance import MemoryMaintenanceService
from agent_core.application.services.profile_access import hash_profile_access_key
from agent_core.application.services.message_history import MessageHistoryService
from agent_core.application.services.planner import PlannerService
from agent_core.application.services.profile import LearnerProfileService
from agent_core.application.services.quiz import QuizService
from agent_core.application.services.reflective_memory import ReflectiveMemoryService
from agent_core.application.services.reflection import ReflectionService
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection_governance import ReflectionGovernanceService
from agent_core.application.services.reflection_outcomes import ReflectionOutcomeService
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.reflection_proposal_rollout_resolver import ReflectionProposalRolloutResolver
from agent_core.application.services.reflection_proposal_rollouts import ReflectionProposalRolloutService
from agent_core.application.services.reflection_proposal_sandbox import ReflectionProposalSandboxService
from agent_core.application.services.reflection_proposals import ReflectionProposalService
from agent_core.application.services.reflection_replay import ReflectionReplayService
from agent_core.application.services.session import SessionService
from agent_core.application.services.skills import SkillCatalogService, SkillResolver, SkillUsageService
from agent_core.application.services.strategy_cards import StrategyCardService
from agent_core.application.services.task import AutonomousTaskService
from agent_core.application.services.workflow import WorkflowRunService
from agent_core.application.services.workspace import WorkspaceService
from agent_core.application.tools.registry import HttpToolSpec, InternalToolRegistry
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.errors import ConfigurationError
from agent_core.infrastructure.config.settings import Settings, get_settings
from agent_core.infrastructure.db.repositories import (
    AuditRepository,
    BehaviorMemoryEmbeddingRepository,
    BehaviorMemoryRepository,
    DailyTaskRepository,
    GoalSkillBindingRepository,
    GoalAutonomyStateRepository,
    LearnerAvailabilityRepository,
    LearnerGoalRepository,
    LearnerProfileRepository,
    KnowledgeMemoryEmbeddingRepository,
    KnowledgeMemoryRepository,
    LearnerTopicMasteryRepository,
    MemoryAnnotationRepository,
    MemoryConflictRepository,
    MemoryEmbeddingRepository,
    MemoryEvidenceLinkRepository,
    MemoryEventRepository,
    MemoryGovernanceDecisionRepository,
    MemoryMaintenanceJobRepository,
    PlanStageRepository,
    ReflectionActionRepository,
    ReflectionEvidenceSignalRepository,
    ReflectionOutcomeEvaluationRepository,
    ReflectionProposalEvaluationRepository,
    ReflectionProposalApprovalDecisionRepository,
    ReflectionProposalRepository,
    ReflectionProposalRolloutDecisionRepository,
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
    ReflectionProposalSandboxRunRepository,
    ReflectionRecordRepository,
    ReflectionReviewDecisionRepository,
    ReflectiveMemoryRepository,
    ScheduledAutonomyJobRepository,
    SessionMessageRepository,
    SessionQuizRepository,
    SkillArtifactRepository,
    SkillUsageEventRepository,
    SessionRepository,
    StudyPlanRepository,
    TaskAttemptRepository,
    WorkflowRunRepository,
    LearnerGoalStrategyCardRepository,
)
from agent_core.infrastructure.embedding.dashscope_compatible_provider import DashScopeCompatibleEmbeddingProvider
from agent_core.infrastructure.embedding.types import EmbeddingProvider
from agent_core.infrastructure.llm.dashscope_compatible_provider import DashScopeCompatibleLLMProvider
from agent_core.infrastructure.llm.mock_provider import MockLLMProvider
from agent_core.infrastructure.llm.types import LLMProvider
from agent_core.infrastructure.redis.client import RedisHealthClient


@lru_cache(maxsize=1)
def get_engine():
    settings = get_settings()
    poolclass = NullPool if settings.app_env != "production" else None
    if poolclass is None:
        return create_async_engine(settings.database_url, future=True)
    return create_async_engine(settings.database_url, future=True, poolclass=poolclass)


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


@lru_cache(maxsize=1)
def get_redis_client() -> RedisHealthClient:
    settings = get_settings()
    return RedisHealthClient(settings.redis_url)


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    settings = get_settings()
    return SkillRegistry.from_allowed_skills(settings.allowed_skills)


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    settings.validate_llm_configuration()
    provider_name = settings.llm_provider_name
    if provider_name == "mock":
        return MockLLMProvider(model_name=settings.llm_model)
    if provider_name in {"dashscope_compatible", "dashscope", "aliyun"}:
        if settings.llm_api_key is None or settings.llm_base_url is None:
            raise ConfigurationError("DashScope-compatible provider requires API key and base URL configuration.")
        return DashScopeCompatibleLLMProvider(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            default_model=settings.llm_model,
            tutor_model=settings.tutor_model_name,
            quiz_model=settings.quiz_model_name,
            hint_model=settings.hint_model_name,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    raise ConfigurationError(f"Unsupported AGENT_EDU_LLM_PROVIDER value: {settings.llm_provider}")


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider | None:
    settings = get_settings()
    provider_name = settings.embedding_provider_name
    if provider_name is None:
        return None

    settings.validate_embedding_configuration()
    if provider_name in {"dashscope", "dashscope_compatible", "aliyun"}:
        return DashScopeCompatibleEmbeddingProvider(
            api_key=settings.embedding_api_key_value or "",
            base_url=settings.embedding_base_url_value or "",
            model_name=settings.embedding_model or "",
            timeout_seconds=settings.embedding_timeout_seconds,
            dimensions=settings.embedding_dimensions,
        )
    raise ConfigurationError(f"Unsupported AGENT_EDU_EMBEDDING_PROVIDER value: {settings.embedding_provider}")


async def get_db_session() -> AsyncSession:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session


def get_settings_dependency() -> Settings:
    return get_settings()


def _operator_key_is_valid(value: str | None) -> bool:
    settings = get_settings()
    configured = settings.operator_api_key.get_secret_value().strip() if settings.operator_api_key is not None else ""
    provided = value.strip() if value is not None else ""
    return bool(configured and provided and secrets.compare_digest(provided, configured))


def require_operator_api_key(x_operator_key: str | None = Header(default=None, alias="X-Operator-Key")) -> str:
    if not _operator_key_is_valid(x_operator_key):
        raise HTTPException(status_code=403, detail="Invalid operator API key.")
    return x_operator_key.strip()


async def get_access_context(
    x_operator_key: str | None = Header(default=None, alias="X-Operator-Key"),
    x_learner_key: str | None = Header(default=None, alias="X-Learner-Key"),
    session: AsyncSession = Depends(get_db_session),
) -> AccessContext:
    if _operator_key_is_valid(x_operator_key):
        return AccessContext(actor_type="operator", learner_profile_id=None)

    learner_key = x_learner_key.strip() if x_learner_key is not None else ""
    if learner_key:
        profile = await LearnerProfileRepository(session).get_by_access_key_hash(hash_profile_access_key(learner_key))
        if profile is not None:
            return AccessContext(actor_type="learner", learner_profile_id=profile.id)

    raise HTTPException(status_code=401, detail="Missing or invalid access credentials.")


def get_audit_service(session: AsyncSession) -> AuditService:
    return AuditService(AuditRepository(session), get_session_factory())


def get_memory_service(session: AsyncSession) -> MemoryService:
    settings = get_settings()
    return MemoryService(
        MemoryEventRepository(session),
        embedding_repository=MemoryEmbeddingRepository(session),
        embedding_provider=get_embedding_provider(),
        audit_service=get_audit_service(session),
        knowledge_memory_repository=KnowledgeMemoryRepository(session),
        knowledge_memory_embedding_repository=KnowledgeMemoryEmbeddingRepository(session),
        behavior_memory_repository=BehaviorMemoryRepository(session),
        behavior_memory_embedding_repository=BehaviorMemoryEmbeddingRepository(session),
        evidence_link_repository=MemoryEvidenceLinkRepository(session),
        governance_decision_repository=MemoryGovernanceDecisionRepository(session),
        conflict_repository=MemoryConflictRepository(session),
        annotation_repository=MemoryAnnotationRepository(session),
        task_attempt_repository=TaskAttemptRepository(session),
        learner_topic_mastery_repository=LearnerTopicMasteryRepository(session),
        governance_config={
            "candidate_to_active_evidence_min": settings.memory_candidate_to_active_evidence_min,
            "candidate_to_active_support_min": settings.memory_candidate_to_active_support_min,
            "candidate_to_active_confidence_min": settings.memory_candidate_to_active_confidence_min,
            "candidate_to_active_contradiction_max": settings.memory_candidate_to_active_contradiction_max,
            "active_to_stable_evidence_min": settings.memory_active_to_stable_evidence_min,
            "active_to_stable_stability_min": settings.memory_active_to_stable_stability_min,
            "active_to_stable_assessment_min": settings.memory_active_to_stable_assessment_min,
            "stable_demote_contradiction_min": settings.memory_stable_demote_contradiction_min,
            "stable_demote_freshness_max": settings.memory_stable_demote_freshness_max,
            "archive_freshness_max": settings.memory_archive_freshness_max,
            "archive_goal_relevance_max": settings.memory_archive_goal_relevance_max,
            "behavior_candidate_recurrence_min": settings.memory_behavior_candidate_recurrence_min,
            "behavior_active_recurrence_min": settings.memory_behavior_active_recurrence_min,
            "behavior_active_to_stable_stability_min": settings.memory_behavior_active_to_stable_stability_min,
            "reflection_effective_weight": settings.memory_reflection_effective_weight,
            "reflection_ineffective_weight": settings.memory_reflection_ineffective_weight,
            "compression_min_group_size": settings.memory_compression_min_group_size,
        },
    )


def get_memory_maintenance_service(session: AsyncSession) -> MemoryMaintenanceService:
    settings = get_settings()
    return MemoryMaintenanceService(
        repository=MemoryMaintenanceJobRepository(session),
        memory_service=get_memory_service(session),
        audit_service=get_audit_service(session),
        db_session=session,
        jobs_per_tick=settings.memory_maintenance_jobs_per_tick,
        batch_size=settings.memory_maintenance_batch_size,
        lease_seconds=settings.memory_maintenance_lease_seconds,
        max_attempts=settings.memory_maintenance_retry_max_attempts,
    )


def get_long_term_memory_materialization_service(session: AsyncSession) -> LongTermMemoryMaterializationService:
    return LongTermMemoryMaterializationService(get_memory_service(session), audit_service=get_audit_service(session))


def get_profile_service(session: AsyncSession) -> LearnerProfileService:
    return LearnerProfileService(
        LearnerProfileRepository(session),
        session,
        get_audit_service(session),
    )


def get_goal_service(session: AsyncSession) -> LearnerGoalService:
    return LearnerGoalService(
        repository=LearnerGoalRepository(session),
        learner_profile_repository=LearnerProfileRepository(session),
        db_session=session,
        audit_service=get_audit_service(session),
        goal_autonomy_state_repository=GoalAutonomyStateRepository(session),
        learner_availability_repository=LearnerAvailabilityRepository(session),
    )


def get_planner_service(session: AsyncSession) -> PlannerService:
    return PlannerService(
        llm_provider=get_llm_provider(),
        audit_service=get_audit_service(session),
        strategy_card_service=get_strategy_card_service(session),
        rollout_resolver=get_reflection_proposal_rollout_resolver(session),
        goal_skill_binding_resolver=get_goal_skill_binding_resolver(session),
        skill_usage_service=get_skill_usage_service(session),
    )


def get_workflow_run_service(session: AsyncSession) -> WorkflowRunService:
    return WorkflowRunService(
        repository=WorkflowRunRepository(session),
        db_session=session,
        audit_service=get_audit_service(session),
    )


def get_session_service(session: AsyncSession) -> SessionService:
    return SessionService(
        SessionRepository(session),
        LearnerProfileRepository(session),
        LearnerGoalRepository(session),
        session,
        get_audit_service(session),
    )


def get_message_history_service(session: AsyncSession) -> MessageHistoryService:
    return MessageHistoryService(
        session_repository=SessionRepository(session),
        message_repository=SessionMessageRepository(session),
    )


def get_chat_service(session: AsyncSession) -> ChatService:
    audit_service = get_audit_service(session)
    memory_service = get_memory_service(session)
    return ChatService(
        db_session=session,
        session_repository=SessionRepository(session),
        message_repository=SessionMessageRepository(session),
        quiz_repository=SessionQuizRepository(session),
        memory_service=memory_service,
        long_term_memory_materialization_service=LongTermMemoryMaterializationService(
            memory_service,
            audit_service=audit_service,
        ),
        long_term_memory_replay_scheduler=LongTermMemoryMaterializationReplayScheduler(
            autonomy_job_service=get_autonomy_job_service(session),
        ),
        reflection_evidence_service=get_reflection_evidence_service(session),
        strategy_card_service=get_strategy_card_service(session),
        rollout_resolver=get_reflection_proposal_rollout_resolver(session),
        rollout_observation_scheduler=get_reflection_proposal_rollout_observation_scheduler(session),
        goal_skill_binding_resolver=get_goal_skill_binding_resolver(session),
        audit_service=audit_service,
        llm_provider=get_llm_provider(),
        skill_registry=get_skill_registry(),
        skill_usage_service=get_skill_usage_service(session),
    )


def get_quiz_service(session: AsyncSession) -> QuizService:
    return QuizService(
        db_session=session,
        audit_service=get_audit_service(session),
        session_repository=SessionRepository(session),
        quiz_repository=SessionQuizRepository(session),
        llm_provider=get_llm_provider(),
        skill_registry=get_skill_registry(),
        goal_skill_binding_resolver=get_goal_skill_binding_resolver(session),
        skill_usage_service=get_skill_usage_service(session),
    )


def get_skill_catalog_service(session: AsyncSession = Depends(get_db_session)) -> SkillCatalogService:
    return SkillCatalogService(
        artifact_repository=SkillArtifactRepository(session),
        audit_service=get_audit_service(session),
        skill_registry=get_skill_registry(),
    )


def get_skill_resolver(session: AsyncSession = Depends(get_db_session)) -> SkillResolver:
    return SkillResolver(
        artifact_repository=SkillArtifactRepository(session),
        audit_service=get_audit_service(session),
        skill_registry=get_skill_registry(),
    )


def get_skill_usage_service(session: AsyncSession = Depends(get_db_session)) -> SkillUsageService:
    return SkillUsageService(
        usage_repository=SkillUsageEventRepository(session),
        skill_resolver=get_skill_resolver(session),
        audit_service=get_audit_service(session),
    )


def get_autonomy_job_service(session: AsyncSession) -> AutonomyJobService:
    return AutonomyJobService(
        repository=ScheduledAutonomyJobRepository(session),
        audit_service=get_audit_service(session),
    )


def get_reflection_service(session: AsyncSession) -> ReflectionService:
    return ReflectionService(
        reflection_record_repository=ReflectionRecordRepository(session),
        reflection_action_repository=ReflectionActionRepository(session),
        goal_repository=LearnerGoalRepository(session),
        daily_task_repository=DailyTaskRepository(session),
        workflow_run_repository=WorkflowRunRepository(session),
        study_plan_repository=StudyPlanRepository(session),
        task_attempt_repository=TaskAttemptRepository(session),
        learner_topic_mastery_repository=LearnerTopicMasteryRepository(session),
        goal_autonomy_state_repository=GoalAutonomyStateRepository(session),
        session_repository=SessionRepository(session),
        memory_service=get_memory_service(session),
        long_term_memory_materialization_service=get_long_term_memory_materialization_service(session),
        autonomy_job_service=get_autonomy_job_service(session),
        evidence_service=get_reflection_evidence_service(session),
        outcome_service=get_reflection_outcome_service(session),
        governance_service=get_reflection_governance_service(session),
        strategy_card_service=get_strategy_card_service(session),
        reflective_memory_service=get_reflective_memory_service(session),
        proposal_service=get_reflection_proposal_service(session),
        replay_service=get_reflection_replay_service(session),
        audit_service=get_audit_service(session),
        llm_provider=get_llm_provider(),
        db_session=session,
        reflection_max_depth=get_settings().reflection_max_depth,
    )


def get_reflection_evidence_service(session: AsyncSession) -> ReflectionEvidenceService:
    return ReflectionEvidenceService(
        repository=ReflectionEvidenceSignalRepository(session),
        message_repository=SessionMessageRepository(session),
        memory_event_repository=MemoryEventRepository(session),
        daily_task_repository=DailyTaskRepository(session),
        workflow_run_repository=WorkflowRunRepository(session),
        learner_topic_mastery_repository=LearnerTopicMasteryRepository(session),
        audit_service=get_audit_service(session),
    )


def get_reflection_outcome_service(session: AsyncSession) -> ReflectionOutcomeService:
    return ReflectionOutcomeService(
        repository=ReflectionOutcomeEvaluationRepository(session),
        task_attempt_repository=TaskAttemptRepository(session),
        audit_service=get_audit_service(session),
    )


def get_long_term_memory_materialization_replay_executor(
    session: AsyncSession,
) -> LongTermMemoryMaterializationReplayExecutor:
    return LongTermMemoryMaterializationReplayExecutor(
        session_repository=SessionRepository(session),
        message_repository=SessionMessageRepository(session),
        memory_event_repository=MemoryEventRepository(session),
        goal_repository=LearnerGoalRepository(session),
        daily_task_repository=DailyTaskRepository(session),
        task_attempt_repository=TaskAttemptRepository(session),
        reflection_record_repository=ReflectionRecordRepository(session),
        reflection_outcome_evaluation_repository=ReflectionOutcomeEvaluationRepository(session),
        materialization_service=get_long_term_memory_materialization_service(session),
        audit_service=get_audit_service(session),
    )


def get_reflection_governance_service(session: AsyncSession) -> ReflectionGovernanceService:
    return ReflectionGovernanceService(
        reflection_record_repository=ReflectionRecordRepository(session),
        reflection_action_repository=ReflectionActionRepository(session),
        review_decision_repository=ReflectionReviewDecisionRepository(session),
        audit_service=get_audit_service(session),
    )


def get_strategy_card_service(session: AsyncSession) -> StrategyCardService:
    return StrategyCardService(
        repository=LearnerGoalStrategyCardRepository(session),
        audit_service=get_audit_service(session),
    )


def get_reflective_memory_service(session: AsyncSession) -> ReflectiveMemoryService:
    return ReflectiveMemoryService(
        repository=ReflectiveMemoryRepository(session),
        audit_service=get_audit_service(session),
    )


def get_reflection_proposal_service(session: AsyncSession) -> ReflectionProposalService:
    return ReflectionProposalService(
        repository=ReflectionProposalRepository(session),
        approval_decision_repository=ReflectionProposalApprovalDecisionRepository(session),
        evaluation_repository=ReflectionProposalEvaluationRepository(session),
        autonomy_job_service=get_autonomy_job_service(session),
        audit_service=get_audit_service(session),
    )


def get_reflection_replay_service(session: AsyncSession) -> ReflectionReplayService:
    return ReflectionReplayService(
        repository=ReflectionProposalEvaluationRepository(session),
        audit_service=get_audit_service(session),
    )


def get_reflection_proposal_sandbox_service(session: AsyncSession) -> ReflectionProposalSandboxService:
    return ReflectionProposalSandboxService(
        sandbox_run_repository=ReflectionProposalSandboxRunRepository(session),
        proposal_service=get_reflection_proposal_service(session),
        replay_service=get_reflection_replay_service(session),
        audit_service=get_audit_service(session),
        strategy_card_service=get_strategy_card_service(session),
        session_repository=SessionRepository(session),
        message_repository=SessionMessageRepository(session),
        daily_task_repository=DailyTaskRepository(session),
        task_attempt_repository=TaskAttemptRepository(session),
        workflow_run_repository=WorkflowRunRepository(session),
        chat_service=get_chat_service(session),
        internal_tool_registry=InternalToolRegistry(audit_service=get_audit_service(session)),
    )


def get_reflection_proposal_rollout_resolver(session: AsyncSession) -> ReflectionProposalRolloutResolver:
    return ReflectionProposalRolloutResolver(
        rollout_repository=ReflectionProposalRolloutRepository(session),
    )


def get_goal_skill_binding_resolver(session: AsyncSession) -> GoalSkillBindingResolver:
    return GoalSkillBindingResolver(
        repository=GoalSkillBindingRepository(session),
    )


def get_reflection_proposal_rollout_observation_scheduler(
    session: AsyncSession,
) -> ReflectionProposalRolloutObservationScheduler:
    return ReflectionProposalRolloutObservationScheduler(
        rollout_repository=ReflectionProposalRolloutRepository(session),
        autonomy_job_service=get_autonomy_job_service(session),
        audit_service=get_audit_service(session),
    )


def get_reflection_proposal_rollout_service(session: AsyncSession) -> ReflectionProposalRolloutService:
    return ReflectionProposalRolloutService(
        proposal_repository=ReflectionProposalRepository(session),
        rollout_repository=ReflectionProposalRolloutRepository(session),
        rollout_observation_repository=ReflectionProposalRolloutObservationRepository(session),
        rollout_decision_repository=ReflectionProposalRolloutDecisionRepository(session),
        goal_repository=LearnerGoalRepository(session),
        study_plan_repository=StudyPlanRepository(session),
        plan_stage_repository=PlanStageRepository(session),
        daily_task_repository=DailyTaskRepository(session),
        workflow_run_repository=WorkflowRunRepository(session),
        goal_autonomy_state_repository=GoalAutonomyStateRepository(session),
        session_repository=SessionRepository(session),
        message_repository=SessionMessageRepository(session),
        reflection_record_repository=ReflectionRecordRepository(session),
        reflection_evidence_repository=ReflectionEvidenceSignalRepository(session),
        task_attempt_repository=TaskAttemptRepository(session),
        planner_service=get_planner_service(session),
        workflow_run_service=get_workflow_run_service(session),
        observation_scheduler=get_reflection_proposal_rollout_observation_scheduler(session),
        goal_skill_binding_repository=GoalSkillBindingRepository(session),
        audit_service=get_audit_service(session),
    )


def get_task_service(session: AsyncSession) -> AutonomousTaskService:
    audit_service = get_audit_service(session)
    tool_registry = InternalToolRegistry(audit_service=audit_service)
    settings = get_settings()
    if settings.external_http_tools_enabled:
        tool_registry.register(
            HttpToolSpec(
                name="external_progress_ping",
                description="Allowlisted external progress callback placeholder.",
                risk_level="medium",
                url="http://127.0.0.1:9/progress",
                timeout_seconds=settings.external_http_tool_timeout_seconds,
                allowed_statuses=(200, 202),
                enabled=False,
            )
        )
    return AutonomousTaskService(
        db_session=session,
        goal_repository=LearnerGoalRepository(session),
        study_plan_repository=StudyPlanRepository(session),
        plan_stage_repository=PlanStageRepository(session),
        daily_task_repository=DailyTaskRepository(session),
        workflow_run_repository=WorkflowRunRepository(session),
        goal_autonomy_state_repository=GoalAutonomyStateRepository(session),
        autonomy_job_repository=ScheduledAutonomyJobRepository(session),
        learner_availability_repository=LearnerAvailabilityRepository(session),
        learner_topic_mastery_repository=LearnerTopicMasteryRepository(session),
        task_attempt_repository=TaskAttemptRepository(session),
        planner_service=get_planner_service(session),
        workflow_run_service=get_workflow_run_service(session),
        session_service=get_session_service(session),
        chat_service=get_chat_service(session),
        quiz_service=get_quiz_service(session),
        autonomy_job_service=get_autonomy_job_service(session),
        reflection_service=get_reflection_service(session),
        reflection_evidence_service=get_reflection_evidence_service(session),
        reflection_outcome_service=get_reflection_outcome_service(session),
        reflection_proposal_sandbox_service=get_reflection_proposal_sandbox_service(session),
        reflection_proposal_rollout_service=get_reflection_proposal_rollout_service(session),
        rollout_resolver=get_reflection_proposal_rollout_resolver(session),
        rollout_observation_scheduler=get_reflection_proposal_rollout_observation_scheduler(session),
        goal_skill_binding_resolver=get_goal_skill_binding_resolver(session),
        strategy_card_service=get_strategy_card_service(session),
        reflective_memory_service=get_reflective_memory_service(session),
        memory_service=get_memory_service(session),
        long_term_memory_materialization_service=get_long_term_memory_materialization_service(session),
        long_term_memory_replay_executor=get_long_term_memory_materialization_replay_executor(session),
        internal_tool_registry=tool_registry,
        skill_usage_service=get_skill_usage_service(session),
        audit_service=audit_service,
    )


def get_workspace_service(session: AsyncSession) -> WorkspaceService:
    return WorkspaceService(
        learner_profile_repository=LearnerProfileRepository(session),
        learner_goal_repository=LearnerGoalRepository(session),
        study_plan_repository=StudyPlanRepository(session),
        session_repository=SessionRepository(session),
        workflow_run_repository=WorkflowRunRepository(session),
        goal_autonomy_state_repository=GoalAutonomyStateRepository(session),
        task_service=get_task_service(session),
        memory_service=get_memory_service(session),
    )
