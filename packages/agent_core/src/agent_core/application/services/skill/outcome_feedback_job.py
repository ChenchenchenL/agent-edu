from __future__ import annotations

from dataclasses import dataclass, field

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.outcome_aggregator import SkillOutcomeAggregator
from agent_core.application.services.skill.outcome_trigger_strategy import OutcomeTriggerConfig, OutcomeTriggerStrategy
from agent_core.application.services.skill.quality_updater import SkillQualityUpdater, SkillQualityUpdaterConfig
from agent_core.infrastructure.db.repositories.skill import SkillArtifactRepository, SkillCuratorRecommendationRepository
from agent_core.infrastructure.observability.metrics import (
    observe_skill_auto_suppress,
    observe_skill_outcome_metrics,
    observe_skill_quality,
)


@dataclass(frozen=True)
class SkillOutcomeFeedbackConfig:
    enabled: bool = True
    quality_updater_config: SkillQualityUpdaterConfig = SkillQualityUpdaterConfig()
    trigger_config: OutcomeTriggerConfig = OutcomeTriggerConfig()
    artifact_scan_limit: int = 50


@dataclass(frozen=True)
class SkillOutcomeFeedbackResult:
    quality_updated: int
    flagged_for_review: int
    suppression_recommendations_created: int
    demotion_recommendations_created: int
    suppression_candidates: list[str] = field(default_factory=list)


class SkillOutcomeFeedbackJob:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        recommendation_repository: SkillCuratorRecommendationRepository,
        aggregator: SkillOutcomeAggregator,
        audit_service: AuditService,
        config: SkillOutcomeFeedbackConfig | None = None,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._recommendation_repository = recommendation_repository
        self._aggregator = aggregator
        self._audit_service = audit_service
        self._config = config or SkillOutcomeFeedbackConfig()
        self._quality_updater = SkillQualityUpdater(
            artifact_repository=artifact_repository,
            aggregator=aggregator,
            audit_service=audit_service,
            config=self._config.quality_updater_config,
        )
        self._trigger_strategy = OutcomeTriggerStrategy(
            artifact_repository=artifact_repository,
            recommendation_repository=recommendation_repository,
            aggregator=aggregator,
            audit_service=audit_service,
            config=self._config.trigger_config,
        )

    async def run_once(self, *, limit: int | None = None) -> SkillOutcomeFeedbackResult:
        cfg = self._config
        if not cfg.enabled:
            return SkillOutcomeFeedbackResult(0, 0, 0, 0)

        scan_limit = limit or cfg.artifact_scan_limit
        quality_result = await self._quality_updater.update_quality_scores(limit=scan_limit)

        suppress_count = 0
        demotion_count = 0

        for status in ("active", "stable"):
            artifacts = await self._artifact_repository.list_artifacts(status=status, limit=scan_limit)
            for artifact in artifacts:
                metrics = await self._aggregator.compute_artifact_metrics(
                    artifact_id=artifact.id,
                    surface=artifact.scope,
                )
                observe_skill_quality(
                    artifact_id=artifact.id,
                    skill_name=artifact.name,
                    surface=artifact.scope,
                    score=artifact.quality_score,
                )
                if metrics.total_events > 0:
                    observe_skill_outcome_metrics(
                        artifact_id=artifact.id,
                        surface=artifact.scope,
                        completion_rate=metrics.completion_rate,
                        failure_rate=metrics.failure_rate,
                        correction_rate=metrics.correction_rate,
                    )

                if artifact.id in quality_result.suppression_candidates:
                    trigger_result = await self._trigger_strategy.evaluate_and_recommend(
                        artifact=artifact,
                    )
                    if trigger_result.get("suppress"):
                        suppress_count += 1
                        observe_skill_auto_suppress(
                            skill_name=artifact.name,
                            surface=artifact.scope,
                        )
                    elif trigger_result.get("demotion"):
                        demotion_count += 1

        await self._audit_service.record(
            event_type="skill.outcome_feedback_job.completed",
            resource_type="system",
            resource_id=None,
            actor="system:outcome_feedback",
            event_data={
                "quality_updated": quality_result.updated_count,
                "flagged_for_review": quality_result.flagged_count,
                "suppression_recommendations_created": suppress_count,
                "demotion_recommendations_created": demotion_count,
            },
        )

        return SkillOutcomeFeedbackResult(
            quality_updated=quality_result.updated_count,
            flagged_for_review=quality_result.flagged_count,
            suppression_recommendations_created=suppress_count,
            demotion_recommendations_created=demotion_count,
            suppression_candidates=quality_result.suppression_candidates,
        )
