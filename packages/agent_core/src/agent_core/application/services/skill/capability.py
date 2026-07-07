"""Capability-driven runtime contracts.

Phase 1 of the skill autonomy evolution. These contracts decouple the
runtime entry point from fixed ``skill_name`` strings, allowing callers
to request a *capability* and let the bridge layer resolve it to the
legacy skill resolution path.

This module deliberately does **not** perform multi-candidate ranking.
``confidence`` and ``fallback_chain`` carry rule-based bridge values
until Phase 2 introduces a real router.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CAPABILITY_SELECTION_REASON_CODES = frozenset({
    "binding_overlay_applied",
    "static_fallback",
    "suppressed_artifact",
    "contract_incompatible",
    "legacy_skill_bridge",
    "production_default",
    "artifact_missing_static_fallback",
    "runtime_resolution_failed",
})

CAPABILITY_BRIDGE_VERSION = "bridge_v1"


@dataclass(frozen=True)
class CapabilityRequest:
    """Input contract for capability-driven runtime resolution.

    Callers express *what* they need, not *which skill* should fulfil it.
    """

    capability: str
    surface: str
    learner_goal_id: str | None = None
    topic_key: str | None = None
    task_type: str | None = None
    trigger_source: str | None = None
    risk_budget: str | None = None
    tenant_policy_id: str | None = None


@dataclass(frozen=True)
class CapabilitySelection:
    """Output contract for capability-driven runtime resolution.

    In Phase 1 the selection always contains a single winner produced by
    the legacy bridge.  ``reason_codes`` explain *why* this artifact was
    chosen (or why the fallback was used).
    """

    requested_capability: str
    selected_artifact_id: str | None
    selected_capability: str
    reason_codes: list[str] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    confidence: float = 1.0
    tool_plan_template_id: str | None = None
    legacy_skill_name: str | None = None
    bridge_version: str = CAPABILITY_BRIDGE_VERSION
    resolution_mode: str = "legacy_bridge"


@dataclass(frozen=True)
class RuntimeCapabilityExecutionPlan:
    """Wraps the existing ``RuntimeSkillExecutionPlan`` with capability metadata.

    ``router_decision`` is populated only when a ``SkillRouterService`` was
    used (Phase 2+).  It carries the full ranked candidate list and loser
    reason map so that the explain layer can surface them without re-running
    the router.
    """

    plan: object  # RuntimeSkillExecutionPlan – typed as object to avoid circular import
    selection: CapabilitySelection
    request: CapabilityRequest
    router_decision: object | None = None  # SkillRouterDecision | None
