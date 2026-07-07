"""Bridge adapter between capability-driven and legacy skill resolution.

``CapabilityRequestBridge`` is the single translation point:

* ``to_legacy_inputs`` converts a ``CapabilityRequest`` into the
  keyword arguments expected by the existing ``resolve_runtime_plan``
  and ``resolve_execution_plan`` signatures.
* ``build_selection`` wraps the legacy ``SkillExecutionPlan`` /
  ``RuntimeSkillExecutionPlan`` output into a ``CapabilitySelection``.

Callers should never need to know about legacy ``skill_name`` values;
the bridge hides that detail.
"""

from __future__ import annotations

from typing import Any

from agent_core.application.services.skill.capability import (
    CAPABILITY_BRIDGE_VERSION,
    CapabilityRequest,
    CapabilitySelection,
)
from agent_core.application.services.skill.capability_catalog import resolve_capability_to_legacy


class CapabilityRequestBridge:
    """Translate capability requests to legacy resolution inputs and back."""

    @staticmethod
    def to_legacy_inputs(
        request: CapabilityRequest,
    ) -> dict[str, Any] | None:
        """Return legacy keyword arguments for a capability request.

        Returns ``None`` when the capability cannot be mapped.
        """
        resolved = resolve_capability_to_legacy(
            request.capability,
            surface=request.surface,
        )
        if resolved is None:
            return None
        legacy_skill_name, effective_surface = resolved
        return {
            "skill_name": legacy_skill_name,
            "surface": effective_surface,
            "learner_goal_id": request.learner_goal_id,
            "topic_key": request.topic_key,
            "task_type": request.task_type,
            "trigger_source": request.trigger_source,
        }

    @staticmethod
    def build_selection(
        request: CapabilityRequest,
        *,
        artifact_id: str | None,
        resolver_status: str,
        selection_reason: str,
        tool_plan: list[dict[str, Any]] | None = None,
        binding_applied: bool = False,
    ) -> CapabilitySelection:
        """Build a ``CapabilitySelection`` from legacy resolution output."""
        resolved = resolve_capability_to_legacy(
            request.capability,
            surface=request.surface,
        )
        selected_capability = resolved[0] if resolved else request.capability
        legacy_skill_name = resolved[0] if resolved else None

        reason_codes: list[str] = []
        if binding_applied:
            reason_codes.append("binding_overlay_applied")
        reason_codes.append(selection_reason)

        fallback_chain: list[str] = []
        if resolver_status == "missing_artifact":
            fallback_chain.append("static_fallback")
        elif resolver_status == "blocked":
            fallback_chain.append("suppressed_artifact")
        elif resolver_status == "incompatible":
            fallback_chain.append("contract_incompatible")

        confidence = 1.0
        if resolver_status != "resolved":
            confidence = 0.5

        tool_plan_template_id: str | None = None
        if tool_plan:
            first_tool = tool_plan[0].get("tool_name") if tool_plan else None
            if first_tool:
                tool_plan_template_id = f"{request.capability}:{first_tool}"

        return CapabilitySelection(
            requested_capability=request.capability,
            selected_artifact_id=artifact_id,
            selected_capability=selected_capability,
            reason_codes=reason_codes,
            fallback_chain=fallback_chain,
            confidence=confidence,
            tool_plan_template_id=tool_plan_template_id,
            legacy_skill_name=legacy_skill_name,
            bridge_version=CAPABILITY_BRIDGE_VERSION,
            resolution_mode="legacy_bridge",
        )
