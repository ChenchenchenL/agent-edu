from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_core.infrastructure.db.repositories import TaskAttemptRepository
    from agent_core.domain.entities.autonomy import LearnerTopicMastery

from agent_core.domain.entities.autonomy import LearnerTopicMastery


class ReviewService:
    """Service for handling review scheduling logic."""

    def __init__(
        self,
        *,
        task_attempt_repository: TaskAttemptRepository | None = None,
    ) -> None:
        self._task_attempt_repository = task_attempt_repository

    async def get_review_intervals(
        self,
        learner_goal_id: str,
        mastery: LearnerTopicMastery | None,
        *,
        recent_failures: int | None = None,
    ) -> list[int]:
        """Resolve review intervals."""
        score = mastery.mastery_score if mastery is not None else 0.5
        confidence = mastery.confidence if mastery is not None else 0.5
        evidence_count = mastery.evidence_count if mastery is not None else 0
        
        if recent_failures is None:
            recent_failures = await self._recent_topic_failure_count(
                learner_goal_id=learner_goal_id,
                topic_key=mastery.topic_key if mastery is not None else None,
            )
            
        tier_order = ["remedial", "reinforced", "standard", "stable", "relaxed"]
        tier = "standard"
        if recent_failures >= 2 or score < 0.45 or confidence < 0.45:
            tier = "remedial"
        elif recent_failures >= 1 or score < 0.65:
            tier = "reinforced"
        elif score >= 0.85 and confidence >= 0.75 and evidence_count >= 4 and recent_failures == 0:
            tier = "relaxed"
        elif score >= 0.75 and confidence >= 0.65:
            tier = "stable"
            
        tier_to_intervals = {
            "remedial": [1, 2, 3],
            "reinforced": [1, 2, 5],
            "standard": [1, 3, 7],
            "stable": [2, 5, 10],
            "relaxed": [3, 7, 14],
        }
        return tier_to_intervals.get(tier, [1, 3, 7])

    async def _recent_topic_failure_count(self, *, learner_goal_id: str, topic_key: str | None) -> int:
        if self._task_attempt_repository is None or not topic_key:
            return 0
        attempts = await self._task_attempt_repository.list_recent_by_goal(learner_goal_id, limit=10)
        topic_attempts = [item for item in attempts if item.topic_focus == topic_key][:3]
        return len([item for item in topic_attempts if item.outcome_status in {"failed", "skipped"}])
