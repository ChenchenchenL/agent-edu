"""Tests for Phase 2 SkillRouterService.

Covers:
- Router contract objects
- Candidate source collection (with mock repos)
- Deterministic ranking and scoring
- Eligibility filtering (governance, staged, suppression)
- Low-confidence baseline fallback
- High failure rate forced fallback
- Rollback pressure penalty
- Explain output with winner and loser reasons
- Router integration with DynamicRuntimeRegistryService
- Observability metrics emission
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_core.application.services.skill.capability import CapabilityRequest
from agent_core.application.services.skill.router import (
    SkillRouterCandidate,
    SkillRouterDecision,
    SkillRouterRequest,
    SkillRouterService,
    TRUST_LEVELS,
    ROUTING_CONFIDENCE_THRESHOLDS,
)
from agent_core.application.services.skill.router_policy import SkillCandidateRanker
from agent_core.application.services.skill.router_sources import (
    ActiveArtifactCandidateSource,
    BaselineBuiltinCandidateSource,
    StagedArtifactCandidateSource,
)
from agent_core.application.services.dynamic_runtime_registry import (
    DynamicRuntimeRegistryService,
)
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    capability: str = "plan.generate",
    surface: str = "plan_generation",
    include_staged: bool = False,
) -> SkillRouterRequest:
    return SkillRouterRequest(
        capability_request=CapabilityRequest(
            capability=capability,
            surface=surface,
            learner_goal_id="goal-1",
        ),
        resource_id="res-1",
        include_staged=include_staged,
        learner_goal_id="goal-1",
    )


def _make_candidate(
    *,
    candidate_id: str = "active:art-1",
    source_type: str = "active_artifact",
    skill_name: str = "plan_study_path",
    eligible: bool = True,
    trust_level: int = 30,
    topic_coverage: float = 1.0,
    recent_usage_score: float = 0.8,
    failure_rate: float = 0.1,
    rollback_pressure: float = 0.0,
    surface: str = "plan_generation",
) -> SkillRouterCandidate:
    return SkillRouterCandidate(
        candidate_id=candidate_id,
        source_type=source_type,
        capability="plan.generate",
        artifact_id="art-1" if source_type != "baseline_builtin" else None,
        skill_name=skill_name,
        surface=surface,
        implementation_binding=skill_name,
        artifact_status="active" if source_type != "baseline_builtin" else "baseline",
        trust_level=trust_level,
        eligible=eligible,
        topic_coverage=topic_coverage,
        surface_compatibility=1.0,
        recent_usage_score=recent_usage_score,
        failure_rate=failure_rate,
        rollback_pressure=rollback_pressure,
    )


# ---------------------------------------------------------------------------
# Unit tests: Router contracts
# ---------------------------------------------------------------------------


class TestRouterContracts:
    def test_router_request_fields(self) -> None:
        req = _make_request()
        assert req.capability_request.capability == "plan.generate"
        assert req.include_staged is False

    def test_router_candidate_defaults(self) -> None:
        c = _make_candidate()
        assert c.eligible is True
        assert c.ineligible_reason_codes == []
        assert c.total_score == 0.0

    def test_trust_levels_ordered(self) -> None:
        assert TRUST_LEVELS["baseline_builtin"] > TRUST_LEVELS["active_governed"]
        assert TRUST_LEVELS["active_governed"] > TRUST_LEVELS["staged_probe"]
        assert TRUST_LEVELS["staged_probe"] > TRUST_LEVELS["external_installed"]


# ---------------------------------------------------------------------------
# Unit tests: Deterministic ranker
# ---------------------------------------------------------------------------


class TestSkillCandidateRanker:
    def test_high_usage_candidate_wins(self) -> None:
        ranker = SkillCandidateRanker()
        c1 = _make_candidate(candidate_id="c1", recent_usage_score=0.3)
        c2 = _make_candidate(candidate_id="c2", recent_usage_score=0.9)
        request = _make_request()
        ranked = ranker.rank([c1, c2], request)
        assert ranked[0].candidate_id == "c2"

    def test_high_failure_rate_penalised(self) -> None:
        ranker = SkillCandidateRanker()
        c1 = _make_candidate(candidate_id="c1", failure_rate=0.0)
        c2 = _make_candidate(candidate_id="c2", failure_rate=0.8)
        request = _make_request()
        ranked = ranker.rank([c1, c2], request)
        assert ranked[0].candidate_id == "c1"

    def test_rollback_pressure_penalised(self) -> None:
        ranker = SkillCandidateRanker()
        c1 = _make_candidate(candidate_id="c1", rollback_pressure=0.0)
        c2 = _make_candidate(candidate_id="c2", rollback_pressure=0.9)
        request = _make_request()
        ranked = ranker.rank([c1, c2], request)
        assert ranked[0].candidate_id == "c1"

    def test_trust_level_affects_ranking(self) -> None:
        ranker = SkillCandidateRanker()
        c1 = _make_candidate(
            candidate_id="c1",
            trust_level=TRUST_LEVELS["baseline_builtin"],
            recent_usage_score=0.5,
            topic_coverage=0.5,
        )
        c2 = _make_candidate(
            candidate_id="c2",
            trust_level=TRUST_LEVELS["external_installed"],
            recent_usage_score=0.5,
            topic_coverage=0.5,
        )
        request = _make_request()
        ranked = ranker.rank([c1, c2], request)
        assert ranked[0].candidate_id == "c1"

    def test_sub_scores_present(self) -> None:
        ranker = SkillCandidateRanker()
        c = _make_candidate()
        ranked = ranker.rank([c], _make_request())
        assert "topic_coverage" in ranked[0].sub_scores
        assert "failure_penalty" in ranked[0].sub_scores
        assert "trust" in ranked[0].sub_scores
        assert "rollback_penalty" in ranked[0].sub_scores
        assert ranked[0].total_score > 0


# ---------------------------------------------------------------------------
# Unit tests: Router service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSkillRouterService:
    async def test_active_artifact_wins_over_baseline(self) -> None:
        active = _make_candidate(
            candidate_id="active:art-1",
            source_type="active_artifact",
            recent_usage_score=0.9,
            failure_rate=0.05,
        )
        baseline = _make_candidate(
            candidate_id="baseline:plan_study_path",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
            recent_usage_score=0.5,
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [active, baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        decision = await router.decide(_make_request())
        assert decision.winner is not None
        assert decision.winner.source_type == "active_artifact"
        assert decision.baseline_used is False

    async def test_staged_candidate_excluded_without_include_staged(self) -> None:
        staged = _make_candidate(
            candidate_id="staged:art-2",
            source_type="staged_artifact",
            trust_level=TRUST_LEVELS["staged_probe"],
        )
        baseline = _make_candidate(
            candidate_id="baseline:plan_study_path",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [staged, baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        decision = await router.decide(_make_request(include_staged=False))
        assert decision.winner is not None
        assert decision.winner.source_type == "baseline_builtin"
        assert decision.baseline_used is True

    async def test_staged_candidate_participates_with_include_staged(self) -> None:
        staged = _make_candidate(
            candidate_id="staged:art-2",
            source_type="staged_artifact",
            trust_level=TRUST_LEVELS["staged_probe"],
            recent_usage_score=0.9,
            failure_rate=0.0,
        )
        baseline = _make_candidate(
            candidate_id="baseline:plan_study_path",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
            recent_usage_score=0.5,
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [staged, baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        decision = await router.decide(_make_request(include_staged=True))
        assert decision.winner is not None
        assert decision.winner.source_type == "staged_artifact"

    async def test_low_confidence_falls_back_to_baseline(self) -> None:
        weak = _make_candidate(
            candidate_id="active:weak",
            source_type="active_artifact",
            recent_usage_score=0.1,
            failure_rate=0.0,
            topic_coverage=0.1,
        )
        baseline = _make_candidate(
            candidate_id="baseline:plan_study_path",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [weak, baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        decision = await router.decide(_make_request())
        assert decision.winner is not None
        assert decision.baseline_used is True
        assert "low_confidence" in decision.fallback_chain or "insufficient_gap_over_baseline" in decision.fallback_chain

    async def test_high_failure_rate_forced_fallback(self) -> None:
        failing = _make_candidate(
            candidate_id="active:failing",
            source_type="active_artifact",
            failure_rate=0.8,
            recent_usage_score=0.9,
        )
        baseline = _make_candidate(
            candidate_id="baseline:plan_study_path",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [failing, baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        decision = await router.decide(_make_request())
        assert decision.winner is not None
        assert decision.baseline_used is True
        assert "high_failure_rate" in decision.fallback_chain

    async def test_ineligible_candidate_blocked(self) -> None:
        ineligible = _make_candidate(
            candidate_id="active:ineligible",
            source_type="active_artifact",
            eligible=False,
        )
        baseline = _make_candidate(
            candidate_id="baseline:plan_study_path",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [ineligible, baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        decision = await router.decide(_make_request())
        assert "active:ineligible" in decision.blocked_candidate_ids

    async def test_loser_reasons_present(self) -> None:
        c1 = _make_candidate(candidate_id="c1", recent_usage_score=0.9)
        c2 = _make_candidate(candidate_id="c2", recent_usage_score=0.3)
        baseline = _make_candidate(
            candidate_id="baseline",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
            recent_usage_score=0.5,
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [c1, c2, baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        decision = await router.decide(_make_request())
        assert decision.winner is not None
        assert decision.winner.candidate_id == "c1"
        assert "c2" in decision.loser_reason_map

    async def test_deterministic_results(self) -> None:
        c1 = _make_candidate(candidate_id="c1", recent_usage_score=0.8)
        c2 = _make_candidate(candidate_id="c2", recent_usage_score=0.6)

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [c1, c2]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )
        d1 = await router.decide(_make_request())
        d2 = await router.decide(_make_request())
        assert d1.winner.candidate_id == d2.winner.candidate_id
        assert d1.confidence == d2.confidence


# ---------------------------------------------------------------------------
# Unit tests: BaselineBuiltinCandidateSource
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBaselineBuiltinCandidateSource:
    async def test_collects_baseline_for_known_capability(self) -> None:
        registry = SkillRegistry.from_allowed_skills(["plan_study_path"])
        source = BaselineBuiltinCandidateSource(skill_registry=registry)
        request = _make_request()
        candidates = await source.collect(request)
        assert len(candidates) == 1
        assert candidates[0].source_type == "baseline_builtin"
        assert candidates[0].skill_name == "plan_study_path"
        assert candidates[0].trust_level == TRUST_LEVELS["baseline_builtin"]

    async def test_returns_empty_for_unknown_capability(self) -> None:
        registry = SkillRegistry.from_allowed_skills(["plan_study_path"])
        source = BaselineBuiltinCandidateSource(skill_registry=registry)
        request = _make_request(capability="unknown", surface="chat")
        candidates = await source.collect(request)
        assert candidates == []


# ---------------------------------------------------------------------------
# Integration tests: DynamicRuntimeRegistryService with router
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRegistryWithRouter:
    async def test_resolve_via_router(self) -> None:
        baseline = _make_candidate(
            candidate_id="baseline:plan_study_path",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [baseline]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        mock_plan = MagicMock(
            artifact_id=None,
            resolver_status="resolved",
            selection_reason="production_default",
            implementation_binding="plan_study_path",
            execution_kind="study_plan",
            runtime_directives={},
            tool_plan=[],
            binding_metadata={},
            resolution=MagicMock(
                skill_name="plan_study_path",
                surface="plan_generation",
                artifact_id=None,
                skill_version=None,
                artifact_status="baseline",
                resolver_status="missing_artifact",
                selection_reason="artifact_missing_static_fallback",
                implementation_binding="plan_study_path",
            ),
        )
        mock_usage = MagicMock()
        # Router path uses build_execution_plan_from_resolution, not resolve_execution_plan
        mock_usage.build_execution_plan_from_resolution = AsyncMock(return_value=mock_plan)

        registry = DynamicRuntimeRegistryService(
            goal_skill_binding_resolver=None,
            skill_usage_service=mock_usage,
            router=router,
        )

        request = CapabilityRequest(
            capability="plan.generate",
            surface="plan_generation",
            learner_goal_id="goal-1",
        )
        result = await registry.resolve_capability_request(request, resource_id="res-1")
        assert result is not None
        assert result.selection.resolution_mode == "deterministic_policy"
        assert result.selection.bridge_version == "router_v2"
        # Verify router_decision is propagated (Phase 2 explain requirement)
        assert result.router_decision is not None
        assert result.router_decision.baseline_used is True
        assert len(result.router_decision.ranked_candidates) >= 1
        # Verify build_execution_plan_from_resolution was used (not resolve_execution_plan)
        mock_usage.build_execution_plan_from_resolution.assert_awaited_once()
        call_kwargs = mock_usage.build_execution_plan_from_resolution.call_args.kwargs
        assert call_kwargs["resolution"].resolver_status == "missing_artifact"
        assert call_kwargs["resolution"].artifact_id is None


# ---------------------------------------------------------------------------
# Tests: Condition 7 — operator explain surfaces ranked_candidates and
#                       loser_reason_map (requires router_decision on plan)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExplainRouterDecision:
    """Verify that RuntimeExplainService exposes full router decision detail."""

    async def _make_registry_with_two_candidates(
        self,
    ) -> tuple[object, object]:  # (registry, mock_usage)
        winner = _make_candidate(
            candidate_id="active:art-1",
            source_type="active_artifact",
            recent_usage_score=0.9,
            failure_rate=0.05,
        )
        loser = _make_candidate(
            candidate_id="active:art-2",
            source_type="active_artifact",
            recent_usage_score=0.2,
            failure_rate=0.05,
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [winner, loser]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        mock_plan = MagicMock(
            artifact_id="art-1",
            resolver_status="resolved",
            implementation_binding="plan_study_path",
            execution_kind="study_plan",
            runtime_directives={},
            tool_plan=[],
            binding_metadata={},
            resolution=MagicMock(
                skill_name="plan_study_path",
                surface="plan_generation",
                artifact_id="art-1",
                skill_version=None,
                artifact_status="active",
                resolver_status="resolved",
                selection_reason="production_default",
                implementation_binding="plan_study_path",
            ),
        )
        mock_usage = MagicMock()
        mock_usage.build_execution_plan_from_resolution = AsyncMock(return_value=mock_plan)

        registry = DynamicRuntimeRegistryService(
            goal_skill_binding_resolver=None,
            skill_usage_service=mock_usage,
            router=router,
        )
        return registry, mock_usage

    async def test_router_decision_propagated_to_plan(self) -> None:
        registry, _ = await self._make_registry_with_two_candidates()
        request = CapabilityRequest(
            capability="plan.generate",
            surface="plan_generation",
            learner_goal_id="goal-1",
        )
        result = await registry.resolve_capability_request(request, resource_id="r1")
        assert result is not None
        assert result.router_decision is not None
        # Winner is the high-usage candidate
        assert result.router_decision.winner is not None
        assert result.router_decision.winner.candidate_id == "active:art-1"
        # Loser reasons must be populated
        assert "active:art-2" in result.router_decision.loser_reason_map
        # Ranked candidates must include both
        ids = [c.candidate_id for c in result.router_decision.ranked_candidates]
        assert "active:art-1" in ids
        assert "active:art-2" in ids

    async def test_explain_router_decision_includes_all_fields(self) -> None:
        """explain_router_decision() must expose ranked_candidates and loser_reason_map."""
        from agent_core.application.services.skill.runtime_explain import RuntimeExplainService

        registry, _ = await self._make_registry_with_two_candidates()
        svc = RuntimeExplainService(dynamic_runtime_registry=registry)
        request = CapabilityRequest(
            capability="plan.generate",
            surface="plan_generation",
            learner_goal_id="goal-1",
        )
        result = await svc.explain_router_decision(request)
        assert "router_decision" in result
        rd = result["router_decision"]
        assert rd is not None
        assert rd["baseline_used"] is False
        assert len(rd["ranked_candidates"]) >= 2
        assert "active:art-2" in rd["loser_reason_map"]
        # Each ranked candidate must have scoring detail
        winner_entry = next(c for c in rd["ranked_candidates"] if c["candidate_id"] == "active:art-1")
        assert "total_score" in winner_entry
        assert "sub_scores" in winner_entry

    async def test_explain_capability_includes_router_decision(self) -> None:
        """explain_capability() must also expose router_decision (condition 7)."""
        from agent_core.application.services.skill.runtime_explain import RuntimeExplainService

        registry, _ = await self._make_registry_with_two_candidates()
        svc = RuntimeExplainService(dynamic_runtime_registry=registry)
        request = CapabilityRequest(
            capability="plan.generate",
            surface="plan_generation",
            learner_goal_id="goal-1",
        )
        result = await svc.explain_capability(request)
        # Both explain entry points must expose the router decision
        assert "router_decision" in result
        rd = result["router_decision"]
        assert rd is not None
        assert "ranked_candidates" in rd
        assert "loser_reason_map" in rd
