"""Quiz attempt submission orchestration.

Coordinates session/quiz/question ownership validation, grading via
``AnswerGradingService``, attempt persistence, required audit, best-effort
skill usage recording, and long-term memory materialisation (Phase 4).
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.quiz_grading import (
    AnswerGradingService,
    GradingResult,
)
from agent_core.application.services.skill import SkillUsageService
from agent_core.domain.entities.session.quiz import (
    RECOMMENDED_NEXT_ACTIONS,
    SessionQuizAnswerAttempt,
)
from agent_core.domain.errors import NotFoundError, ValidationError
from agent_core.domain.schemas.quiz import (
    AnswerAttemptResponse,
    GradingFeedback,
    MasterySnapshotResponse,
    QuizQuestion,
)
from agent_core.infrastructure.db.repositories.learner import (
    LearnerTopicMasteryRepository,
)
from agent_core.infrastructure.db.repositories.quiz_answer_attempt import (
    SessionQuizAnswerAttemptRepository,
)
from agent_core.infrastructure.db.repositories.session import (
    SessionQuizRepository,
    SessionRepository,
)
from agent_core.application.services.long_term_memory_materialization import (
    LongTermMemoryMaterializationService,
)
from agent_core.application.services.long_term_memory_materialization_replay import (
    LongTermMemoryMaterializationReplayScheduler,
    LongTermMemoryReplayScheduleResult,
)
from agent_core.infrastructure.observability.metrics import (
    observe_long_term_memory_materialization,
    observe_reflection_evidence_derivation,
)
from agent_core.application.services.reflection_evidence import ReflectionEvidenceService
from agent_core.application.services.reflection import ReflectionTriggerRequest

# Signal codes that warrant immediate reflection triggering
_SIGNAL_TO_TRIGGER_SOURCE = {
    "repeated_misconception": "repeated_misconception",
    "hint_after_wrong_answer": "hint_dependency_failure",
    "low_mastery_high_difficulty_mismatch": "low_mastery_high_difficulty_mismatch",
    "assessment_regression_from_quiz": "assessment_regression_from_quiz",
    "quiz_strategy_failure": "high_failure_rate_artifact",
}

_LOGGER = logging.getLogger(__name__)


class _RecommendedNextActionPolicy:
    """Pure-function rule engine for Phase 1 recommended_next_action.

    This is a placeholder policy that relies on score, hint usage, and
    attempt count. Phase 3 will replace it with the AdaptiveQuizPolicy.
    """

    @staticmethod
    def decide(
        *,
        score: float | None,
        is_correct: bool | None,
        hint_used: bool,
        hint_count: int,
        attempt_number: int,
        grading_status: str,
    ) -> str:
        if grading_status != "graded":
            action = "request_review"
        elif is_correct is False and attempt_number >= 3:
            action = "easier_question"
        elif is_correct is False and hint_count >= 2:
            action = "request_hint"
        elif is_correct is True and hint_used:
            action = "review"
        elif is_correct is True and score is not None and score >= 0.8:
            action = "continue"
        else:
            action = "review"
        if action not in RECOMMENDED_NEXT_ACTIONS:
            return "review"
        return action


class QuizAttemptService:
    def __init__(
        self,
        *,
        db_session: AsyncSession,
        audit_service: AuditService,
        session_repository: SessionRepository,
        quiz_repository: SessionQuizRepository,
        attempt_repository: SessionQuizAnswerAttemptRepository,
        grading_service: AnswerGradingService,
        topic_mastery_repository: LearnerTopicMasteryRepository,
        skill_usage_service: SkillUsageService | None = None,
        materialization_service: LongTermMemoryMaterializationService | None = None,
        long_term_memory_replay_scheduler: LongTermMemoryMaterializationReplayScheduler | None = None,
        reflection_evidence_service: ReflectionEvidenceService | None = None,
        reflection_service: Any | None = None,
    ) -> None:
        self._db_session = db_session
        self._audit_service = audit_service
        self._session_repository = session_repository
        self._quiz_repository = quiz_repository
        self._attempt_repository = attempt_repository
        self._grading_service = grading_service
        self._topic_mastery_repository = topic_mastery_repository
        self._skill_usage_service = skill_usage_service
        self._materialization_service = materialization_service
        self._long_term_memory_replay_scheduler = long_term_memory_replay_scheduler
        self._reflection_evidence_service = reflection_evidence_service
        self._reflection_service = reflection_service

    async def submit_attempt(
        self,
        *,
        session_id: str,
        quiz_id: str,
        question_id: str,
        learner_answer: str,
        hint_used: bool,
        hint_count: int,
        client_context: dict[str, Any] | None = None,
        grading_strategy: str = "hybrid",
        commit: bool = True,
    ) -> AnswerAttemptResponse:
        session = await self._session_repository.get_by_id(session_id)
        if session is None:
            raise NotFoundError(f"Learning session '{session_id}' was not found.")

        try:
            stored_quiz = await self._quiz_repository.get_quiz_with_questions(
                session_id=session_id, quiz_id=quiz_id
            )
        except NotFoundError:
            raise NotFoundError(
                f"Quiz '{quiz_id}' was not found in session '{session_id}'."
            )

        question: QuizQuestion | None = None
        question_entity_id: str | None = None
        for quiz_question in stored_quiz.questions:
            candidate_id = self._match_question_id(quiz_question, question_id)
            if candidate_id is not None:
                question = quiz_question
                question_entity_id = candidate_id
                break
        if question is None or question_entity_id is None:
            raise NotFoundError(
                f"Question '{question_id}' was not found in quiz '{quiz_id}'."
            )

        learner_profile_id = session.learner_profile_id
        learner_goal_id = session.learner_goal_id
        daily_task_id = session.daily_task_id
        topic_key = session.subject or stored_quiz.quiz.topic
        subskill_keys = list(stored_quiz.quiz.skill_trace)

        last_attempt = await self._attempt_repository.get_last_by_question(
            question_entity_id
        )
        attempt_number = (last_attempt.attempt_number if last_attempt else 0) + 1

        grading_result = await self._safe_grade(
            question=question,
            learner_answer=learner_answer,
            strategy=grading_strategy,
        )

        attempt = SessionQuizAnswerAttempt.build(
            session_id=session_id,
            quiz_id=quiz_id,
            question_id=question_entity_id,
            learner_profile_id=learner_profile_id,
            learner_goal_id=learner_goal_id,
            daily_task_id=daily_task_id,
            topic_key=topic_key,
            subskill_keys=subskill_keys,
            question_prompt=question.prompt,
            reference_answer=question.answer,
            learner_answer=learner_answer,
            grading_status=grading_result.grading_status,
            grading_source=grading_result.grading_source,
            score=grading_result.score,
            is_correct=grading_result.is_correct,
            confidence=grading_result.confidence,
            rubric_feedback=grading_result.rubric_feedback,
            misconception_codes=list(grading_result.misconception_codes),
            hint_used=hint_used,
            hint_count=hint_count,
            attempt_number=attempt_number,
            metadata={"client_context": client_context} if client_context else {},
        )
        await self._attempt_repository.create(attempt)

        await self._audit_service.record(
            event_type=self._audit_event_type(grading_result),
            resource_type="learning_session",
            resource_id=session_id,
            actor=f"learner:{learner_profile_id}",
            event_data={
                "attempt_id": attempt.id,
                "quiz_id": quiz_id,
                "question_id": question_entity_id,
                "grading_status": grading_result.grading_status,
                "grading_source": grading_result.grading_source,
                "score": grading_result.score,
                "is_correct": grading_result.is_correct,
                "hint_used": hint_used,
                "hint_count": hint_count,
                "attempt_number": attempt_number,
                "validation_error": grading_result.validation_error,
            },
        )

        await self._record_skill_usage(
            attempt=attempt,
            grading_result=grading_result,
            topic_key=topic_key,
            hint_used=hint_used,
            hint_count=hint_count,
        )

        if commit:
            try:
                await self._db_session.commit()
            except Exception:
                await self._db_session.rollback()
                raise

        # Derive Reflection Evidence Signals
        if self._reflection_evidence_service is not None:
            signals = []
            try:
                begin_nested = getattr(self._db_session, "begin_nested", None)
                if begin_nested is None:
                    signals = await self._reflection_evidence_service.derive_from_answer_attempt(
                        attempt=attempt,
                    )
                else:
                    async with begin_nested():
                        signals = await self._reflection_evidence_service.derive_from_answer_attempt(
                            attempt=attempt,
                        )
            except Exception:
                _LOGGER.exception("Failed to derive reflection evidence signals from answer attempt; continuing")
                observe_reflection_evidence_derivation(
                    source_type="quiz_answer_attempt",
                    status="failed",
                )

            # Bridge: trigger reflections for signals that warrant it
            if signals and self._reflection_service is not None and attempt.learner_goal_id is not None:
                triggered_sources = set()
                for signal in signals:
                    trigger_source = _SIGNAL_TO_TRIGGER_SOURCE.get(signal.signal_code)
                    if trigger_source and trigger_source not in triggered_sources:
                        triggered_sources.add(trigger_source)
                        try:
                            req = ReflectionTriggerRequest(
                                learner_profile_id=attempt.learner_profile_id,
                                learner_goal_id=attempt.learner_goal_id,
                                scope="task",
                                target_type="learner_goal",
                                target_id=attempt.learner_goal_id,
                                trigger_source=trigger_source,
                                reflection_depth=1,
                                topic_focus=attempt.topic_key,
                            )
                            await self._reflection_service.trigger_reflection(req)
                        except Exception:
                            _LOGGER.exception(
                                "Failed to trigger reflection for signal=%s trigger=%s; continuing",
                                signal.signal_code,
                                trigger_source,
                            )

        # Phase 4: Long-Term Memory Materialization from Quiz Attempt
        if self._materialization_service is not None:
            try:
                begin_nested = getattr(self._db_session, "begin_nested", None)
                if begin_nested is None:
                    await self._materialization_service.materialize_from_answer_attempt(
                        attempt=attempt,
                        persist_embeddings=True,
                    )
                else:
                    async with begin_nested():
                        await self._materialization_service.materialize_from_answer_attempt(
                            attempt=attempt,
                            persist_embeddings=True,
                        )
            except Exception as exc:
                _LOGGER.exception("Failed to materialize memory candidate from quiz attempt.")
                observe_long_term_memory_materialization(
                    source_type="quiz_answer_attempt",
                    status="failed",
                    reason_code=type(exc).__name__,
                )
                replay = await self._schedule_quiz_materialization_replay(attempt=attempt)
                event_data = {
                    "source_type": "quiz_answer_attempt",
                    "learner_profile_id": learner_profile_id,
                    "learner_goal_id": learner_goal_id,
                    "attempt_id": attempt.id,
                    "quiz_id": quiz_id,
                    "question_id": question_entity_id,
                    "error_code": type(exc).__name__,
                    "error": str(exc),
                }
                event_data.update(replay.audit_payload())
                try:
                    await self._audit_service.record_durable(
                        event_type="long_term_memory.materialization.failed",
                        resource_type="quiz_answer_attempt",
                        resource_id=attempt.id,
                        actor="system",
                        event_data=event_data,
                    )
                except Exception:
                    _LOGGER.exception(
                        "Failed to record durable audit for materialization failure (attempt=%s); "
                        "attempt is already committed, suppressing audit-write error.",
                        attempt.id,
                    )

        mastery_snapshot = await self._load_mastery_snapshot(
            learner_goal_id=learner_goal_id, topic_key=topic_key
        )

        recommended_action = _RecommendedNextActionPolicy.decide(
            score=grading_result.score,
            is_correct=grading_result.is_correct,
            hint_used=hint_used,
            hint_count=hint_count,
            attempt_number=attempt_number,
            grading_status=grading_result.grading_status,
        )

        return AnswerAttemptResponse(
            attempt_id=attempt.id,
            session_id=session_id,
            quiz_id=quiz_id,
            question_id=question_entity_id,
            attempt_number=attempt_number,
            grading=GradingFeedback(
                grading_status=grading_result.grading_status,
                grading_source=grading_result.grading_source,
                score=grading_result.score,
                is_correct=grading_result.is_correct,
                confidence=grading_result.confidence,
                rubric_feedback=grading_result.rubric_feedback,
                misconception_codes=list(grading_result.misconception_codes),
                needs_human_review=grading_result.needs_human_review,
            ),
            mastery_snapshot=mastery_snapshot,
            recommended_next_action=recommended_action,
            created_at=attempt.created_at,
        )

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    async def _safe_grade(
        self,
        *,
        question: QuizQuestion,
        learner_answer: str,
        strategy: str,
    ) -> GradingResult:
        try:
            return await self._grading_service.grade(
                question_prompt=question.prompt,
                reference_answer=question.answer,
                question_type=question.question_type,
                options=question.options,
                learner_answer=learner_answer,
                strategy=strategy,
            )
        except Exception as exc:
            _LOGGER.exception("grading service failure; recording rejected attempt")
            return GradingResult(
                grading_status="rejected",
                grading_source=None,
                score=None,
                is_correct=None,
                confidence=None,
                rubric_feedback=None,
                misconception_codes=(),
                reasoning_quality=None,
                needs_human_review=True,
                validation_error=f"grading_service_failure:{type(exc).__name__}",
            )

    async def _record_skill_usage(
        self,
        *,
        attempt: SessionQuizAnswerAttempt,
        grading_result: GradingResult,
        topic_key: str,
        hint_used: bool,
        hint_count: int,
    ) -> None:
        if self._skill_usage_service is None:
            return
        if grading_result.grading_status == "graded":
            outcome_status = "completed" if grading_result.is_correct else "failed"
        elif grading_result.grading_status == "needs_review":
            outcome_status = "aborted"
        else:
            outcome_status = "aborted"
        try:
            await self._skill_usage_service.record_usage(
                skill_name="quiz.answer_submission",
                surface="quiz",
                outcome_status=outcome_status,
                learner_profile_id=attempt.learner_profile_id,
                learner_goal_id=attempt.learner_goal_id,
                session_id=attempt.session_id,
                daily_task_id=attempt.daily_task_id,
                topic_key=topic_key,
                trigger_source="quiz_attempt",
                outcome_signals={
                    "confidence": grading_result.confidence,
                }
                if grading_result.confidence is not None
                else None,
                metadata={
                    "grading_status": grading_result.grading_status,
                    "grading_source": grading_result.grading_source,
                    "score": grading_result.score,
                    "is_correct": grading_result.is_correct,
                    "hint_used": hint_used,
                    "hint_count": hint_count,
                    "attempt_number": attempt.attempt_number,
                    "attempt_id": attempt.id,
                },
            )
        except Exception:
            _LOGGER.exception(
                "skill usage record failed for attempt %s; continuing", attempt.id
            )

    async def _load_mastery_snapshot(
        self,
        *,
        learner_goal_id: str | None,
        topic_key: str,
    ) -> MasterySnapshotResponse | None:
        if learner_goal_id is None:
            return None
        mastery = await self._topic_mastery_repository.get_by_goal_and_topic(
            learner_goal_id=learner_goal_id, topic_key=topic_key
        )
        if mastery is None:
            return None
        return MasterySnapshotResponse(
            topic_key=mastery.topic_key,
            mastery_score=mastery.mastery_score,
            confidence=mastery.confidence,
            evidence_count=mastery.evidence_count,
            last_attempt_status=mastery.last_attempt_status,
            last_assessed_at=mastery.last_assessed_at,
        )

    @staticmethod
    def _match_question_id(question: QuizQuestion, question_id: str) -> str | None:
        if question.id == question_id:
            return question_id
        return None

    @staticmethod
    def _audit_event_type(grading_result: GradingResult) -> str:
        if grading_result.grading_status == "graded":
            return "quiz.answer_attempt.submitted"
        if grading_result.grading_status == "needs_review":
            return "quiz.answer_attempt.needs_review"
        return "quiz.answer_attempt.rejected"

    async def _schedule_quiz_materialization_replay(
        self,
        *,
        attempt: SessionQuizAnswerAttempt,
    ) -> LongTermMemoryReplayScheduleResult:
        try:
            if self._long_term_memory_replay_scheduler is not None:
                return await self._long_term_memory_replay_scheduler.schedule_quiz_answer_attempt(
                    learner_goal_id=attempt.learner_goal_id,
                    attempt_id=attempt.id,
                )
        except Exception as replay_exc:
            return LongTermMemoryReplayScheduleResult(
                enqueued=False,
                job_id=None,
                idempotency_key=f"ltm-replay:quiz_answer_attempt:{attempt.id}",
                due_at=None,
                skip_reason="replay_enqueue_failed",
                error_code=type(replay_exc).__name__,
                error=str(replay_exc),
            )
        return LongTermMemoryReplayScheduleResult(
            enqueued=False,
            job_id=None,
            idempotency_key=f"ltm-replay:quiz_answer_attempt:{attempt.id}",
            due_at=None,
            skip_reason="replay_scheduler_unconfigured",
        )
