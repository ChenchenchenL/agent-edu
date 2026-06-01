from __future__ import annotations

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.autonomy import TaskAttempt
from agent_core.domain.entities.reflection import ReflectionRecord
from agent_core.domain.entities.reflection_v2 import ReflectionOutcomeEvaluation
from agent_core.infrastructure.db.repositories import ReflectionOutcomeEvaluationRepository, TaskAttemptRepository


class ReflectionOutcomeService:
    def __init__(
        self,
        *,
        repository: ReflectionOutcomeEvaluationRepository,
        task_attempt_repository: TaskAttemptRepository | None,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._task_attempt_repository = task_attempt_repository
        self._audit_service = audit_service

    async def start_tracking(self, *, reflection: ReflectionRecord, topic_key: str | None, baseline_snapshot: dict[str, object]) -> ReflectionOutcomeEvaluation:
        existing = await self._repository.get_by_reflection(reflection.id)
        if existing is not None:
            return existing
        evaluation = ReflectionOutcomeEvaluation.build(
            reflection_record_id=reflection.id,
            learner_goal_id=reflection.learner_goal_id,
            topic_key=topic_key,
            window_size=3,
            baseline_snapshot=baseline_snapshot,
        )
        await self._repository.create(evaluation)
        return evaluation

    async def evaluate(self, *, reflection: ReflectionRecord, topic_key: str | None) -> ReflectionOutcomeEvaluation | None:
        evaluation = await self._repository.get_by_reflection(reflection.id)
        if evaluation is None or self._task_attempt_repository is None:
            return evaluation
        attempts = await self._task_attempt_repository.list_recent_by_goal(reflection.learner_goal_id, limit=10)
        topic_attempts = [item for item in attempts if topic_key is None or item.topic_focus == topic_key][:3]
        if not topic_attempts:
            return evaluation
        success_count = len([item for item in topic_attempts if item.outcome_status == "completed"])
        failure_count = len([item for item in topic_attempts if item.outcome_status in {"failed", "skipped"}])
        status = "inconclusive"
        score = 0.0
        note = "insufficient evidence"
        if len(topic_attempts) >= evaluation.window_size:
            if success_count >= 2 and failure_count <= 1:
                status = "effective"
                score = 0.7
                note = "follow-up attempts improved"
            elif failure_count >= 2:
                status = "ineffective"
                score = -0.5
                note = "follow-up attempts did not improve"
            else:
                status = "inconclusive"
                score = 0.0
                note = "mixed follow-up results"
        updated = evaluation.with_result(
            evaluation_status=status,
            observed_attempt_count=len(topic_attempts),
            outcome_snapshot={
                "success_count": success_count,
                "failure_count": failure_count,
                "attempt_ids": [item.id for item in topic_attempts],
            },
            improvement_score=score,
            evaluation_note=note,
            evaluated=status != "pending",
        )
        await self._repository.update(updated)
        await self._audit_service.record(
            event_type="reflection.outcome.evaluated",
            resource_type="reflection_outcome_evaluation",
            resource_id=updated.id,
            actor="system",
            event_data={
                "reflection_record_id": reflection.id,
                "evaluation_status": updated.evaluation_status,
                "observed_attempt_count": updated.observed_attempt_count,
            },
        )
        return updated

    async def list_pending(self, *, learner_goal_id: str | None = None, limit: int = 20) -> list[ReflectionOutcomeEvaluation]:
        if not hasattr(self._repository, "list_pending"):
            return []
        return await self._repository.list_pending(learner_goal_id=learner_goal_id, limit=limit)
