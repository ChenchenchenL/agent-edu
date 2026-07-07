from sqlalchemy.ext.asyncio import AsyncSession
import logging

from agent_core.application.services.audit import AuditService
from agent_core.application.services.dynamic_runtime_registry import (
    DynamicRuntimeRegistryService,
    RuntimeSkillExecutionPlan,
)
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding, GoalSkillBindingResolver
from agent_core.application.services.reflection_proposal_rollout_observation_scheduler import (
    ReflectionProposalRolloutObservationScheduler,
)
from agent_core.application.services.skill.capability import CapabilityRequest
from agent_core.application.services.skills import SkillUsageService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.quiz import SessionQuiz, SessionQuizQuestion
from agent_core.domain.entities.session import LearningSession
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.quiz import (
    GenerateQuizRequest,
    QuizDetailResponse,
    QuizDraftResponse,
    QuizSummaryResponse,
)
from agent_core.infrastructure.db.repositories import (
    SessionQuizRepository,
    SessionRepository,
    LearnerTopicMasteryRepository,
    SessionQuizAnswerAttemptRepository,
    LearnerGoalStrategyCardRepository,
)
from agent_core.infrastructure.llm.types import LLMProvider
from agent_core.infrastructure.observability.metrics import observe_llm_operation
from agent_core.application.services.adaptive_quiz_policy import AdaptiveQuizPolicyService
from agent_core.application.services.memory import MemoryService

_LOGGER = logging.getLogger(__name__)


class QuizService:
    def __init__(
        self,
        *,
        db_session: AsyncSession,
        audit_service: AuditService,
        session_repository: SessionRepository,
        quiz_repository: SessionQuizRepository,
        llm_provider: LLMProvider,
        skill_registry: SkillRegistry,
        goal_skill_binding_resolver: GoalSkillBindingResolver | None = None,
        rollout_observation_scheduler: ReflectionProposalRolloutObservationScheduler | None = None,
        skill_usage_service: SkillUsageService | None = None,
        runtime_registry: DynamicRuntimeRegistryService | None = None,
        adaptive_policy_service: AdaptiveQuizPolicyService | None = None,
        memory_service: MemoryService | None = None,
    ) -> None:
        self._db_session = db_session
        self._audit_service = audit_service
        self._session_repository = session_repository
        self._quiz_repository = quiz_repository
        self._llm_provider = llm_provider
        self._skill_registry = skill_registry
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._rollout_observation_scheduler = rollout_observation_scheduler
        self._skill_usage_service = skill_usage_service
        self._runtime_registry = runtime_registry
        self._adaptive_policy_service = adaptive_policy_service or AdaptiveQuizPolicyService()
        self._memory_service = memory_service

    async def generate_quiz(self, payload: GenerateQuizRequest, *, commit: bool = True) -> QuizDraftResponse:
        if payload.session_id is None:
            raise ValidationError("session_id is required for quiz generation.")

        session = await self._session_repository.get_by_id(payload.session_id)
        if session is None:
            raise NotFoundError(f"Session '{payload.session_id}' was not found.")
        skills = self._skill_registry.trace_for_mode("quiz")
        skill_binding = None
        if self._goal_skill_binding_resolver is not None and session.learner_goal_id is not None:
            skill_binding = await self._goal_skill_binding_resolver.get_active_binding(
                learner_goal_id=session.learner_goal_id,
                surface="quiz",
                topic_key=payload.topic,
                trigger_source="quiz_generation",
                include_staged=False,
            )
        runtime_plan = await self._resolve_runtime_plan(
            learner_goal_id=session.learner_goal_id,
            skill_name=skills[0],
            surface="quiz",
            resource_id=session.id,
            topic_key=payload.topic,
            trigger_source="quiz_generation",
        )
        skill_execution_plan = runtime_plan.plan if runtime_plan is not None else await self._resolve_skill_execution_plan(
            skill_name=skills[0],
            surface="quiz",
            resource_id=session.id,
            skill_binding=skill_binding,
        )
        skill_resolution = skill_execution_plan.resolution if skill_execution_plan is not None else await self._resolve_skill_for_runtime(
            skill_name=skills[0],
            surface="quiz",
            resource_id=session.id,
        )

        current_mastery = None
        recent_attempts = []
        active_strategy_card = None
        ltm_interpretation = None

        if session.learner_goal_id is not None:
            try:
                mastery_repo = LearnerTopicMasteryRepository(self._db_session)
                current_mastery = await mastery_repo.get_by_goal_and_topic(
                    learner_goal_id=session.learner_goal_id, topic_key=payload.topic
                )
            except Exception:
                _LOGGER.warning(
                    "Failed to fetch learner topic mastery for goal=%s topic=%s, proceeding without mastery data.",
                    session.learner_goal_id,
                    payload.topic,
                    exc_info=True,
                )

            try:
                attempt_repo = SessionQuizAnswerAttemptRepository(self._db_session)
                recent_attempts = await attempt_repo.list_recent_by_goal_topic(
                    learner_goal_id=session.learner_goal_id, topic_key=payload.topic, limit=20
                )
            except Exception:
                _LOGGER.warning(
                    "Failed to fetch recent quiz attempts for goal=%s topic=%s, proceeding without attempt history.",
                    session.learner_goal_id,
                    payload.topic,
                    exc_info=True,
                )

            try:
                strategy_repo = LearnerGoalStrategyCardRepository(self._db_session)
                active_strategy_card = await strategy_repo.get_active_by_goal(session.learner_goal_id)
            except Exception:
                _LOGGER.warning(
                    "Failed to fetch active strategy card for goal=%s, proceeding without strategy bias.",
                    session.learner_goal_id,
                    exc_info=True,
                )

            if self._memory_service is not None:
                try:
                    interpretation = await self._memory_service.build_interpretation(
                        learner_profile_id=session.learner_profile_id,
                        learner_goal_id=session.learner_goal_id,
                    )
                    facts = [f.summary for f in interpretation.facts]
                    behaviors = [b.summary for b in interpretation.behavior_patterns]
                    ltm_interpretation = "; ".join(facts + behaviors) if (facts or behaviors) else None
                except Exception:
                    _LOGGER.exception("Failed to build memory interpretation, proceeding without it.")

        runtime_directives = (
            dict(skill_execution_plan.runtime_directives)
            if skill_execution_plan is not None
            else dict(skill_binding.runtime_directives) if skill_binding is not None else {}
        )

        # Resolve adaptive policy
        policy_output = self._adaptive_policy_service.resolve_policy(
            learner_profile_id=session.learner_profile_id,
            learner_goal_id=session.learner_goal_id,
            session_id=session.id,
            topic_key=payload.topic,
            requested_difficulty=payload.difficulty,
            requested_question_count=payload.question_count,
            current_mastery=current_mastery,
            recent_attempts=recent_attempts,
            active_strategy_card=active_strategy_card,
            long_term_memory_interpretation=ltm_interpretation,
            runtime_directives=runtime_directives,
        )

        directives_list: list[str] = []
        if policy_output.skill_directives:
            for k, v in policy_output.skill_directives.items():
                if k == "directives" and isinstance(v, list):
                    directives_list.extend(str(item) for item in v)
                elif isinstance(v, bool):
                    if v:
                        directives_list.append(f"{k}: true")
                elif isinstance(v, list):
                    directives_list.append(f"{k}: {', '.join(str(i) for i in v)}")
                else:
                    directives_list.append(f"{k}: {v}")

        quiz = None
        session_quiz = None
        try:
            quiz = await self._llm_provider.generate_quiz_draft(
                topic=payload.topic,
                difficulty=policy_output.effective_difficulty,
                question_count=policy_output.question_count,
                skill_directives=directives_list or None,
                feedback_style=policy_output.feedback_style,
            )
            session_quiz = SessionQuiz.build(
                session_id=session.id,
                topic=quiz.topic,
                difficulty=quiz.difficulty,
                question_count=len(quiz.questions),
                skill_trace=skills,
            )
            quiz_questions = [
                SessionQuizQuestion.build(
                    quiz_id=session_quiz.id,
                    position=index + 1,
                    prompt=item.prompt,
                    answer=item.answer,
                )
                for index, item in enumerate(quiz.questions)
            ]
            await self._quiz_repository.create_quiz(session_quiz)
            await self._quiz_repository.create_questions(quiz_questions)
            await self._audit_service.record(
                event_type="llm.quiz.completed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "provider": quiz.provider,
                    "model": quiz.model,
                    "operation": "quiz",
                    "status": "completed",
                    "latency_ms": quiz.latency_ms,
                    "retry_count": quiz.retry_count,
                    "session_id": session.id,
                    "quiz_id": session_quiz.id,
                    "response_shape_valid": quiz.response_shape_valid,
                    "usage": None,
                },
            )
            await self._audit_service.record(
                event_type="quiz.generated",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "topic": payload.topic,
                    "question_count": len(quiz.questions),
                    "session_id": session.id,
                    "quiz_id": session_quiz.id,
                    "adaptation_rationale": policy_output.adaptation_rationale,
                },
            )
            observe_llm_operation(
                operation="quiz",
                provider=quiz.provider,
                status="completed",
                latency_ms=quiz.latency_ms,
            )
            await self._record_skill_usage(
                session=session,
                topic=payload.topic,
                outcome_status="completed",
                latency_ms=quiz.latency_ms,
                input_summary=payload.topic,
                output_summary=f"{len(quiz.questions)} questions",
                resolution=skill_resolution,
                metadata=self._build_usage_metadata(
                    base_metadata={
                        "quiz_id": session_quiz.id,
                        "difficulty": quiz.difficulty,
                        "question_count": len(quiz.questions),
                        "response_shape_valid": quiz.response_shape_valid,
                        "retry_count": quiz.retry_count,
                        "provider": quiz.provider,
                        "model": quiz.model,
                        "adaptation_rationale": policy_output.adaptation_rationale,
                    },
                    execution_plan=skill_execution_plan,
                    runtime_plan=runtime_plan,
                ),
            )
            if session.learner_goal_id is not None:
                await self._schedule_surface_rollout_observation(
                    learner_goal_id=session.learner_goal_id,
                    surface="quiz",
                    trigger_source="quiz_generation",
                    source_ref=session_quiz.id,
                )
            if commit:
                await self._db_session.commit()
        except Exception as exc:
            observe_llm_operation(
                operation="quiz",
                provider=getattr(self._llm_provider, "provider_name", "unknown"),
                status="failed",
                latency_ms=getattr(quiz, "latency_ms", 0) if quiz is not None else 0,
            )
            await self._audit_service.record_durable(
                event_type="llm.quiz.failed",
                resource_type="learning_session",
                resource_id=session.id,
                actor="system",
                event_data={
                    "provider": getattr(self._llm_provider, "provider_name", "unknown"),
                    "model": getattr(self._llm_provider, "model_name", None),
                    "operation": "quiz",
                    "status": "failed",
                    "latency_ms": getattr(quiz, "latency_ms", 0) if quiz is not None else 0,
                    "retry_count": getattr(quiz, "retry_count", 0) if quiz is not None else 0,
                    "session_id": session.id,
                    "quiz_id": session_quiz.id if session_quiz is not None else None,
                    "response_shape_valid": getattr(quiz, "response_shape_valid", False) if quiz is not None else False,
                    "usage": None,
                },
            )
            await self._db_session.rollback()
            await self._record_skill_usage(
                session=session,
                topic=payload.topic,
                outcome_status="failed",
                latency_ms=getattr(quiz, "latency_ms", 0) if quiz is not None else 0,
                input_summary=payload.topic,
                error_code=type(exc).__name__,
                resolution=skill_resolution,
                metadata=self._build_usage_metadata(
                    base_metadata={
                        "quiz_id": session_quiz.id if session_quiz is not None else None,
                        "difficulty": payload.difficulty,
                        "question_count": payload.question_count,
                        "adaptation_rationale": policy_output.adaptation_rationale,
                    },
                    execution_plan=skill_execution_plan,
                    runtime_plan=runtime_plan,
                ),
            )
            if commit:
                await self._db_session.commit()
            raise
        return QuizDraftResponse(
            quiz_id=session_quiz.id,
            session_id=session.id,
            topic=quiz.topic,
            difficulty=quiz.difficulty,
            question_count=len(quiz.questions),
            questions=quiz.questions,
            skill_trace=skills,
            created_at=session_quiz.created_at,
        )

    async def list_quizzes(self, session_id: str) -> list[QuizSummaryResponse]:
        session = await self._session_repository.get_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Session '{session_id}' was not found.")

        quizzes = await self._quiz_repository.list_by_session(session_id)
        return [
            QuizSummaryResponse(
                quiz_id=item.id,
                session_id=item.session_id,
                topic=item.topic,
                difficulty=item.difficulty,
                question_count=item.question_count,
                skill_trace=item.skill_trace,
                created_at=item.created_at,
            )
            for item in quizzes
        ]

    async def get_quiz(self, *, session_id: str, quiz_id: str) -> QuizDetailResponse:
        stored = await self._quiz_repository.get_quiz_with_questions(session_id=session_id, quiz_id=quiz_id)
        return QuizDetailResponse(
            quiz_id=stored.quiz.id,
            session_id=stored.quiz.session_id,
            topic=stored.quiz.topic,
            difficulty=stored.quiz.difficulty,
            question_count=stored.quiz.question_count,
            questions=stored.questions,
            skill_trace=stored.quiz.skill_trace,
            created_at=stored.quiz.created_at,
        )

    async def _resolve_skill_for_runtime(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str,
    ) -> SkillResolution | None:
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_for_runtime(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
        )

    async def _resolve_skill_execution_plan(
        self,
        *,
        skill_name: str,
        surface: str,
        resource_id: str,
        skill_binding: ActiveGoalSkillBinding | None,
    ) -> SkillExecutionPlan | None:
        if self._skill_usage_service is None:
            return None
        return await self._skill_usage_service.resolve_execution_plan(
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            skill_binding=skill_binding,
        )

    async def _resolve_runtime_plan(
        self,
        *,
        learner_goal_id: str | None,
        skill_name: str,
        surface: str,
        resource_id: str,
        topic_key: str | None,
        trigger_source: str | None,
    ) -> RuntimeSkillExecutionPlan | None:
        if self._runtime_registry is None:
            return None
        surface_to_capability = {"quiz": "assessment.generate"}
        capability = surface_to_capability.get(surface)
        if capability is not None:
            request = CapabilityRequest(
                capability=capability,
                surface=surface,
                learner_goal_id=learner_goal_id,
                topic_key=topic_key,
                trigger_source=trigger_source,
            )
            result = await self._runtime_registry.resolve_capability_request(
                request,
                resource_id=resource_id,
            )
            if result is not None:
                return result.plan
        return await self._runtime_registry.resolve_runtime_plan(
            learner_goal_id=learner_goal_id,
            skill_name=skill_name,
            surface=surface,
            resource_id=resource_id,
            topic_key=topic_key,
            trigger_source=trigger_source,
            include_staged=False,
        )

    async def _record_skill_usage(
        self,
        *,
        session: LearningSession,
        topic: str,
        outcome_status: str,
        latency_ms: int | None,
        input_summary: str | None,
        output_summary: str | None = None,
        error_code: str | None = None,
        resolution: SkillResolution | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        if self._skill_usage_service is None:
            return
        await self._skill_usage_service.record_usage(
            skill_name="create_quiz",
            surface="quiz",
            outcome_status=outcome_status,
            learner_profile_id=session.learner_profile_id,
            learner_goal_id=session.learner_goal_id,
            session_id=session.id,
            daily_task_id=session.daily_task_id,
            topic_key=topic,
            trigger_source="quiz_generation",
            latency_ms=latency_ms,
            input_summary=input_summary,
            output_summary=output_summary,
            error_code=error_code,
            resolution=resolution,
            metadata=metadata,
        )

    async def _schedule_surface_rollout_observation(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> None:
        if self._rollout_observation_scheduler is None:
            return
        await self._rollout_observation_scheduler.schedule_active(
            learner_goal_id=learner_goal_id,
            surface=surface,
            trigger_source=trigger_source,
            source_ref=source_ref,
        )

    @staticmethod
    def _build_usage_metadata(
        *,
        base_metadata: dict[str, object],
        execution_plan: SkillExecutionPlan | None,
        runtime_plan: RuntimeSkillExecutionPlan | None = None,
    ) -> dict[str, object]:
        return DynamicRuntimeRegistryService.usage_metadata_for_plan(
            execution_plan=execution_plan,
            runtime_plan=runtime_plan,
            base_metadata=base_metadata,
        )
