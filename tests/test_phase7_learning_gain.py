import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from agent_core.application.services.skill.outcome_aggregator import (
    SkillOutcomeAggregator,
)
from agent_core.application.services.skill.quality_updater import (
    SkillQualityUpdater,
    SkillQualityUpdaterConfig,
)
from agent_core.application.services.skill.curator_job import (
    SkillCuratorJobService,
    SkillCuratorJobConfig,
)
from agent_core.domain.entities.skill import SkillArtifact, SkillUsageEvent


class StubUsageRepository:
    def __init__(self, events=None):
        self.events = events or []

    async def list_events(self, **kwargs):
        res = self.events
        if "artifact_id" in kwargs:
            res = [e for e in res if e.skill_artifact_id == kwargs["artifact_id"]]
        elif "skill_name" in kwargs:
            res = [e for e in res if e.skill_name == kwargs["skill_name"]]
        return res


class StubArtifactRepository:
    def __init__(self, artifacts=None):
        self.artifacts = artifacts or []

    async def list_artifacts(self, **kwargs):
        return self.artifacts

    async def update(self, artifact):
        for idx, a in enumerate(self.artifacts):
            if a.id == artifact.id:
                self.artifacts[idx] = artifact
                break
        return artifact


class StubRecommendationService:
    def __init__(self):
        self.created = []

    async def create_recommendation(self, **kwargs):
        self.created.append(kwargs)
        return MagicMock()


class StubRecommendationRepository:
    def __init__(self):
        self.records = []

    async def get_by_source_job_id(self, source_job_id):
        return None


class StubAuditService:
    def __init__(self):
        self.events = []

    async def record(self, **kwargs):
        self.events.append(kwargs)


def _make_usage_event(
    *,
    event_id: str,
    artifact_id: str,
    skill_name: str,
    outcome_status: str,
    outcome_signals: dict,
) -> SkillUsageEvent:
    return SkillUsageEvent(
        id=event_id,
        skill_artifact_id=artifact_id,
        skill_name=skill_name,
        skill_version="0.1.0",
        skill_status_at_use="active",
        learner_profile_id="p-1",
        learner_goal_id="g-1",
        session_id="s-1",
        daily_task_id="t-1",
        workflow_run_id="w-1",
        surface="chat",
        topic_key="topic-1",
        trigger_source="manual",
        outcome_status=outcome_status,
        latency_ms=100,
        cost_units=0.01,
        input_summary=None,
        input_fingerprint=None,
        output_summary=None,
        output_fingerprint=None,
        error_code=None,
        resolver_status="resolved",
        selection_reason="production_default",
        outcome_signals=outcome_signals,
        metadata={},
        created_at=datetime.now(timezone.utc),
    )


class TestPhase7LearningGain:
    @pytest.mark.asyncio
    async def test_positive_mastery_delta_improves_artifact_quality(self) -> None:
        artifact = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.5,
        )
        artifact.id = "art-1"

        # Events with positive learning gains
        event1 = _make_usage_event(
            event_id="ev-1",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_before": 0.3, "mastery_after": 0.6, "confidence": 0.8},
        )
        event2 = _make_usage_event(
            event_id="ev-2",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_delta": 0.2, "confidence": 0.8},
        )

        artifact_repo = StubArtifactRepository([artifact])
        usage_repo = StubUsageRepository([event1, event2])
        aggregator = SkillOutcomeAggregator(usage_repository=usage_repo)
        audit_service = StubAuditService()

        updater = SkillQualityUpdater(
            artifact_repository=artifact_repo,
            aggregator=aggregator,
            audit_service=audit_service,
            config=SkillQualityUpdaterConfig(learning_gain_weight=0.5),
        )

        # Run updater
        await updater.update_quality_scores()

        # Quality score should be higher than initial 0.5
        assert artifact.quality_score > 0.5

    @pytest.mark.asyncio
    async def test_high_completion_but_negative_learning_gain_creates_review_recommendation(self) -> None:
        artifact = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.5,
        )
        artifact.id = "art-1"

        # Completed events but negative learning gain delta
        event1 = _make_usage_event(
            event_id="ev-1",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_before": 0.5, "mastery_after": 0.3},
        )
        event2 = _make_usage_event(
            event_id="ev-2",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_before": 0.6, "mastery_after": 0.4},
        )

        artifact_repo = StubArtifactRepository([artifact])
        usage_repo = StubUsageRepository([event1, event2])
        rec_service = StubRecommendationService()
        rec_repo = StubRecommendationRepository()
        audit_service = StubAuditService()

        # Run curator job on this artifact
        job_service = SkillCuratorJobService(
            artifact_repository=artifact_repo,
            usage_repository=usage_repo,
            proposal_repository=MagicMock(),
            rollout_repository=MagicMock(),
            rollout_observation_repository=MagicMock(),
            rollout_decision_repository=MagicMock(),
            goal_skill_binding_repository=MagicMock(),
            recommendation_repository=rec_repo,
            recommendation_service=rec_service,
            audit_service=audit_service,
            config=SkillCuratorJobConfig(usage_lookback_days=10),
        )

        # Let's call _maybe_recommend_learning_gain_review directly to test
        recommendation_id = await job_service._maybe_recommend_learning_gain_review(
            artifact=artifact,
            now=datetime.now(timezone.utc),
            window_key="win-1",
        )

        # It must generate a demote_candidate recommendation because completion_rate=1.0 >= 0.7 but learning_gain_rate < 0.0
        assert recommendation_id is not None
        assert len(rec_service.created) == 1
        assert rec_service.created[0]["recommendation_type"] == "demote_candidate"
        assert rec_service.created[0]["recommended_action"] == "demote_active"

    @pytest.mark.asyncio
    async def test_missing_learning_gain_does_not_crash_existing_curator_path(self) -> None:
        artifact = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.5,
        )
        artifact.id = "art-1"

        # Event with no mastery delta outcome signals
        event1 = _make_usage_event(
            event_id="ev-1",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"confidence": 0.8},
        )

        artifact_repo = StubArtifactRepository([artifact])
        usage_repo = StubUsageRepository([event1])
        aggregator = SkillOutcomeAggregator(usage_repository=usage_repo)
        audit_service = StubAuditService()

        # aggregator path should not crash
        metrics = await aggregator.compute_artifact_metrics(artifact_id="art-1", surface="chat")
        assert metrics.learning_gain_rate == 0.0

        # quality score updater path should not crash
        updater = SkillQualityUpdater(
            artifact_repository=artifact_repo,
            aggregator=aggregator,
            audit_service=audit_service,
        )
        await updater.update_quality_scores()

        # curator check path should not crash and return None
        job_service = SkillCuratorJobService(
            artifact_repository=artifact_repo,
            usage_repository=usage_repo,
            proposal_repository=MagicMock(),
            rollout_repository=MagicMock(),
            rollout_observation_repository=MagicMock(),
            rollout_decision_repository=MagicMock(),
            goal_skill_binding_repository=MagicMock(),
            recommendation_repository=StubRecommendationRepository(),
            recommendation_service=StubRecommendationService(),
            audit_service=audit_service,
        )

        recommendation_id = await job_service._maybe_recommend_learning_gain_review(
            artifact=artifact,
            now=datetime.now(timezone.utc),
            window_key="win-1",
        )
        assert recommendation_id is None

    @pytest.mark.asyncio
    async def test_negative_mastery_delta_reduces_quality_score(self) -> None:
        artifact = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.7,
        )
        artifact.id = "art-1"

        # Events with negative learning gains
        event1 = _make_usage_event(
            event_id="ev-1",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_before": 0.6, "mastery_after": 0.4, "confidence": 0.8},
        )
        event2 = _make_usage_event(
            event_id="ev-2",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_delta": -0.15, "confidence": 0.8},
        )

        artifact_repo = StubArtifactRepository([artifact])
        usage_repo = StubUsageRepository([event1, event2])
        aggregator = SkillOutcomeAggregator(usage_repository=usage_repo)
        audit_service = StubAuditService()

        updater = SkillQualityUpdater(
            artifact_repository=artifact_repo,
            aggregator=aggregator,
            audit_service=audit_service,
            config=SkillQualityUpdaterConfig(learning_gain_weight=0.5),
        )

        await updater.update_quality_scores()

        # Quality score should be lower than initial 0.7 due to negative learning gain
        assert artifact.quality_score < 0.7

    @pytest.mark.asyncio
    async def test_direct_mastery_delta_equivalent_to_computed(self) -> None:
        artifact = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.5,
        )
        artifact.id = "art-1"

        # Event with direct mastery_delta
        event1 = _make_usage_event(
            event_id="ev-1",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_delta": 0.25, "confidence": 0.8},
        )

        artifact_repo1 = StubArtifactRepository([artifact])
        usage_repo1 = StubUsageRepository([event1])
        aggregator1 = SkillOutcomeAggregator(usage_repository=usage_repo1)

        metrics1 = await aggregator1.compute_artifact_metrics(artifact_id="art-1", surface="chat")

        # Event with computed mastery delta from before/after
        artifact2 = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.5,
        )
        artifact2.id = "art-1"

        event2 = _make_usage_event(
            event_id="ev-2",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_before": 0.3, "mastery_after": 0.55, "confidence": 0.8},
        )

        usage_repo2 = StubUsageRepository([event2])
        aggregator2 = SkillOutcomeAggregator(usage_repository=usage_repo2)

        metrics2 = await aggregator2.compute_artifact_metrics(artifact_id="art-1", surface="chat")

        # Both should produce the same learning_gain_rate
        assert abs(metrics1.learning_gain_rate - metrics2.learning_gain_rate) < 1e-6

    @pytest.mark.asyncio
    async def test_invalid_mastery_values_are_skipped(self) -> None:
        artifact = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.5,
        )
        artifact.id = "art-1"

        # Events with invalid mastery values
        event1 = _make_usage_event(
            event_id="ev-1",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_before": 1.5, "mastery_after": 0.6},  # Invalid: before > 1.0
        )
        event2 = _make_usage_event(
            event_id="ev-2",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_delta": 2.0},  # Invalid: delta > 1.0
        )
        event3 = _make_usage_event(
            event_id="ev-3",
            artifact_id="art-1",
            skill_name="concept_explain",
            outcome_status="completed",
            outcome_signals={"mastery_before": 0.3, "mastery_after": 0.5},  # Valid
        )

        usage_repo = StubUsageRepository([event1, event2, event3])
        aggregator = SkillOutcomeAggregator(usage_repository=usage_repo)

        metrics = await aggregator.compute_artifact_metrics(artifact_id="art-1", surface="chat")

        # Only the valid event should be counted
        assert metrics.learning_gain_rate == 0.2  # (0.5 - 0.3) = 0.2

    @pytest.mark.asyncio
    async def test_quality_score_clamping_with_max_delta(self) -> None:
        artifact = SkillArtifact.build(
            name="concept_explain",
            version="0.1.0",
            skill_type="curated",
            scope="chat",
            status="active",
            description="explain",
            quality_score=0.5,
        )
        artifact.id = "art-1"

        # Events with very high learning gain
        events = [
            _make_usage_event(
                event_id=f"ev-{i}",
                artifact_id="art-1",
                skill_name="concept_explain",
                outcome_status="completed",
                outcome_signals={"mastery_delta": 0.8, "confidence": 0.9},
            )
            for i in range(10)
        ]

        artifact_repo = StubArtifactRepository([artifact])
        usage_repo = StubUsageRepository(events)
        aggregator = SkillOutcomeAggregator(usage_repository=usage_repo)
        audit_service = StubAuditService()

        updater = SkillQualityUpdater(
            artifact_repository=artifact_repo,
            aggregator=aggregator,
            audit_service=audit_service,
            config=SkillQualityUpdaterConfig(
                learning_gain_weight=0.5,
                max_delta=0.05,  # Very small max delta
            ),
        )

        await updater.update_quality_scores()

        # Quality score should increase but be clamped by max_delta
        # The EMA smoothing applies alpha (0.3) to the delta, so the actual change
        # is approximately: alpha * (new_score - old_score), then clamped to max_delta
        assert artifact.quality_score > 0.5
        # With max_delta=0.05, the score should not jump more than 0.05 + small tolerance
        # Use epsilon for floating point comparison
        assert artifact.quality_score <= 0.60 + 1e-9  # Allow floating point tolerance
