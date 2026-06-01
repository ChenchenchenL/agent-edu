from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.goal_skill_binding_resolver import GoalSkillBindingResolver
from agent_core.application.services.skills import SkillUsageService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.quiz import SessionQuiz, SessionQuizQuestion
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.quiz import (
    GenerateQuizRequest,
    QuizDetailResponse,
    QuizDraftResponse,
    QuizSummaryResponse,
)
from agent_core.infrastructure.db.repositories import SessionQuizRepository, SessionRepository
from agent_core.infrastructure.llm.types import LLMProvider
from agent_core.infrastructure.observability.metrics import observe_llm_operation


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
        skill_usage_service: SkillUsageService | None = None,
    ) -> None:
        self._db_session = db_session
        self._audit_service = audit_service
        self._session_repository = session_repository
        self._quiz_repository = quiz_repository
        self._llm_provider = llm_provider
        self._skill_registry = skill_registry
        self._goal_skill_binding_resolver = goal_skill_binding_resolver
        self._skill_usage_service = skill_usage_service

    async def generate_quiz(self, payload: GenerateQuizRequest, *, commit: bool = True) -> QuizDraftResponse:
        if payload.session_id is None:
            raise ValidationError("session_id is required for quiz generation.")

        session = await self._session_repository.get_by_id(payload.session_id)
        if session is None:
            raise NotFoundError(f"Session '{payload.session_id}' was not found.")
        skill_binding = None
        if self._goal_skill_binding_resolver is not None and session.learner_goal_id is not None:
            skill_binding = await self._goal_skill_binding_resolver.get_active_binding(
                learner_goal_id=session.learner_goal_id,
                surface="quiz",
                topic_key=payload.topic,
                include_staged=True,
            )

        quiz = None
        session_quiz = None
        try:
            quiz = await self._llm_provider.generate_quiz_draft(
                topic=payload.topic,
                difficulty=payload.difficulty,
                question_count=int((skill_binding.runtime_directives.get("question_count") if skill_binding is not None else None) or payload.question_count),
                skill_directives=list(skill_binding.runtime_directives.get("skill_directives") or []) if skill_binding is not None else None,
                feedback_style=str(skill_binding.runtime_directives.get("feedback_style")) if skill_binding is not None and skill_binding.runtime_directives.get("feedback_style") else None,
            )
            session_quiz = SessionQuiz.build(
                session_id=session.id,
                topic=quiz.topic,
                difficulty=quiz.difficulty,
                question_count=len(quiz.questions),
                skill_trace=self._skill_registry.trace_for_mode("quiz"),
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
                    "question_count": payload.question_count,
                    "session_id": session.id,
                    "quiz_id": session_quiz.id,
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
                metadata={
                    "quiz_id": session_quiz.id,
                    "difficulty": quiz.difficulty,
                    "question_count": len(quiz.questions),
                    "response_shape_valid": quiz.response_shape_valid,
                    "retry_count": quiz.retry_count,
                    "provider": quiz.provider,
                    "model": quiz.model,
                },
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
                metadata={
                    "quiz_id": session_quiz.id if session_quiz is not None else None,
                    "difficulty": payload.difficulty,
                    "question_count": payload.question_count,
                },
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
            skill_trace=self._skill_registry.trace_for_mode("quiz"),
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

    async def _record_skill_usage(
        self,
        *,
        session,
        topic: str,
        outcome_status: str,
        latency_ms: int | None,
        input_summary: str | None,
        output_summary: str | None = None,
        error_code: str | None = None,
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
            metadata=metadata,
        )
