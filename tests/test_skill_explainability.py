"""Tests for Phase 8: Explainability and Operator Drill-Down."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from agent_core.application.services.skill.artifact_timeline import ArtifactTimeline, SkillArtifactTimelineService
from agent_core.application.services.skill.rollout_drilldown import RolloutDrillDownService, RolloutDrillDownSummary
from agent_core.application.services.skill.runtime_explain import RuntimeExplainService
from agent_core.domain.entities.skill import SkillArtifact, SkillCuratorRecommendation, SkillUsageEvent
from agent_core.domain.schemas.skill import (
    ArtifactTimelineResponse,
    FallbackTraceResponse,
    RolloutDrillDownResponse,
    RouterExplainResponse,
)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

class _StubArtifactRepo:
    def __init__(self, artifacts: list[SkillArtifact] | None = None) -> None:
        self.artifacts = artifacts or []

    async def get_by_id(self, artifact_id: str) -> SkillArtifact | None:
        for a in self.artifacts:
            if a.id == artifact_id:
                return a
        return None

    async def list_artifacts(self, **kwargs: Any) -> list[SkillArtifact]:
        return self.artifacts


class _StubAuditRepo:
    def __init__(self, events: list[Any] | None = None) -> None:
        self._events = events or []

    async def list_events(self, *, resource_type: str | None = None, limit: int = 200, **kwargs: Any) -> list[Any]:
        if resource_type:
            return [e for e in self._events if e.resource_type == resource_type][:limit]
        return self._events[:limit]


class _StubUsageRepo:
    def __init__(self, events: list[SkillUsageEvent] | None = None) -> None:
        self._events = events or []

    async def list_events(self, *, artifact_id: str | None = None, skill_name: str | None = None, surface: str | None = None, limit: int = 50, **kwargs: Any) -> list[SkillUsageEvent]:
        result = self._events
        if artifact_id:
            result = [e for e in result if e.skill_artifact_id == artifact_id]
        if skill_name:
            result = [e for e in result if e.skill_name == skill_name]
        if surface:
            result = [e for e in result if e.surface == surface]
        return result[:limit]


class _StubRecommendationRepo:
    def __init__(self, recs: list[SkillCuratorRecommendation] | None = None) -> None:
        self._recs = recs or []

    async def list_recommendations(self, *, artifact_id: str | None = None, limit: int = 20, **kwargs: Any) -> list[SkillCuratorRecommendation]:
        result = self._recs
        if artifact_id:
            result = [r for r in result if r.artifact_id == artifact_id]
        return result[:limit]


class _StubRolloutRepo:
    def __init__(self, rollouts: list[Any] | None = None) -> None:
        self._rollouts = rollouts or []

    async def get_by_id(self, rollout_id: str) -> Any | None:
        for r in self._rollouts:
            if r.id == rollout_id:
                return r
        return None


class _StubObservationRepo:
    def __init__(self, observations: list[Any] | None = None) -> None:
        self._observations = observations or []

    async def list_by_rollout(self, rollout_id: str) -> list[Any]:
        return [o for o in self._observations if o.rollout_id == rollout_id]


class _StubDecisionRepo:
    def __init__(self, decisions: list[Any] | None = None) -> None:
        self._decisions = decisions or []

    async def list_by_rollout(self, rollout_id: str) -> list[Any]:
        return [d for d in self._decisions if d.rollout_id == rollout_id]


class _StubProposalRepo:
    def __init__(self, proposals: list[Any] | None = None) -> None:
        self._proposals = proposals or []

    async def get_by_id(self, proposal_id: str) -> Any | None:
        for p in self._proposals:
            if p.id == proposal_id:
                return p
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeAuditEvent:
    event_type: str
    resource_type: str
    resource_id: str | None
    actor: str
    event_data: dict[str, Any]
    created_at: datetime


@dataclass
class _FakeRollout:
    id: str
    proposal_id: str
    status: str
    activated_at: datetime | None = None
    promoted_at: datetime | None = None
    rolled_back_at: datetime | None = None


@dataclass
class _FakeObservation:
    id: str
    rollout_id: str
    recommendation: str
    positive_score: float
    negative_score: float
    observed_sample_count: int
    signal_summary: dict[str, Any]
    reason_codes: list[str]
    created_at: datetime


@dataclass
class _FakeDecision:
    id: str
    rollout_id: str
    decision_type: str
    previous_status: str
    new_status: str
    reason_code: str
    operator_id: str
    created_at: datetime


@dataclass
class _FakeProposal:
    id: str
    proposal_type: str
    status: str
    hypothesis: str
    evaluation_status: str
    risk_level: str
    target_scope: str


def _make_artifact(artifact_id: str = "art-1") -> SkillArtifact:
    from dataclasses import replace
    base = SkillArtifact.build(
        name="test_skill", version="1.0.0", skill_type="curated",
        scope="chat", status="active", description="test", quality_score=0.7,
    )
    return replace(base, id=artifact_id, lineage_id=artifact_id)


# ===========================================================================
# Artifact Timeline
# ===========================================================================


class TestArtifactTimeline:
    @pytest.mark.asyncio
    async def test_build_timeline(self) -> None:
        artifact = _make_artifact()
        audit_events = [
            _FakeAuditEvent(
                event_type="skill.artifact.activated",
                resource_type="skill_artifact",
                resource_id=artifact.id,
                actor="operator:test",
                event_data={"artifact_id": artifact.id},
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
            _FakeAuditEvent(
                event_type="skill.quality_score.updated",
                resource_type="skill_artifact",
                resource_id=artifact.id,
                actor="system:outcome_feedback",
                event_data={"artifact_id": artifact.id, "old_score": 0.5, "new_score": 0.7},
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            _FakeAuditEvent(
                event_type="skill.artifact.suppressed",
                resource_type="skill_artifact",
                resource_id=artifact.id,
                actor="operator:test",
                event_data={"artifact_id": artifact.id, "reason_code": "safety_review"},
                created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
            ),
        ]
        usage_events = [
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id, skill_name="test_skill",
                skill_version="1.0.0", skill_status_at_use="active",
                surface="chat", outcome_status="completed",
            ),
            SkillUsageEvent.build(
                skill_artifact_id=artifact.id, skill_name="test_skill",
                skill_version="1.0.0", skill_status_at_use="active",
                surface="chat", outcome_status="failed",
            ),
        ]

        svc = SkillArtifactTimelineService(
            artifact_repository=_StubArtifactRepo([artifact]),
            audit_repository=_StubAuditRepo(audit_events),
            usage_repository=_StubUsageRepo(usage_events),
            recommendation_repository=_StubRecommendationRepo(),
        )
        timeline = await svc.build_timeline(artifact.id)
        assert timeline.artifact_id == artifact.id
        assert timeline.artifact_summary["status"] == "active"
        assert timeline.usage_summary["total_events"] == 2
        assert len(timeline.quality_history) == 1
        assert len(timeline.suppression_history) == 1
        assert len(timeline.lifecycle_events) >= 2

    @pytest.mark.asyncio
    async def test_artifact_not_found(self) -> None:
        from agent_core.domain.errors import NotFoundError
        svc = SkillArtifactTimelineService(
            artifact_repository=_StubArtifactRepo([]),
            audit_repository=_StubAuditRepo(),
            usage_repository=_StubUsageRepo(),
            recommendation_repository=_StubRecommendationRepo(),
        )
        with pytest.raises(NotFoundError):
            await svc.build_timeline("nonexistent")


# ===========================================================================
# Rollout Drill-Down
# ===========================================================================


class TestRolloutDrillDown:
    @pytest.mark.asyncio
    async def test_build_summary(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rollout = _FakeRollout(
            id="rollout-1", proposal_id="prop-1", status="rolled_out",
            activated_at=now, promoted_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
        )
        proposal = _FakeProposal(
            id="prop-1", proposal_type="skill_package", status="approved",
            hypothesis="Improve chat response", evaluation_status="effective",
            risk_level="low", target_scope="chat",
        )
        observations = [
            _FakeObservation(
                id="obs-1", rollout_id="rollout-1", recommendation="collecting",
                positive_score=0.6, negative_score=0.2, observed_sample_count=3,
                signal_summary={}, reason_codes=[],
                created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            ),
            _FakeObservation(
                id="obs-2", rollout_id="rollout-1", recommendation="promote",
                positive_score=0.8, negative_score=0.1, observed_sample_count=5,
                signal_summary={}, reason_codes=["task_completed"],
                created_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
            ),
        ]
        decisions = [
            _FakeDecision(
                id="dec-1", rollout_id="rollout-1", decision_type="activate",
                previous_status="proposed", new_status="staged",
                reason_code="auto_approved", operator_id="system",
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            ),
        ]

        svc = RolloutDrillDownService(
            rollout_repository=_StubRolloutRepo([rollout]),
            observation_repository=_StubObservationRepo(observations),
            decision_repository=_StubDecisionRepo(decisions),
            proposal_repository=_StubProposalRepo([proposal]),
            usage_repository=_StubUsageRepo(),
        )
        summary = await svc.build_summary("rollout-1")
        assert summary.rollout_id == "rollout-1"
        assert summary.current_status == "rolled_out"
        assert summary.proposal_summary["hypothesis"] == "Improve chat response"
        assert len(summary.observation_timeline) == 2
        assert len(summary.decision_timeline) == 1
        assert summary.duration_days > 0

    @pytest.mark.asyncio
    async def test_rollout_not_found(self) -> None:
        from agent_core.domain.errors import NotFoundError
        svc = RolloutDrillDownService(
            rollout_repository=_StubRolloutRepo(),
            observation_repository=_StubObservationRepo(),
            decision_repository=_StubDecisionRepo(),
            proposal_repository=_StubProposalRepo(),
            usage_repository=_StubUsageRepo(),
        )
        with pytest.raises(NotFoundError):
            await svc.build_summary("nonexistent")


# ===========================================================================
# Fallback Trace
# ===========================================================================


class TestFallbackTrace:
    @pytest.mark.asyncio
    async def test_trace_fallback(self) -> None:
        usage_events = [
            SkillUsageEvent.build(
                skill_artifact_id="art-1", skill_name="test_skill",
                skill_version="1.0.0", skill_status_at_use="active",
                surface="chat", outcome_status="completed",
                selection_reason="production_default",
                metadata={"fallback_chain": ["baseline_fallback"], "confidence": 0.3},
            ),
            SkillUsageEvent.build(
                skill_artifact_id="art-1", skill_name="test_skill",
                skill_version="1.0.0", skill_status_at_use="active",
                surface="chat", outcome_status="completed",
                selection_reason="production_default",
            ),
            SkillUsageEvent.build(
                skill_artifact_id="art-1", skill_name="test_skill",
                skill_version="1.0.0", skill_status_at_use="active",
                surface="chat", outcome_status="failed",
                selection_reason="artifact_missing_static_fallback",
                error_code="timeout",
            ),
        ]

        @dataclass
        class _FakeRegistry:
            async def resolve_capability_request(self, *args: Any, **kwargs: Any) -> None:
                return None

        svc = RuntimeExplainService(
            dynamic_runtime_registry=_FakeRegistry(),
            usage_repository=_StubUsageRepo(usage_events),
        )
        result = await svc.trace_fallback(skill_name="test_skill", surface="chat")
        assert result["total_events"] == 3
        assert result["fallback_rate"] > 0
        assert result["baseline_reliance_rate"] > 0
        assert len(result["common_failure_reasons"]) >= 1


# ===========================================================================
# Schema Validation
# ===========================================================================


class TestSchemaValidation:
    def test_router_explain_response(self) -> None:
        resp = RouterExplainResponse(
            request={"capability": "chat.respond", "surface": "chat"},
            bridge={"mapped": True},
            selection=None,
            router_decision=None,
        )
        assert resp.request["capability"] == "chat.respond"

    def test_artifact_timeline_response(self) -> None:
        resp = ArtifactTimelineResponse(
            artifact_id="art-1",
            artifact_summary={"status": "active"},
            lifecycle_events=[],
            usage_summary={"total_events": 0},
            quality_history=[],
            related_proposal_ids=[],
            suppression_history=[],
            recommendation_history=[],
        )
        assert resp.artifact_id == "art-1"

    def test_rollout_drilldown_response(self) -> None:
        resp = RolloutDrillDownResponse(
            rollout_id="r-1",
            proposal_summary={},
            observation_timeline=[],
            decision_timeline=[],
            usage_attribution={},
            signal_trend={},
            current_status="staged",
            duration_days=0.0,
        )
        assert resp.current_status == "staged"

    def test_fallback_trace_response(self) -> None:
        resp = FallbackTraceResponse(
            skill_name="s",
            surface="chat",
            total_events=0,
            fallback_history=[],
            fallback_rate=0.0,
            baseline_reliance_rate=0.0,
            common_failure_reasons=[],
        )
        assert resp.fallback_rate == 0.0
