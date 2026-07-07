"""Tests for Phase 1 capability-driven runtime contracts.

Three layers:
- Unit tests: bridge catalog, CapabilityRequestBridge, selection generation
- Service tests: DynamicRuntimeRegistryService capability entry + bridge
- Scenario test: planner path no longer explicitly passes skill_name
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from agent_core.application.services.skill.capability import (
    CAPABILITY_BRIDGE_VERSION,
    CapabilityRequest,
    CapabilitySelection,
    RuntimeCapabilityExecutionPlan,
)
from agent_core.application.services.skill.capability_bridge import CapabilityRequestBridge
from agent_core.application.services.skill.capability_catalog import (
    get_bridge_entry,
    list_capabilities,
    resolve_capability_to_legacy,
    reverse_lookup,
)
from agent_core.application.services.dynamic_runtime_registry import (
    DynamicRuntimeRegistryService,
    RuntimeSkillExecutionPlan,
)
from agent_core.application.services.goal_skill_binding_resolver import ActiveGoalSkillBinding
from agent_core.application.services.skill.resolution import SkillResolver
from agent_core.application.services.skill.usage import SkillUsageService
from agent_core.application.skills.registry import SkillRegistry
from agent_core.domain.entities.skill import SkillExecutionPlan, SkillResolution


# ---------------------------------------------------------------------------
# Unit tests: capability catalog
# ---------------------------------------------------------------------------


class TestCapabilityCatalog:
    def test_known_capabilities_resolve(self) -> None:
        result = resolve_capability_to_legacy("chat.respond", surface="chat")
        assert result == ("explain_concept", "chat")

    def test_plan_generate_resolves_for_both_surfaces(self) -> None:
        assert resolve_capability_to_legacy("plan.generate", surface="plan_generation") == (
            "plan_study_path",
            "plan_generation",
        )
        assert resolve_capability_to_legacy("plan.generate", surface="replan") == (
            "plan_study_path",
            "replan",
        )

    def test_unknown_capability_returns_none(self) -> None:
        assert resolve_capability_to_legacy("nonexistent.capability") is None

    def test_unsupported_surface_returns_none(self) -> None:
        assert resolve_capability_to_legacy("chat.respond", surface="quiz") is None

    def test_default_surface_used_when_none_given(self) -> None:
        result = resolve_capability_to_legacy("hint.adaptive")
        assert result == ("adaptive_hint", "hint")

    def test_reverse_lookup_finds_capability(self) -> None:
        assert reverse_lookup("explain_concept", "chat") == "chat.respond"
        assert reverse_lookup("plan_study_path", "plan_generation") == "plan.generate"
        assert reverse_lookup("plan_study_path", "replan") == "plan.generate"
        assert reverse_lookup("create_quiz", "quiz") == "assessment.generate"
        assert reverse_lookup("schedule_review", "review_scheduling") == "review.schedule"

    def test_reverse_lookup_returns_none_for_unknown(self) -> None:
        assert reverse_lookup("nonexistent_skill", "chat") is None

    def test_get_bridge_entry_returns_entry(self) -> None:
        entry = get_bridge_entry("chat.respond")
        assert entry is not None
        assert entry.legacy_skill_name == "explain_concept"

    def test_list_capabilities_returns_all_entries(self) -> None:
        caps = list_capabilities()
        assert len(caps) == 5
        names = {c.capability for c in caps}
        assert names == {
            "chat.respond",
            "hint.adaptive",
            "assessment.generate",
            "plan.generate",
            "review.schedule",
        }


# ---------------------------------------------------------------------------
# Unit tests: CapabilityRequestBridge
# ---------------------------------------------------------------------------


class TestCapabilityRequestBridge:
    def test_to_legacy_inputs_known_capability(self) -> None:
        request = CapabilityRequest(
            capability="plan.generate",
            surface="plan_generation",
            learner_goal_id="goal-1",
            topic_key="math",
        )
        result = CapabilityRequestBridge.to_legacy_inputs(request)
        assert result is not None
        assert result["skill_name"] == "plan_study_path"
        assert result["surface"] == "plan_generation"
        assert result["learner_goal_id"] == "goal-1"
        assert result["topic_key"] == "math"

    def test_to_legacy_inputs_unknown_capability_returns_none(self) -> None:
        request = CapabilityRequest(capability="unknown", surface="chat")
        assert CapabilityRequestBridge.to_legacy_inputs(request) is None

    def test_build_selection_resolved(self) -> None:
        request = CapabilityRequest(capability="chat.respond", surface="chat")
        selection = CapabilityRequestBridge.build_selection(
            request,
            artifact_id="art-1",
            resolver_status="resolved",
            selection_reason="production_default",
        )
        assert selection.requested_capability == "chat.respond"
        assert selection.selected_capability == "explain_concept"
        assert selection.selected_artifact_id == "art-1"
        assert selection.legacy_skill_name == "explain_concept"
        assert selection.confidence == 1.0
        assert "production_default" in selection.reason_codes
        assert selection.bridge_version == CAPABILITY_BRIDGE_VERSION
        assert selection.resolution_mode == "legacy_bridge"

    def test_build_selection_missing_artifact_has_fallback(self) -> None:
        request = CapabilityRequest(capability="chat.respond", surface="chat")
        selection = CapabilityRequestBridge.build_selection(
            request,
            artifact_id=None,
            resolver_status="missing_artifact",
            selection_reason="artifact_missing_static_fallback",
        )
        assert selection.confidence == 0.5
        assert "static_fallback" in selection.fallback_chain

    def test_build_selection_binding_applied(self) -> None:
        request = CapabilityRequest(capability="plan.generate", surface="plan_generation")
        selection = CapabilityRequestBridge.build_selection(
            request,
            artifact_id="art-2",
            resolver_status="resolved",
            selection_reason="production_default",
            binding_applied=True,
        )
        assert "binding_overlay_applied" in selection.reason_codes

    def test_build_selection_with_tool_plan_template(self) -> None:
        request = CapabilityRequest(capability="review.schedule", surface="review_scheduling")
        selection = CapabilityRequestBridge.build_selection(
            request,
            artifact_id="art-3",
            resolver_status="resolved",
            selection_reason="production_default",
            tool_plan=[{"tool_name": "schedule_review_tool", "payload": {}}],
        )
        assert selection.tool_plan_template_id == "review.schedule:schedule_review_tool"


# ---------------------------------------------------------------------------
# Unit tests: SkillRegistry capability methods
# ---------------------------------------------------------------------------


class TestSkillRegistryCapability:
    def _make_registry(self) -> SkillRegistry:
        return SkillRegistry.from_allowed_skills([
            "explain_concept",
            "adaptive_hint",
            "create_quiz",
            "plan_study_path",
            "schedule_review",
        ])

    def test_default_skill_for_capability(self) -> None:
        registry = self._make_registry()
        assert registry.default_skill_for_capability("chat.respond", "chat") == "explain_concept"
        assert registry.default_skill_for_capability("plan.generate", "plan_generation") == "plan_study_path"

    def test_default_skill_for_unknown_capability(self) -> None:
        registry = self._make_registry()
        assert registry.default_skill_for_capability("nonexistent", "chat") is None

    def test_supports_capability(self) -> None:
        registry = self._make_registry()
        assert registry.supports_capability("chat.respond", "chat") is True
        assert registry.supports_capability("nonexistent", "chat") is False

    def test_default_handler_for_capability(self) -> None:
        registry = self._make_registry()
        handler = registry.default_handler_for_capability("chat.respond", "chat")
        assert handler == "explain_concept"

    def test_capability_not_enabled_in_registry(self) -> None:
        registry = SkillRegistry.from_allowed_skills(["explain_concept"])
        assert registry.default_skill_for_capability("plan.generate", "plan_generation") is None


# ---------------------------------------------------------------------------
# Service tests: DynamicRuntimeRegistryService capability entry
# ---------------------------------------------------------------------------


def _build_resolution(
    *,
    skill_name: str = "plan_study_path",
    surface: str = "plan_generation",
    artifact_id: str | None = None,
    resolver_status: str = "resolved",
    selection_reason: str = "production_default",
) -> SkillResolution:
    return SkillResolution.build(
        skill_name=skill_name,
        surface=surface,
        artifact_id=artifact_id,
        skill_version=None,
        artifact_status="active" if artifact_id else None,
        resolver_status=resolver_status,
        selection_reason=selection_reason,
        implementation_binding=skill_name,
    )


def _build_execution_plan(
    resolution: SkillResolution | None = None,
) -> SkillExecutionPlan:
    resolution = resolution or _build_resolution()
    return SkillExecutionPlan(
        resolution=resolution,
        execution_kind="study_plan",
        runtime_directives={},
        tool_plan=[],
        binding_metadata={},
    )


@pytest.mark.asyncio
class TestDynamicRuntimeRegistryCapability:
    async def test_resolve_capability_request_success(self) -> None:
        mock_usage_service = MagicMock(spec=SkillUsageService)
        mock_usage_service.resolve_execution_plan = AsyncMock(
            return_value=_build_execution_plan()
        )

        service = DynamicRuntimeRegistryService(
            goal_skill_binding_resolver=None,
            skill_usage_service=mock_usage_service,
        )

        request = CapabilityRequest(
            capability="plan.generate",
            surface="plan_generation",
            learner_goal_id="goal-1",
        )
        result = await service.resolve_capability_request(request, resource_id="res-1")

        assert result is not None
        assert isinstance(result, RuntimeCapabilityExecutionPlan)
        assert result.selection.requested_capability == "plan.generate"
        assert result.selection.selected_capability == "plan_study_path"
        assert result.selection.legacy_skill_name == "plan_study_path"
        assert result.request is request

        mock_usage_service.resolve_execution_plan.assert_awaited_once()
        call_kwargs = mock_usage_service.resolve_execution_plan.call_args.kwargs
        assert call_kwargs["skill_name"] == "plan_study_path"
        assert call_kwargs["surface"] == "plan_generation"

    async def test_resolve_capability_request_unknown_capability(self) -> None:
        mock_usage_service = MagicMock(spec=SkillUsageService)
        service = DynamicRuntimeRegistryService(
            goal_skill_binding_resolver=None,
            skill_usage_service=mock_usage_service,
        )
        request = CapabilityRequest(capability="unknown", surface="chat")
        result = await service.resolve_capability_request(request, resource_id="res-1")
        assert result is None

    async def test_resolve_capability_request_no_usage_service(self) -> None:
        service = DynamicRuntimeRegistryService(
            goal_skill_binding_resolver=None,
            skill_usage_service=None,
        )
        request = CapabilityRequest(capability="chat.respond", surface="chat")
        result = await service.resolve_capability_request(request, resource_id="res-1")
        assert result is None

    async def test_legacy_resolve_runtime_plan_bridges_to_capability(self) -> None:
        mock_usage_service = MagicMock(spec=SkillUsageService)
        mock_usage_service.resolve_execution_plan = AsyncMock(
            return_value=_build_execution_plan()
        )

        service = DynamicRuntimeRegistryService(
            goal_skill_binding_resolver=None,
            skill_usage_service=mock_usage_service,
        )

        result = await service.resolve_runtime_plan(
            learner_goal_id="goal-1",
            skill_name="plan_study_path",
            surface="plan_generation",
            resource_id="res-1",
        )

        assert result is not None
        assert isinstance(result, RuntimeSkillExecutionPlan)
        mock_usage_service.resolve_execution_plan.assert_awaited_once()

    async def test_runtime_metadata_includes_capability(self) -> None:
        plan = _build_execution_plan()
        runtime_plan = DynamicRuntimeRegistryService.build_runtime_plan(
            plan=plan, binding=None
        )
        selection = CapabilitySelection(
            requested_capability="plan.generate",
            selected_artifact_id=None,
            selected_capability="plan_study_path",
            reason_codes=["production_default"],
            legacy_skill_name="plan_study_path",
        )

        metadata = DynamicRuntimeRegistryService.runtime_metadata_for_usage(
            runtime_plan,
            capability_selection=selection,
        )
        assert "capability" in metadata
        cap = metadata["capability"]
        assert cap["requested_capability"] == "plan.generate"
        assert cap["selected_capability"] == "plan_study_path"
        assert cap["bridge_version"] == CAPABILITY_BRIDGE_VERSION


# ---------------------------------------------------------------------------
# Scenario test: planner path uses capability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestPlannerCapabilityScenario:
    async def test_planner_resolve_runtime_plan_uses_capability(self) -> None:
        """Planner._resolve_runtime_plan should use resolve_capability_request,
        not resolve_runtime_plan with hardcoded skill_name."""
        from agent_core.application.services.planner import PlannerService

        mock_registry = MagicMock(spec=DynamicRuntimeRegistryService)
        mock_registry.resolve_capability_request = AsyncMock(return_value=None)
        mock_registry.resolve_runtime_plan = AsyncMock(return_value=None)

        planner = PlannerService.__new__(PlannerService)
        planner._runtime_registry = mock_registry
        planner._skill_usage_service = None
        planner._goal_skill_binding_resolver = None

        goal = MagicMock()
        goal.id = "goal-1"
        goal.subject = "math"

        await planner._resolve_runtime_plan(goal)

        mock_registry.resolve_capability_request.assert_awaited_once()
        request_arg = mock_registry.resolve_capability_request.call_args.args[0]
        assert isinstance(request_arg, CapabilityRequest)
        assert request_arg.capability == "plan.generate"
        assert request_arg.surface == "plan_generation"
        assert request_arg.learner_goal_id == "goal-1"
        assert request_arg.topic_key == "math"
