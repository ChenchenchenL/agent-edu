"""Tests for Phase 7: Outcome Feedback Loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.outcome_aggregator import ArtifactOutcomeMetrics, SkillOutcomeAggregator
from agent_core.application.services.skill.outcome_feedback_job import SkillOutcomeFeedbackJob, SkillOutcomeFeedbackConfig, SkillOutcomeFeedbackResult
from agent_core.application.services.skill.outcome_trigger_strategy import OutcomeTriggerConfig, OutcomeTriggerStrategy
from agent_core.application.services.skill.quality_updater import SkillQualityUpdater, SkillQualityUpdaterConfig, QualityUpdateResult
from agent_core.domain.entities.skill import SkillArtifact, SkillCuratorRecommendation, SkillUsageEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    *,
    artifact_id: str = "art-1",
    surface: str = "chat",
    outcome_status: str = "completed",
    outcome_signals: dict[str, Any] | None = None,
) -> SkillUsageEvent:
    return SkillUsageEvent.build(
        skill_artifact_id=artifact_id,
        skill_name="test_skill",
        skill_version="1.0.0",
        skill_status_at_use="active",
        surface=surface,
        outcome_status=outcome_status,
        outcome_signals=outcome_signals or {},
    )


def _make_artifact(
    *,
    artifact_id: str = "art-1",
    name: str = "test_skill",
    status: str = "active",
    quality_score: float = 0.5,
) -> SkillArtifact:
    from dataclasses import replace
    base = SkillArtifact.build(
        name=name,
        version="1.0.0",
        skill_type="curated",
        scope="chat",
        status=status,
        description="Test skill",
        quality_score=quality_score,
    )
    return replace(base, id=artifact_id, lineage_id=artifact_id)


# ---------------------------------------------------------------------------
# Stub repositories
# ---------------------------------------------------------------------------

class _StubUsageRepo:
    def __init__(self, events: list[SkillUsageEvent] | None = None) -> None:
        self._events = events or []

    async def list_events(self, *, artifact_id: str, surface: str, limit: int = 50, created_at_from: Any = None, **kwargs: Any) -> list[SkillUsageEvent]:
        return [e for e in self._events if e.skill_artifact_id == artifact_id and e.surface == surface][:limit]


class _StubArtifactRepo:
    def __init__(self, artifacts: list[SkillArtifact] | None = None) -> None:
        self.artifacts = artifacts or []

    async def list_artifacts(self, *, status: str, limit: int = 50, name: str | None = None, scope: str | None = None, **kwargs: Any) -> list[SkillArtifact]:
        result = [a for a in self.artifacts if a.status == status]
        if name:
            result = [a for a in result if a.name == name]
        if scope:
            result = [a for a in result if a.scope == scope]
        return result[:limit]

    async def update(self, entity: SkillArtifact) -> None:
        for i, a in enumerate(self.artifacts):
            if a.id == entity.id:
                self.artifacts[i] = entity
                return

    async def get_by_id(self, artifact_id: str) -> SkillArtifact | None:
        for a in self.artifacts:
            if a.id == artifact_id:
                return a
        return None


class _StubAuditRepo:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def create(self, event: Any) -> Any:
        self.events.append(event)
        return event


class _StubRecommendationRepo:
    def __init__(self) -> None:
        self.recommendations: list[SkillCuratorRecommendation] = []

    async def create(self, entity: SkillCuratorRecommendation) -> None:
        self.recommendations.append(entity)

    async def get_by_source_job_id(self, source_job_id: str) -> SkillCuratorRecommendation | None:
        for r in self.recommendations:
            if r.source_job_id == source_job_id:
                return r
        return None


# ===========================================================================
# Outcome Aggregator
# ===========================================================================


class TestOutcomeAggregator:
    @pytest.mark.asyncio
    async def test_no_events_returns_neutral(self) -> None:
        repo = _StubUsageRepo([])
        agg = SkillOutcomeAggregator(usage_repository=repo)
        metrics = await agg.compute_artifact_metrics(artifact_id="art-1", surface="chat")
        assert metrics.total_events == 0
        assert metrics.completion_rate == 0.0
        assert metrics.failure_rate == 0.0
        assert metrics.avg_confidence == 0.5

    @pytest.mark.asyncio
    async def test_all_completed(self) -> None:
        events = [_make_event(outcome_status="completed") for _ in range(5)]
        repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=repo)
        metrics = await agg.compute_artifact_metrics(artifact_id="art-1", surface="chat")
        assert metrics.total_events == 5
        assert metrics.completion_rate == 1.0
        assert metrics.failure_rate == 0.0
        assert metrics.positive_composite >= 0.5

    @pytest.mark.asyncio
    async def test_all_failed(self) -> None:
        events = [_make_event(outcome_status="failed") for _ in range(5)]
        repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=repo)
        metrics = await agg.compute_artifact_metrics(artifact_id="art-1", surface="chat")
        assert metrics.failure_rate == 1.0
        assert metrics.completion_rate == 0.0
        assert metrics.negative_composite > 0.3

    @pytest.mark.asyncio
    async def test_outcome_signals_consumed(self) -> None:
        events = [
            _make_event(
                outcome_status="completed",
                outcome_signals={
                    "user_correction_requested": True,
                    "accepted_by_user": True,
                    "confidence": 0.8,
                },
            ),
            _make_event(
                outcome_status="completed",
                outcome_signals={
                    "user_correction_requested": False,
                    "accepted_by_user": True,
                    "confidence": 0.6,
                },
            ),
            _make_event(
                outcome_status="failed",
                outcome_signals={
                    "safety_refusal": True,
                    "confidence": 0.3,
                },
            ),
        ]
        repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=repo)
        metrics = await agg.compute_artifact_metrics(artifact_id="art-1", surface="chat")
        assert metrics.total_events == 3
        assert metrics.correction_rate == pytest.approx(1 / 3, abs=0.01)
        assert metrics.safety_refusal_rate == pytest.approx(1 / 3, abs=0.01)
        assert metrics.acceptance_rate == pytest.approx(2 / 3, abs=0.01)
        assert metrics.avg_confidence == pytest.approx(0.567, abs=0.01)

    @pytest.mark.asyncio
    async def test_negative_composite_formula(self) -> None:
        events = [
            _make_event(outcome_status="failed", outcome_signals={"user_correction_requested": True}),
            _make_event(outcome_status="completed"),
        ]
        repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=repo)
        metrics = await agg.compute_artifact_metrics(artifact_id="art-1", surface="chat")
        expected = 0.4 * 0.5 + 0.3 * 0.5 + 0.3 * 0.0
        assert metrics.negative_composite == pytest.approx(expected, abs=0.01)


# ===========================================================================
# Quality Updater
# ===========================================================================


class TestQualityUpdater:
    @pytest.mark.asyncio
    async def test_updates_quality_score(self) -> None:
        artifact = _make_artifact(quality_score=0.5)
        art_repo = _StubArtifactRepo([artifact])
        events = [_make_event(outcome_status="completed") for _ in range(5)]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        aud_repo = _StubAuditRepo()

        updater = SkillQualityUpdater(
            artifact_repository=art_repo,
            aggregator=agg,
            audit_service=AuditService(aud_repo),
        )
        result = await updater.update_quality_scores(limit=10)
        assert result.updated_count >= 1
        updated = art_repo.artifacts[0]
        assert updated.quality_score != 0.5

    @pytest.mark.asyncio
    async def test_ema_smoothing(self) -> None:
        artifact = _make_artifact(quality_score=0.5)
        art_repo = _StubArtifactRepo([artifact])
        events = [_make_event(outcome_status="failed") for _ in range(10)]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        aud_repo = _StubAuditRepo()

        config = SkillQualityUpdaterConfig(ema_alpha=0.3, max_delta=0.1)
        updater = SkillQualityUpdater(
            artifact_repository=art_repo, aggregator=agg,
            audit_service=AuditService(aud_repo), config=config,
        )
        await updater.update_quality_scores(limit=10)
        updated = art_repo.artifacts[0]
        assert updated.quality_score < 0.5
        assert updated.quality_score >= 0.5 - 0.1

    @pytest.mark.asyncio
    async def test_max_delta_clamped(self) -> None:
        artifact = _make_artifact(quality_score=0.9)
        art_repo = _StubArtifactRepo([artifact])
        events = [_make_event(outcome_status="failed") for _ in range(20)]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        aud_repo = _StubAuditRepo()

        config = SkillQualityUpdaterConfig(ema_alpha=1.0, max_delta=0.05)
        updater = SkillQualityUpdater(
            artifact_repository=art_repo, aggregator=agg,
            audit_service=AuditService(aud_repo), config=config,
        )
        await updater.update_quality_scores(limit=10)
        updated = art_repo.artifacts[0]
        assert updated.quality_score >= 0.9 - 0.05

    @pytest.mark.asyncio
    async def test_suppression_flag(self) -> None:
        artifact = _make_artifact(quality_score=0.15)
        art_repo = _StubArtifactRepo([artifact])
        events = [
            _make_event(
                outcome_status="failed",
                outcome_signals={"user_correction_requested": True, "safety_refusal": True},
            )
            for _ in range(10)
        ]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        aud_repo = _StubAuditRepo()

        config = SkillQualityUpdaterConfig(suppression_threshold=0.3)
        updater = SkillQualityUpdater(
            artifact_repository=art_repo, aggregator=agg,
            audit_service=AuditService(aud_repo), config=config,
        )
        result = await updater.update_quality_scores(limit=10)
        assert len(result.suppression_candidates) >= 1


# ===========================================================================
# Outcome Trigger Strategy
# ===========================================================================


class TestOutcomeTriggerStrategy:
    @pytest.mark.asyncio
    async def test_auto_suppress_multi_condition(self) -> None:
        artifact = _make_artifact(quality_score=0.1)
        art_repo = _StubArtifactRepo([artifact])
        events = [
            _make_event(
                outcome_status="failed",
                outcome_signals={"user_correction_requested": True, "safety_refusal": True},
            )
            for _ in range(15)
        ]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        rec_repo = _StubRecommendationRepo()
        aud_repo = _StubAuditRepo()

        strategy = OutcomeTriggerStrategy(
            artifact_repository=art_repo,
            recommendation_repository=rec_repo,
            aggregator=agg,
            audit_service=AuditService(aud_repo),
        )
        result = await strategy.evaluate_and_recommend(artifact=artifact)
        assert result["suppress"] is True
        assert len(rec_repo.recommendations) == 1
        assert rec_repo.recommendations[0].recommended_action == "suppress_selectable"

    @pytest.mark.asyncio
    async def test_no_suppress_with_few_events(self) -> None:
        artifact = _make_artifact(quality_score=0.1)
        art_repo = _StubArtifactRepo([artifact])
        events = [_make_event(outcome_status="failed") for _ in range(3)]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        rec_repo = _StubRecommendationRepo()
        aud_repo = _StubAuditRepo()

        strategy = OutcomeTriggerStrategy(
            artifact_repository=art_repo,
            recommendation_repository=rec_repo,
            aggregator=agg,
            audit_service=AuditService(aud_repo),
        )
        result = await strategy.evaluate_and_recommend(artifact=artifact)
        assert result["suppress"] is False

    @pytest.mark.asyncio
    async def test_outcome_signal_evidence(self) -> None:
        events = [
            _make_event(outcome_status="completed", outcome_signals={"user_correction_requested": True}),
            _make_event(outcome_status="completed", outcome_signals={"safety_refusal": True, "confidence": 0.2}),
        ]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        metrics = await agg.compute_artifact_metrics(artifact_id="art-1", surface="chat")

        strategy = OutcomeTriggerStrategy(
            artifact_repository=_StubArtifactRepo(),
            recommendation_repository=_StubRecommendationRepo(),
            aggregator=agg,
            audit_service=AuditService(_StubAuditRepo()),
        )
        evidence = strategy.build_outcome_signal_evidence(metrics)
        assert evidence.get("high_correction_rate") is True
        assert evidence.get("safety_refusal_pattern") is True
        assert evidence.get("low_avg_confidence") is True


# ===========================================================================
# Feedback Job
# ===========================================================================


class TestFeedbackJob:
    @pytest.mark.asyncio
    async def test_run_once_disabled(self) -> None:
        job = SkillOutcomeFeedbackJob(
            artifact_repository=_StubArtifactRepo(),
            recommendation_repository=_StubRecommendationRepo(),
            aggregator=SkillOutcomeAggregator(usage_repository=_StubUsageRepo()),
            audit_service=AuditService(_StubAuditRepo()),
            config=SkillOutcomeFeedbackConfig(enabled=False),
        )
        result = await job.run_once()
        assert result.quality_updated == 0

    @pytest.mark.asyncio
    async def test_run_once_with_artifacts(self) -> None:
        artifact = _make_artifact(quality_score=0.5)
        art_repo = _StubArtifactRepo([artifact])
        events = [_make_event(outcome_status="completed") for _ in range(5)]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        aud_repo = _StubAuditRepo()

        job = SkillOutcomeFeedbackJob(
            artifact_repository=art_repo,
            recommendation_repository=_StubRecommendationRepo(),
            aggregator=agg,
            audit_service=AuditService(aud_repo),
        )
        result = await job.run_once(limit=10)
        assert result.quality_updated >= 1
        assert len(aud_repo.events) >= 1

    @pytest.mark.asyncio
    async def test_run_once_suppression_candidate(self) -> None:
        artifact = _make_artifact(quality_score=0.1)
        art_repo = _StubArtifactRepo([artifact])
        events = [
            _make_event(
                outcome_status="failed",
                outcome_signals={"user_correction_requested": True},
            )
            for _ in range(15)
        ]
        usage_repo = _StubUsageRepo(events)
        agg = SkillOutcomeAggregator(usage_repository=usage_repo)
        rec_repo = _StubRecommendationRepo()
        aud_repo = _StubAuditRepo()

        job = SkillOutcomeFeedbackJob(
            artifact_repository=art_repo,
            recommendation_repository=rec_repo,
            aggregator=agg,
            audit_service=AuditService(aud_repo),
            config=SkillOutcomeFeedbackConfig(
                quality_updater_config=SkillQualityUpdaterConfig(suppression_threshold=0.2),
            ),
        )
        result = await job.run_once(limit=10)
        assert result.suppression_recommendations_created >= 0


# ===========================================================================
# Router quality multiplier
# ===========================================================================


class TestRouterQualityMultiplier:
    def test_low_quality_reduces_score(self) -> None:
        from agent_core.application.services.skill.router import SkillRouterCandidate, SkillRouterService
        c_high = SkillRouterCandidate(
            candidate_id="high", source_type="active_artifact", capability="chat",
            artifact_id="a1", skill_name="s", surface="chat",
            implementation_binding="s", artifact_status="active", trust_level=22,
            artifact_quality=0.9, total_score=0.8,
        )
        c_low = SkillRouterCandidate(
            candidate_id="low", source_type="active_artifact", capability="chat",
            artifact_id="a2", skill_name="s", surface="chat",
            implementation_binding="s", artifact_status="active", trust_level=22,
            artifact_quality=0.1, total_score=0.8,
        )
        adjusted_high = SkillRouterService._apply_quality_multiplier(c_high)
        adjusted_low = SkillRouterService._apply_quality_multiplier(c_low)
        assert adjusted_high.total_score > adjusted_low.total_score

    def test_default_quality_no_change(self) -> None:
        from agent_core.application.services.skill.router import SkillRouterCandidate, SkillRouterService
        c = SkillRouterCandidate(
            candidate_id="mid", source_type="active_artifact", capability="chat",
            artifact_id="a1", skill_name="s", surface="chat",
            implementation_binding="s", artifact_status="active", trust_level=22,
            artifact_quality=0.5, total_score=1.0,
        )
        adjusted = SkillRouterService._apply_quality_multiplier(c)
        assert adjusted.total_score == pytest.approx(0.85, abs=0.01)


# ===========================================================================
# Observability metrics
# ===========================================================================


class TestObservabilityMetrics:
    def test_observe_skill_quality(self) -> None:
        from agent_core.infrastructure.observability.metrics import observe_skill_quality
        observe_skill_quality(artifact_id="a1", skill_name="s", surface="chat", score=0.7)

    def test_observe_skill_outcome_metrics(self) -> None:
        from agent_core.infrastructure.observability.metrics import observe_skill_outcome_metrics
        observe_skill_outcome_metrics(
            artifact_id="a1", surface="chat",
            completion_rate=0.8, failure_rate=0.1, correction_rate=0.2,
        )

    def test_observe_skill_auto_suppress(self) -> None:
        from agent_core.infrastructure.observability.metrics import observe_skill_auto_suppress
        observe_skill_auto_suppress(skill_name="s", surface="chat")
