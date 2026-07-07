import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from agent_core.application.services.skill.capability import CapabilityRequest
from agent_core.application.services.skill.router import (
    SkillRouterCandidate,
    SkillRouterDecision,
    SkillRouterRequest,
    SkillRouterService,
    TRUST_LEVELS,
)
from agent_core.application.services.skill.router_policy import SkillCandidateRanker
from agent_core.application.services.dynamic_runtime_registry import (
    DynamicRuntimeRegistryService,
)
from agent_core.domain.entities.learner.autonomy import LearnerTopicMastery
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution


class StubTopicMasteryRepository:
    def __init__(self, masteries=None):
        self.masteries = masteries or {}

    async def get_by_goal_and_topic(self, learner_goal_id, topic_key):
        return self.masteries.get((learner_goal_id, topic_key))


def _make_candidate(
    *,
    candidate_id: str,
    source_type: str,
    skill_name: str = "plan_study_path",
    eligible: bool = True,
    trust_level: int = 30,
    topic_coverage: float = 1.0,
    recent_usage_score: float = 0.8,
    failure_rate: float = 0.0,
    rollback_pressure: float = 0.0,
    compatibility_contract: dict = None,
) -> SkillRouterCandidate:
    return SkillRouterCandidate(
        candidate_id=candidate_id,
        source_type=source_type,
        capability="plan.generate",
        artifact_id="art-1" if source_type != "baseline_builtin" else None,
        skill_name=skill_name,
        surface="plan_generation",
        implementation_binding=skill_name,
        artifact_status="active" if source_type != "baseline_builtin" else "baseline",
        trust_level=trust_level,
        eligible=eligible,
        topic_coverage=topic_coverage,
        surface_compatibility=1.0,
        recent_usage_score=recent_usage_score,
        failure_rate=failure_rate,
        rollback_pressure=rollback_pressure,
        compatibility_contract=compatibility_contract or {},
    )


class TestPhase6MasteryRouting:
    @pytest.mark.asyncio
    async def test_low_mastery_selects_remedial_artifact(self) -> None:
        # Remedial candidate (remediation=True)
        remedial_candidate = _make_candidate(
            candidate_id="external:remedial-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "remediation": True,
                    "supported_mastery_bands": ["novice", "developing"]
                }
            }
        )
        
        # Standard candidate (supported bands: confident)
        standard_candidate = _make_candidate(
            candidate_id="external:standard-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "supported_mastery_bands": ["confident"]
                }
            }
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [remedial_candidate, standard_candidate]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        # For "novice" mastery band (low mastery)
        request = SkillRouterRequest(
            capability_request=CapabilityRequest(
                capability="plan.generate",
                surface="plan_generation",
                learner_goal_id="goal-1",
            ),
            resource_id="res-1",
            mastery_band="novice",
        )

        decision = await router.decide(request)
        assert decision.winner is not None
        assert decision.winner.candidate_id == "external:remedial-1"

    @pytest.mark.asyncio
    async def test_high_mastery_avoids_remedial_only_artifact(self) -> None:
        # Remedial candidate (remediation=True)
        remedial_candidate = _make_candidate(
            candidate_id="external:remedial-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "remediation": True,
                    "supported_mastery_bands": ["novice"]
                }
            }
        )
        
        # Standard candidate (supported bands: confident)
        standard_candidate = _make_candidate(
            candidate_id="external:standard-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "supported_mastery_bands": ["confident"]
                }
            }
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [remedial_candidate, standard_candidate]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        # For "confident" mastery band (high mastery)
        request = SkillRouterRequest(
            capability_request=CapabilityRequest(
                capability="plan.generate",
                surface="plan_generation",
                learner_goal_id="goal-1",
            ),
            resource_id="res-1",
            mastery_band="confident",
        )

        decision = await router.decide(request)
        assert decision.winner is not None
        assert decision.winner.candidate_id == "external:standard-1"

    @pytest.mark.asyncio
    async def test_missing_mastery_falls_back_safely(self) -> None:
        # Baseline candidate
        baseline_candidate = _make_candidate(
            candidate_id="baseline:plan_study_path:plan_generation",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [baseline_candidate]

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
        mock_usage.build_execution_plan_from_resolution = AsyncMock(return_value=mock_plan)

        # Injecting empty topic mastery repo (missing mastery)
        registry = DynamicRuntimeRegistryService(
            goal_skill_binding_resolver=None,
            skill_usage_service=mock_usage,
            router=router,
            topic_mastery_repository=StubTopicMasteryRepository({}),
        )

        request = CapabilityRequest(
            capability="plan.generate",
            surface="plan_generation",
            learner_goal_id="goal-1",
            topic_key="topic-1",
        )

        result = await registry.resolve_capability_request(request, resource_id="res-1")
        assert result is not None
        assert "mastery_band_missing" in result.selection.reason_codes
        # Verification that standard baseline was picked and not blocked
        assert result.router_decision.winner.candidate_id == "baseline:plan_study_path:plan_generation"

    @pytest.mark.asyncio
    async def test_staged_artifact_does_not_bypass_include_staged_false(self) -> None:
        staged_candidate = _make_candidate(
            candidate_id="staged:art-1",
            source_type="staged_artifact",
            compatibility_contract={
                "match_rules": {
                    "supported_mastery_bands": ["novice"]
                }
            }
        )
        
        baseline_candidate = _make_candidate(
            candidate_id="baseline:plan_study_path:plan_generation",
            source_type="baseline_builtin",
            trust_level=TRUST_LEVELS["baseline_builtin"],
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [staged_candidate, baseline_candidate]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        # Low mastery, should fit staged_candidate perfectly, but include_staged is False
        request = SkillRouterRequest(
            capability_request=CapabilityRequest(
                capability="plan.generate",
                surface="plan_generation",
                learner_goal_id="goal-1",
            ),
            resource_id="res-1",
            mastery_band="novice",
            include_staged=False,
        )

        decision = await router.decide(request)
        # Winner must be baseline, staged is excluded
        assert decision.winner is not None
        assert decision.winner.candidate_id == "baseline:plan_study_path:plan_generation"

    @pytest.mark.asyncio
    async def test_developing_mastery_band_routing(self) -> None:
        remedial_candidate = _make_candidate(
            candidate_id="external:remedial-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "remediation": True,
                    "supported_mastery_bands": ["novice"],
                }
            },
        )
        developing_candidate = _make_candidate(
            candidate_id="external:developing-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "supported_mastery_bands": ["developing", "confident"],
                }
            },
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [remedial_candidate, developing_candidate]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        request = SkillRouterRequest(
            capability_request=CapabilityRequest(
                capability="plan.generate",
                surface="plan_generation",
                learner_goal_id="goal-1",
            ),
            resource_id="res-1",
            mastery_band="developing",
        )

        decision = await router.decide(request)
        assert decision.winner is not None
        assert decision.winner.candidate_id == "external:developing-1"

    @pytest.mark.asyncio
    async def test_multiple_remediation_artifacts_compete(self) -> None:
        remedial_a = _make_candidate(
            candidate_id="external:remedial-a",
            source_type="tenant_external",
            recent_usage_score=0.6,
            compatibility_contract={
                "match_rules": {
                    "remediation": True,
                    "supported_mastery_bands": ["novice", "developing"],
                }
            },
        )
        remedial_b = _make_candidate(
            candidate_id="external:remedial-b",
            source_type="tenant_external",
            recent_usage_score=0.9,
            compatibility_contract={
                "match_rules": {
                    "remediation": True,
                    "supported_mastery_bands": ["novice", "developing"],
                }
            },
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [remedial_a, remedial_b]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        request = SkillRouterRequest(
            capability_request=CapabilityRequest(
                capability="plan.generate",
                surface="plan_generation",
                learner_goal_id="goal-1",
            ),
            resource_id="res-1",
            mastery_band="novice",
        )

        decision = await router.decide(request)
        assert decision.winner is not None
        assert decision.winner.candidate_id == "external:remedial-b"

    @pytest.mark.asyncio
    async def test_excluded_mastery_bands_filtering(self) -> None:
        excluded_candidate = _make_candidate(
            candidate_id="external:excluded-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "excluded_mastery_bands": ["confident"],
                }
            },
        )
        standard_candidate = _make_candidate(
            candidate_id="external:standard-1",
            source_type="tenant_external",
            compatibility_contract={},
        )

        class MockSource:
            source_type = "mock"
            async def collect(self, request):
                return [excluded_candidate, standard_candidate]

        router = SkillRouterService(
            sources=[MockSource()],
            ranker=SkillCandidateRanker(),
        )

        request = SkillRouterRequest(
            capability_request=CapabilityRequest(
                capability="plan.generate",
                surface="plan_generation",
                learner_goal_id="goal-1",
            ),
            resource_id="res-1",
            mastery_band="confident",
        )

        decision = await router.decide(request)
        assert decision.winner is not None
        assert decision.winner.candidate_id == "external:standard-1"

    @pytest.mark.asyncio
    async def test_standard_band_uses_candidate_default_mastery_fit(self) -> None:
        from agent_core.application.services.skill.router_policy import _mastery_band_fit

        candidate = _make_candidate(
            candidate_id="external:test-1",
            source_type="tenant_external",
            compatibility_contract={
                "match_rules": {
                    "remediation": True,
                }
            },
        )

        fit = _mastery_band_fit("standard", candidate)
        assert fit == candidate.mastery_fit
