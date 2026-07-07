from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.outcome_aggregator import SkillOutcomeAggregator
from agent_core.infrastructure.db.repositories.skill import SkillArtifactRepository


@dataclass(frozen=True)
class QualityUpdateResult:
    updated_count: int
    flagged_count: int
    suppression_candidates: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillQualityUpdaterConfig:
    ema_alpha: float = 0.3
    max_delta: float = 0.1
    suppression_threshold: float = 0.2
    positive_weight: float = 0.3
    negative_weight: float = 0.3
    confidence_weight: float = 0.2
    learning_gain_weight: float = 0.2


class SkillQualityUpdater:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        aggregator: SkillOutcomeAggregator,
        audit_service: AuditService,
        config: SkillQualityUpdaterConfig | None = None,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._aggregator = aggregator
        self._audit_service = audit_service
        self._config = config or SkillQualityUpdaterConfig()

    async def update_quality_scores(self, *, limit: int = 50) -> QualityUpdateResult:
        cfg = self._config
        updated = 0
        flagged = 0
        suppression_candidates: list[str] = []

        for status in ("active", "stable"):
            artifacts = await self._artifact_repository.list_artifacts(status=status, limit=limit)
            for artifact in artifacts:
                metrics = await self._aggregator.compute_artifact_metrics(
                    artifact_id=artifact.id,
                    surface=artifact.scope,
                )
                if metrics.total_events == 0:
                    continue

                learning_gain_val = getattr(metrics, "learning_gain_rate", 0.0)
                new_score = (
                    0.5
                    + cfg.positive_weight * metrics.positive_composite
                    - cfg.negative_weight * metrics.negative_composite
                    + cfg.confidence_weight * (metrics.avg_confidence - 0.5)
                    + getattr(cfg, "learning_gain_weight", 0.2) * learning_gain_val
                )
                new_score = max(0.0, min(1.0, new_score))

                old_score = artifact.quality_score
                smoothed = (1.0 - cfg.ema_alpha) * old_score + cfg.ema_alpha * new_score
                delta = smoothed - old_score
                clamped_delta = max(-cfg.max_delta, min(cfg.max_delta, delta))
                final_score = max(0.0, min(1.0, old_score + clamped_delta))

                if abs(final_score - old_score) < 1e-6:
                    continue

                artifact.quality_score = final_score
                await self._artifact_repository.update(artifact)
                updated += 1

                if final_score < cfg.suppression_threshold:
                    flagged += 1
                    suppression_candidates.append(artifact.id)

                await self._audit_service.record(
                    event_type="skill.quality_score.updated",
                    resource_type="skill_artifact",
                    resource_id=artifact.id,
                    actor="system:outcome_feedback",
                    event_data={
                        "old_score": round(old_score, 4),
                        "new_score": round(final_score, 4),
                        "raw_score": round(new_score, 4),
                        "total_events": metrics.total_events,
                        "positive_composite": round(metrics.positive_composite, 4),
                        "negative_composite": round(metrics.negative_composite, 4),
                        "avg_confidence": round(metrics.avg_confidence, 4),
                        "learning_gain_rate": round(getattr(metrics, "learning_gain_rate", 0.0), 4),
                        "learning_success_rate": round(getattr(metrics, "learning_success_rate", 0.0), 4),
                        "needs_review": getattr(metrics, "needs_review", False),
                        "learning_gain_missing": metrics.total_events > 0 and getattr(metrics, "learning_gain_rate", 0.0) == 0.0 and not getattr(metrics, "needs_review", False),
                        "flagged": final_score < cfg.suppression_threshold,
                    },
                )

        return QualityUpdateResult(
            updated_count=updated,
            flagged_count=flagged,
            suppression_candidates=suppression_candidates,
        )
