from __future__ import annotations

from datetime import datetime, timezone

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.autonomy import TaskAttempt
from agent_core.domain.entities.memory import MemoryEvent
from agent_core.domain.entities.message import SessionMessage
from agent_core.domain.entities.planning import DailyTask, WorkflowRun
from agent_core.domain.entities.reflection_v2 import ReflectionEvidenceSignal
from agent_core.infrastructure.db.repositories import (
    DailyTaskRepository,
    LearnerTopicMasteryRepository,
    MemoryEventRepository,
    ReflectionEvidenceSignalRepository,
    SessionMessageRepository,
    WorkflowRunRepository,
)


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
    ) -> None:
        self._repository = repository
        self._message_repository = message_repository
        self._memory_event_repository = memory_event_repository
        self._daily_task_repository = daily_task_repository
        self._workflow_run_repository = workflow_run_repository
        self._learner_topic_mastery_repository = learner_topic_mastery_repository
        self._audit_service = audit_service

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
