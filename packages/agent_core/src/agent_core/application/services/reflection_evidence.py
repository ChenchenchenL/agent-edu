from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.autonomy import TaskAttempt
from agent_core.domain.entities.memory import MemoryEvent
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.planning import DailyTask, WorkflowRun
from agent_core.domain.entities.reflection_v2 import ReflectionEvidenceSignal
from agent_core.domain.entities.session.quiz import SessionQuizAnswerAttempt
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    LearnerTopicMasteryRepository,
    MemoryEventRepository,
    ReflectionEvidenceSignalRepository,
    SessionMessageRepository,
    WorkflowRunRepository,
)
from agent_core.infrastructure.db.repositories.quiz_answer_attempt import SessionQuizAnswerAttemptRepository


class ReflectionEvidenceService:
    def __init__(
        self,
        *,
        repository: ReflectionEvidenceSignalRepository,
        message_repository: SessionMessageRepository | None,
        memory_event_repository: MemoryEventRepository,
        daily_task_repository: DailyTaskRepository,
        workflow_run_repository: WorkflowRunRepository,
        learner_topic_mastery_repository: LearnerTopicMasteryRepository | None,
        audit_service: AuditService,
        quiz_answer_attempt_repository: SessionQuizAnswerAttemptRepository | None = None,
    ) -> None:
        self._repository = repository
        self._message_repository = message_repository
        self._memory_event_repository = memory_event_repository
        self._daily_task_repository = daily_task_repository
        self._workflow_run_repository = workflow_run_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._audit_service = audit_service
        self._quiz_answer_attempt_repository = quiz_answer_attempt_repository

    async def derive_from_task(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str,
        task: DailyTask,
        attempt: TaskAttempt | None,
    ) -> list[ReflectionEvidenceSignal]:
        signals: list[ReflectionEvidenceSignal] = []
        if task.status == "skipped":
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    session_id=task.execution_session_id,
                    daily_task_id=task.id,
                    workflow_run_id=task.last_workflow_run_id,
                    source_type="task_attempt",
                    signal_code="repeated_skip_pattern",
                    topic_key=task.topic_focus,
                    severity_score=0.65,
                    confidence_score=0.8,
                    payload={"task_type": task.task_type, "result_note": task.result_note},
                )
            )
        if task.task_type == "assessment" and task.status in {"failed", "completed"}:
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    session_id=task.execution_session_id,
                    daily_task_id=task.id,
                    workflow_run_id=task.last_workflow_run_id,
                    source_type="task_attempt",
                    signal_code="assessment_regression",
                    topic_key=task.topic_focus,
                    severity_score=0.8 if task.status == "failed" else 0.55,
                    confidence_score=0.75,
                    payload={"task_status": task.status, "result_note": task.result_note},
                )
            )
        if attempt is not None and attempt.outcome_status == "failed":
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    session_id=task.execution_session_id,
                    daily_task_id=task.id,
                    workflow_run_id=task.last_workflow_run_id,
                    source_type="task_attempt",
                    signal_code="topic_failure_cluster",
                    topic_key=task.topic_focus,
                    severity_score=0.6,
                    confidence_score=0.7,
                    payload={"score": attempt.score, "task_type": attempt.task_type},
                )
            )
        return await self._persist(signals)

    async def derive_from_workflow(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str,
        workflow_run: WorkflowRun,
    ) -> list[ReflectionEvidenceSignal]:
        if workflow_run.error_code is None:
            return []
        signal_code = "workflow_runtime_failure"
        if "Provider" in workflow_run.error_code:
            signal_code = "workflow_provider_failure"
        elif "Validation" in workflow_run.error_code:
            signal_code = "workflow_validation_failure"
        signals = [
            ReflectionEvidenceSignal.build(
                learner_profile_id=learner_profile_id,
                learner_goal_id=learner_goal_id,
                session_id=None,
                daily_task_id=workflow_run.daily_task_id,
                workflow_run_id=workflow_run.id,
                source_type="workflow_run",
                signal_code=signal_code,
                topic_key=None,
                severity_score=0.9,
                confidence_score=0.95,
                payload={"workflow_type": workflow_run.workflow_type, "error_code": workflow_run.error_code},
            )
        ]
        return await self._persist(signals)

    async def derive_from_session_turn(
        self,
        *,
        learner_profile_id: str,
        learner_goal_id: str,
        session_id: str,
        turn_metrics: dict[str, object],
        learner_message: SessionMessage,
    ) -> list[ReflectionEvidenceSignal]:
        signals: list[ReflectionEvidenceSignal] = []
        hint_history_count = int(turn_metrics.get("hint_history_count") or 0)
        if hint_history_count >= 2:
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    session_id=session_id,
                    daily_task_id=None,
                    workflow_run_id=None,
                    source_type="session_turn",
                    signal_code="high_hint_dependency",
                    topic_key=None,
                    severity_score=0.7,
                    confidence_score=0.8,
                    payload={"hint_history_count": hint_history_count},
                )
            )
        if bool(turn_metrics.get("used_error_analysis")) and learner_message.content_payload is None:
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    session_id=session_id,
                    daily_task_id=None,
                    workflow_run_id=None,
                    source_type="session_turn",
                    signal_code="short_guess_answer",
                    topic_key=None,
                    severity_score=0.55,
                    confidence_score=0.65,
                    payload={"used_error_analysis": True},
                )
            )
        message_text = learner_message.content.casefold()
        confusion_keyword_count = sum(
            1 for token in ("confused", "stuck", "dont understand", "don't understand", "why", "how")
            if token in message_text
        )
        if confusion_keyword_count >= 2:
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=learner_profile_id,
                    learner_goal_id=learner_goal_id,
                    session_id=session_id,
                    daily_task_id=None,
                    workflow_run_id=None,
                    source_type="session_turn",
                    signal_code="repeat_confusion",
                    topic_key=None,
                    severity_score=0.62,
                    confidence_score=0.72,
                    payload={"confusion_keyword_count": confusion_keyword_count},
                )
            )
        return await self._persist(signals)

    async def aggregate_session_signals(self, *, session_id: str) -> dict[str, object]:
        messages = (
            await self._message_repository.list_history(session_id=session_id, limit=50, before_id=None)
            if self._message_repository is not None
            else []
        )
        events = await self._memory_event_repository.list_by_session(session_id, limit=50)
        signals = await self._repository.list_by_session(session_id, limit=20)
        user_messages = [item for item in messages if item.role == "user"]
        hint_turn_count = len([item for item in messages if item.mode == "hint"])
        struggle_event_count = len([item for item in events if item.struggle_note is not None])
        progress_event_count = len([item for item in events if item.progress_note is not None])
        confusion_keyword_count = 0
        direct_answer_request_count = 0
        short_retry_count = 0
        previous_content = ""
        for item in user_messages:
            lowered = item.content.casefold()
            confusion_keyword_count += sum(
                1 for token in ("confused", "stuck", "dont understand", "don't understand", "why", "how")
                if token in lowered
            )
            if any(token in lowered for token in ("just answer", "give answer", "tell me answer", "final answer")):
                direct_answer_request_count += 1
            if previous_content and len(item.content.strip()) <= 24:
                short_retry_count += 1
            previous_content = item.content
        return {
            "hint_turn_count": hint_turn_count,
            "struggle_event_count": struggle_event_count,
            "progress_event_count": progress_event_count,
            "confusion_keyword_count": confusion_keyword_count,
            "direct_answer_request_count": direct_answer_request_count,
            "short_retry_count": short_retry_count,
            "recent_signal_codes": [item.signal_code for item in signals[:6]],
        }

    async def _persist(self, signals: list[ReflectionEvidenceSignal]) -> list[ReflectionEvidenceSignal]:
        for signal in signals:
            await self._repository.create(signal)
            await self._audit_service.record(
                event_type="reflection.evidence.derived",
                resource_type="reflection_evidence_signal",
                resource_id=signal.id,
                actor="system",
                event_data={
                    "learner_goal_id": signal.learner_goal_id,
                    "signal_code": signal.signal_code,
                    "source_type": signal.source_type,
                },
            )
        return signals

    async def derive_from_answer_attempt(
        self,
        *,
        attempt: SessionQuizAnswerAttempt,
    ) -> list[ReflectionEvidenceSignal]:
        signals: list[ReflectionEvidenceSignal] = []
        if self._quiz_answer_attempt_repository is None or attempt.learner_goal_id is None:
            return signals

        # Fetch recent attempts on the same topic
        recent_attempts = await self._quiz_answer_attempt_repository.list_recent_by_goal_topic(
            learner_goal_id=attempt.learner_goal_id,
            topic_key=attempt.topic_key,
            limit=10,
        )

        # 1. repeated_misconception
        if attempt.misconception_codes:
            previous_misconceptions = []
            for prev in recent_attempts:
                if prev.id != attempt.id:
                    previous_misconceptions.extend(prev.misconception_codes)
            
            has_repeated = any(code in previous_misconceptions for code in attempt.misconception_codes)
            if has_repeated:
                signals.append(
                    ReflectionEvidenceSignal.build(
                        learner_profile_id=attempt.learner_profile_id,
                        learner_goal_id=attempt.learner_goal_id,
                        session_id=attempt.session_id,
                        daily_task_id=attempt.daily_task_id,
                        workflow_run_id=None,
                        source_type="quiz_answer_attempt",
                        signal_code="repeated_misconception",
                        topic_key=attempt.topic_key,
                        severity_score=0.75,
                        confidence_score=0.85,
                        payload={"misconception_codes": list(attempt.misconception_codes)},
                    )
                )

        # 2. hint_after_wrong_answer
        if attempt.hint_used and attempt.attempt_number > 1:
            prev_for_question = [
                a for a in recent_attempts
                if a.question_id == attempt.question_id and a.attempt_number < attempt.attempt_number
            ]
            if prev_for_question and not any(a.is_correct for a in prev_for_question):
                signals.append(
                    ReflectionEvidenceSignal.build(
                        learner_profile_id=attempt.learner_profile_id,
                        learner_goal_id=attempt.learner_goal_id,
                        session_id=attempt.session_id,
                        daily_task_id=attempt.daily_task_id,
                        workflow_run_id=None,
                        source_type="quiz_answer_attempt",
                        signal_code="hint_after_wrong_answer",
                        topic_key=attempt.topic_key,
                        severity_score=0.6,
                        confidence_score=0.8,
                        payload={"hint_count": attempt.hint_count, "attempt_number": attempt.attempt_number},
                    )
                )

        # Load current mastery
        mastery = None
        if self._learner_topic_mastery_repository is not None:
            mastery = await self._learner_topic_mastery_repository.get_by_goal_and_topic(
                learner_goal_id=attempt.learner_goal_id,
                topic_key=attempt.topic_key,
            )

        # 3. low_mastery_high_difficulty_mismatch
        difficulty = attempt.metadata.get("difficulty", "medium") if attempt.metadata else "medium"
        if mastery is not None and mastery.mastery_score < 0.45 and difficulty == "hard":
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=attempt.learner_profile_id,
                    learner_goal_id=attempt.learner_goal_id,
                    session_id=attempt.session_id,
                    daily_task_id=attempt.daily_task_id,
                    workflow_run_id=None,
                    source_type="quiz_answer_attempt",
                    signal_code="low_mastery_high_difficulty_mismatch",
                    topic_key=attempt.topic_key,
                    severity_score=0.7,
                    confidence_score=0.9,
                    payload={"mastery_score": mastery.mastery_score, "difficulty": difficulty},
                )
            )

        # 4. assessment_regression_from_quiz
        if attempt.is_correct is False and mastery is not None and mastery.mastery_score >= 0.75:
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=attempt.learner_profile_id,
                    learner_goal_id=attempt.learner_goal_id,
                    session_id=attempt.session_id,
                    daily_task_id=attempt.daily_task_id,
                    workflow_run_id=None,
                    source_type="quiz_answer_attempt",
                    signal_code="assessment_regression_from_quiz",
                    topic_key=attempt.topic_key,
                    severity_score=0.8,
                    confidence_score=0.85,
                    payload={"mastery_score": mastery.mastery_score, "attempt_score": attempt.score},
                )
            )

        # 5. short_guess_answer
        if attempt.learner_answer and len(attempt.learner_answer.strip()) < 3:
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=attempt.learner_profile_id,
                    learner_goal_id=attempt.learner_goal_id,
                    session_id=attempt.session_id,
                    daily_task_id=attempt.daily_task_id,
                    workflow_run_id=None,
                    source_type="quiz_answer_attempt",
                    signal_code="short_guess_answer",
                    topic_key=attempt.topic_key,
                    severity_score=0.5,
                    confidence_score=0.7,
                    payload={"answer_length": len(attempt.learner_answer.strip())},
                )
            )

        # 6. quiz_strategy_failure
        wrong_count = sum(1 for prev in recent_attempts if prev.is_correct is False)
        if wrong_count >= 3:
            signals.append(
                ReflectionEvidenceSignal.build(
                    learner_profile_id=attempt.learner_profile_id,
                    learner_goal_id=attempt.learner_goal_id,
                    session_id=attempt.session_id,
                    daily_task_id=attempt.daily_task_id,
                    workflow_run_id=None,
                    source_type="quiz_answer_attempt",
                    signal_code="quiz_strategy_failure",
                    topic_key=attempt.topic_key,
                    severity_score=0.85,
                    confidence_score=0.9,
                    payload={"failure_count": wrong_count, "window_size": len(recent_attempts)},
                )
            )

        return await self._persist(signals)
