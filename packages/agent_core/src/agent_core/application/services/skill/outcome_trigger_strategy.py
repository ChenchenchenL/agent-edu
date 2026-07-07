from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.outcome_aggregator import ArtifactOutcomeMetrics, SkillOutcomeAggregator
from agent_core.domain.entities.skill import SkillArtifact, SkillCuratorRecommendation
from agent_core.infrastructure.db.repositories.skill import SkillArtifactRepository, SkillCuratorRecommendationRepository


@dataclass(frozen=True)
class OutcomeTriggerConfig:
    auto_suppress_quality_threshold: float = 0.15
    auto_suppress_negative_threshold: float = 0.6
    auto_suppress_min_events: int = 10
    demotion_quality_threshold: float = 0.25
    high_correction_rate_threshold: float = 0.3
    high_safety_refusal_threshold: float = 0.1
    low_avg_confidence_threshold: float = 0.4


@dataclass(frozen=True)
class OutcomeTriggerResult:
    suppress_recommendations: int
    demotion_recommendations: int
    governance_evidence_updates: int


class OutcomeTriggerStrategy:
    def __init__(
        self,
        *,
        artifact_repository: SkillArtifactRepository,
        recommendation_repository: SkillCuratorRecommendationRepository,
        aggregator: SkillOutcomeAggregator,
        audit_service: AuditService,
        config: OutcomeTriggerConfig | None = None,
    ) -> None:
        self._artifact_repository = artifact_repository
        self._recommendation_repository = recommendation_repository
        self._aggregator = aggregator
        self._audit_service = audit_service
        self._config = config or OutcomeTriggerConfig()

    async def evaluate_and_recommend(
        self,
        *,
        artifact: SkillArtifact,
        operator_id: str = "system:outcome_feedback",
    ) -> dict[str, Any]:
        cfg = self._config
        metrics = await self._aggregator.compute_artifact_metrics(
            artifact_id=artifact.id,
            surface=artifact.scope,
        )
        evidence: dict[str, Any] = {
            "quality_score": artifact.quality_score,
            "total_events": metrics.total_events,
            "negative_composite": round(metrics.negative_composite, 4),
            "positive_composite": round(metrics.positive_composite, 4),
            "correction_rate": round(metrics.correction_rate, 4),
            "safety_refusal_rate": round(metrics.safety_refusal_rate, 4),
            "avg_confidence": round(metrics.avg_confidence, 4),
            "failure_rate": round(metrics.failure_rate, 4),
        }

        result: dict[str, Any] = {"suppress": False, "demotion": False, "evidence": evidence}

        if self._should_suppress(metrics):
            rec = await self._create_recommendation(
                artifact=artifact,
                recommendation_type="flag_for_review",
                recommended_action="suppress_selectable",
                reason_code="outcome_quality_regression",
                reason_note=(
                    f"quality_score={artifact.quality_score:.3f}, "
                    f"negative_composite={metrics.negative_composite:.3f}, "
                    f"events={metrics.total_events}"
                ),
                evidence_snapshot=evidence,
                operator_id=operator_id,
            )
            if rec is not None:
                result["suppress"] = True

        elif self._should_flag_demotion(metrics):
            rec = await self._create_recommendation(
                artifact=artifact,
                recommendation_type="flag_for_review",
                recommended_action="none",
                reason_code="outcome_quality_low",
                reason_note=f"quality_score={artifact.quality_score:.3f}, below demotion threshold",
                evidence_snapshot=evidence,
                operator_id=operator_id,
            )
            if rec is not None:
                result["demotion"] = True

        return result

    def build_outcome_signal_evidence(self, metrics: ArtifactOutcomeMetrics) -> dict[str, Any]:
        cfg = self._config
        evidence: dict[str, Any] = {}
        if metrics.correction_rate > cfg.high_correction_rate_threshold:
            evidence["high_correction_rate"] = True
        if metrics.safety_refusal_rate > cfg.high_safety_refusal_threshold:
            evidence["safety_refusal_pattern"] = True
        if metrics.avg_confidence < cfg.low_avg_confidence_threshold:
            evidence["low_avg_confidence"] = True
        return evidence

    def _should_suppress(self, metrics: ArtifactOutcomeMetrics) -> bool:
        cfg = self._config
        return (
            metrics.total_events >= cfg.auto_suppress_min_events
            and metrics.negative_composite > cfg.auto_suppress_negative_threshold
        )

    def _should_flag_demotion(self, metrics: ArtifactOutcomeMetrics) -> bool:
        cfg = self._config
        return (
            metrics.total_events >= cfg.auto_suppress_min_events
            and metrics.negative_composite > cfg.auto_suppress_negative_threshold * 0.5
        )

    async def _create_recommendation(
        self,
        *,
        artifact: SkillArtifact,
        recommendation_type: str,
        recommended_action: str,
        reason_code: str,
        reason_note: str,
        evidence_snapshot: dict[str, Any],
        operator_id: str,
    ) -> SkillCuratorRecommendation | None:
        import uuid
        source_job_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"outcome_feedback:{artifact.id}:{recommendation_type}:{recommended_action}"))

        existing = await self._recommendation_repository.get_by_source_job_id(source_job_id)
        if existing is not None:
            return None

        rec = SkillCuratorRecommendation.build(
            artifact_id=artifact.id,
            skill_name=artifact.name,
            skill_version=artifact.version,
            artifact_status=artifact.status,
            lineage_id=artifact.lineage_id,
            scope=artifact.scope,
            surface=artifact.scope,
            recommendation_type=recommendation_type,
            recommended_action=recommended_action,
            reason_code=reason_code,
            reason_note=reason_note,
            evidence_snapshot=evidence_snapshot,
            created_by=operator_id,
            source_job_id=source_job_id,
        )
        await self._recommendation_repository.create(rec)
        await self._audit_service.record(
            event_type="skill.curator.outcome_recommendation_created",
            resource_type="skill_curator_recommendation",
            resource_id=rec.id,
            actor=operator_id,
            event_data={
                "artifact_id": artifact.id,
                "recommendation_type": recommendation_type,
                "recommended_action": recommended_action,
                "reason_code": reason_code,
            },
        )
        return rec
