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
        from agent_core.application.services.reflection_outcome_policy import evaluate_outcome
        
        evaluation = await self._repository.get_by_reflection(reflection.id)
        if evaluation is None or self._task_attempt_repository is None:
            return evaluation
        attempts = await self._task_attempt_repository.list_recent_by_goal(reflection.learner_goal_id, limit=10)
        topic_attempts = [item for item in attempts if topic_key is None or item.topic_focus == topic_key][:3]
        if not topic_attempts:
            return evaluation

        result = evaluate_outcome(
            topic_attempts=topic_attempts,
            window_size=evaluation.window_size,
        )

        updated = evaluation.with_result(
            evaluation_status=result.evaluation_status,
            observed_attempt_count=result.observed_attempt_count,
            outcome_snapshot=result.outcome_snapshot,
            improvement_score=result.improvement_score,
            evaluation_note=result.evaluation_note,
            evaluated=result.evaluated,
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
