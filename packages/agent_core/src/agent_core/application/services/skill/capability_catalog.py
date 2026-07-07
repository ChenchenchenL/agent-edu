"""Capability-to-legacy-skill bridge catalog.

Centralises the mapping from capability identifiers to the legacy
``skill_name`` values used by the current runtime.  No other module
should hard-code these mappings; callers that need to translate a
capability into a legacy skill must go through this catalog.

The catalog is intentionally small and explicit.  Phase 2 will extend
the resolution logic with real candidate ranking; until then this
table is the single source of truth for the bridge layer.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapabilityBridgeEntry:
    """Maps a capability to its legacy skill resolution inputs."""

    capability: str
    legacy_skill_name: str
    default_surface: str
    supported_surfaces: tuple[str, ...]


_CAPABILITY_BRIDGE_TABLE: dict[str, CapabilityBridgeEntry] = {
    "chat.respond": CapabilityBridgeEntry(
        capability="chat.respond",
        legacy_skill_name="explain_concept",
        default_surface="chat",
        supported_surfaces=("chat",),
    ),
    "hint.adaptive": CapabilityBridgeEntry(
        capability="hint.adaptive",
        legacy_skill_name="adaptive_hint",
        default_surface="hint",
        supported_surfaces=("hint",),
    ),
    "assessment.generate": CapabilityBridgeEntry(
        capability="assessment.generate",
        legacy_skill_name="create_quiz",
        default_surface="quiz",
        supported_surfaces=("quiz", "assessment_generation"),
    ),
    "plan.generate": CapabilityBridgeEntry(
        capability="plan.generate",
        legacy_skill_name="plan_study_path",
        default_surface="plan_generation",
        supported_surfaces=("plan_generation", "replan"),
    ),
    "review.schedule": CapabilityBridgeEntry(
        capability="review.schedule",
        legacy_skill_name="schedule_review",
        default_surface="review_scheduling",
        supported_surfaces=("review_scheduling",),
    ),
}


def get_bridge_entry(capability: str) -> CapabilityBridgeEntry | None:
    return _CAPABILITY_BRIDGE_TABLE.get(capability)


def resolve_capability_to_legacy(
    capability: str,
    surface: str | None = None,
) -> tuple[str, str] | None:
    """Return ``(legacy_skill_name, effective_surface)`` for a capability.

    Returns ``None`` when the capability is unknown or the requested
    surface is not supported.
    """
    entry = get_bridge_entry(capability)
    if entry is None:
        return None
    effective_surface = surface or entry.default_surface
    if effective_surface not in entry.supported_surfaces:
        return None
    return entry.legacy_skill_name, effective_surface


def list_capabilities() -> list[CapabilityBridgeEntry]:
    return list(_CAPABILITY_BRIDGE_TABLE.values())


def reverse_lookup(
    legacy_skill_name: str,
    surface: str,
) -> str | None:
    """Return the capability for a legacy skill_name + surface pair.

    Returns ``None`` when no mapping exists.  This is used by the
    compatibility bridge in ``DynamicRuntimeRegistryService`` to
    translate old callers into the new capability path.
    """
    for entry in _CAPABILITY_BRIDGE_TABLE.values():
        if entry.legacy_skill_name == legacy_skill_name and surface in entry.supported_surfaces:
            return entry.capability
    return None
