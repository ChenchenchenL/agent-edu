"""Runtime binding readiness contracts.

This module defines the dedicated dataclasses used for runtime binding readiness,
allowing operator probe, baseline regression, and future API responses to share
a common contract shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuntimeBindingReadiness:
    """Represents the readiness state of a runtime binding for a given goal/surface.
    
    This is used to determine if a skill is ready to be executed, what its sources
    are, and why it might be blocked or fallback to a static implementation.
    """
    skill_name: str
    surface: str
    learner_goal_id: str | None
    resolution_mode: str
    """e.g., 'production', 'shadow', 'probe'"""
    selected_artifact_id: str | None
    selected_binding_id: str | None
    selected_rollout_id: str | None
    blocked_reason_codes: list[str] = field(default_factory=list)
    """e.g., ['suppressed_artifact', 'contract_incompatible']"""
    fallback_mode: str | None = None
    """e.g., 'static_fallback', 'artifact_only', 'binding_overlay', 'blocked'"""
    tool_plan_status: str = "none"
    """e.g., 'none', 'artifact', 'binding_overlay'"""
    staged_involvement: str = "none"
    """e.g., 'none', 'preview', 'probe'"""


@dataclass(frozen=True)
class RuntimeBindingExplainResult:
    """Detailed explain result for a given goal/surface runtime binding resolution.
    
    This provides full visibility to operators as to why a specific runtime behavior
    was chosen.
    """
    skill_name: str
    surface: str
    source_summary: dict[str, object]
    """e.g. {'artifact_source': '...', 'directives_source': '...', 'tool_plan_source': '...'}"""
    resolution_summary: dict[str, object]
    """e.g. {'resolver_status': '...', 'selection_reason': '...'}"""
    binding_summary: dict[str, object] | None
    """e.g. {'binding_id': '...', 'status': '...'}"""
    rollout_summary: dict[str, object] | None
    """e.g. {'rollout_id': '...', 'strategy': '...'}"""
    tool_plan_summary: dict[str, object] | None
    """e.g. {'enabled': True, 'steps': [...]}"""
    blocked_reason_codes: list[str] = field(default_factory=list)
    fallback_reason_codes: list[str] = field(default_factory=list)
