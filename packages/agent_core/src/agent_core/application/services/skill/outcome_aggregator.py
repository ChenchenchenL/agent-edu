from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from agent_core.infrastructure.db.repositories.skill import SkillUsageEventRepository


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ArtifactOutcomeMetrics:
    artifact_id: str
    surface: str
    window_start: datetime
    window_end: datetime
    total_events: int
    completion_rate: float
    partial_success_rate: float
    failure_rate: float
    correction_rate: float
    safety_refusal_rate: float
    avg_confidence: float
    acceptance_rate: float
    downstream_completion_rate: float
    negative_composite: float
    positive_composite: float
    learning_gain_rate: float = 0.0
    runtime_success_rate: float = 0.0
    learning_success_rate: float = 0.0
    needs_review: bool = False


class SkillOutcomeAggregator:
    def __init__(self, *, usage_repository: SkillUsageEventRepository) -> None:
        self._usage_repository = usage_repository

    async def compute_artifact_metrics(
        self,
        *,
        artifact_id: str,
        surface: str,
        lookback_days: int = 30,
    ) -> ArtifactOutcomeMetrics:
        now = _utcnow()
        window_start = now - timedelta(days=max(lookback_days, 1))

        events = await self._usage_repository.list_events(
            artifact_id=artifact_id,
            surface=surface,
            created_at_from=window_start,
            limit=200,
        )

        total = len(events)
        if total == 0:
            return ArtifactOutcomeMetrics(
                artifact_id=artifact_id,
                surface=surface,
                window_start=window_start,
                window_end=now,
                total_events=0,
                completion_rate=0.0,
                partial_success_rate=0.0,
                failure_rate=0.0,
                correction_rate=0.0,
                safety_refusal_rate=0.0,
                avg_confidence=0.5,
                acceptance_rate=0.0,
                downstream_completion_rate=0.0,
                negative_composite=0.0,
                positive_composite=0.5,
                learning_gain_rate=0.0,
                runtime_success_rate=0.0,
                learning_success_rate=0.0,
                needs_review=False,
            )

        completed = sum(1 for e in events if e.outcome_status == "completed")
        partial = sum(1 for e in events if e.outcome_status == "partial_success")
        failed = sum(1 for e in events if e.outcome_status in ("failed", "aborted"))

        correction_count = 0
        safety_refusal_count = 0
        accepted_count = 0
        downstream_count = 0
        confidence_sum = 0.0
        confidence_count = 0

        valid_gain_events = []

        for event in events:
            signals = event.outcome_signals or {}
            if signals.get("user_correction_requested"):
                correction_count += 1
            if signals.get("safety_refusal"):
                safety_refusal_count += 1
            if signals.get("accepted_by_user"):
                accepted_count += 1
            if signals.get("downstream_task_completed"):
                downstream_count += 1
            conf = signals.get("confidence")
            if isinstance(conf, (int, float)):
                confidence_sum += float(conf)
                confidence_count += 1

            # Parse mastery details
            delta = signals.get("mastery_delta")
            before = signals.get("mastery_before")
            after = signals.get("mastery_after")
            if before is not None and after is not None:
                try:
                    before_val = float(before)
                    after_val = float(after)
                    # Validate mastery values are in [0, 1] range
                    if 0.0 <= before_val <= 1.0 and 0.0 <= after_val <= 1.0:
                        delta = after_val - before_val
                    # Skip invalid mastery values silently
                except (ValueError, TypeError):
                    # Skip invalid mastery values silently
                    pass
            if delta is not None:
                try:
                    delta_val = float(delta)
                    # Validate delta is reasonable (abs <= 1.0)
                    if abs(delta_val) <= 1.0:
                        valid_gain_events.append(delta_val)
                except (ValueError, TypeError):
                    # Skip invalid delta values silently
                    pass

        completion_rate = completed / total
        partial_success_rate = partial / total
        failure_rate = failed / total
        correction_rate = correction_count / total
        safety_refusal_rate = safety_refusal_count / total
        acceptance_rate = accepted_count / total
        downstream_completion_rate = downstream_count / total
        avg_confidence = confidence_sum / confidence_count if confidence_count > 0 else 0.5

        negative_composite = (
            0.4 * failure_rate
            + 0.3 * correction_rate
            + 0.3 * safety_refusal_rate
        )
        positive_composite = (
            0.3 * completion_rate
            + 0.3 * acceptance_rate
            + 0.2 * downstream_completion_rate
            + 0.2 * (1.0 - correction_rate)
        )

        learning_gain_rate = sum(valid_gain_events) / len(valid_gain_events) if valid_gain_events else 0.0
        runtime_success_rate = (completed + partial) / total
        learning_success_rate = sum(1 for d in valid_gain_events if d > 0) / len(valid_gain_events) if valid_gain_events else 0.0

        # Flag needs_review: low failure (<0.15) but low/negative learning gain (<0.02)
        # Requires minimum 5 mastery events to avoid false positives on new artifacts
        needs_review = False
        if failure_rate < 0.15 and len(valid_gain_events) >= 5 and learning_gain_rate < 0.02:
            needs_review = True

        return ArtifactOutcomeMetrics(
            artifact_id=artifact_id,
            surface=surface,
            window_start=window_start,
            window_end=now,
            total_events=total,
            completion_rate=completion_rate,
            partial_success_rate=partial_success_rate,
            failure_rate=failure_rate,
            correction_rate=correction_rate,
            safety_refusal_rate=safety_refusal_rate,
            avg_confidence=avg_confidence,
            acceptance_rate=acceptance_rate,
            downstream_completion_rate=downstream_completion_rate,
            negative_composite=negative_composite,
            positive_composite=positive_composite,
            learning_gain_rate=learning_gain_rate,
            runtime_success_rate=runtime_success_rate,
            learning_success_rate=learning_success_rate,
            needs_review=needs_review,
        )
