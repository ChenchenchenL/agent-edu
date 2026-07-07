"""Reflection evidence contracts and payload normalization.

Provides a unified runtime and governance evidence payload specification
for reflection records, supporting backward compatibility and fail-closed
degradation when runtime evidence is missing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_core.domain.entities.skill import SkillUsageEvent
    from agent_core.domain.entities.reflection.proposal import (
        ReflectionProposalRollout,
        ReflectionProposalRolloutObservation,
    )


def build_capability_request_summary(event: SkillUsageEvent | None) -> dict[str, Any] | None:
    """Build request summary from usage event."""
    if event is None:
        return None
    cap_meta = event.metadata.get("capability") or {}
    return {
        "requested_capability": cap_meta.get("requested_capability") or event.skill_name,
        "surface": event.surface,
        "topic_key": event.topic_key,
        "task_type": event.metadata.get("task_type") or cap_meta.get("task_type"),
        "trigger_source": event.trigger_source,
        "risk_budget": event.metadata.get("risk_budget"),
        "tenant_policy_id": event.metadata.get("tenant_policy_id"),
    }


def build_capability_selection_summary(event: SkillUsageEvent | None) -> dict[str, Any] | None:
    """Build selection summary from usage event."""
    if event is None:
        return None
    cap_meta = event.metadata.get("capability") or {}
    
    # Extract confidence from various potential locations
    confidence = event.outcome_signals.get("confidence")
    if confidence is None:
        confidence = event.metadata.get("confidence")
    if confidence is None:
        confidence = cap_meta.get("confidence")
    if confidence is not None:
        confidence = float(confidence)

    # Loser reason codes: extract from loser_reason_map keys or candidate reason codes
    loser_reason_codes: list[str] = []
    loser_map = event.metadata.get("loser_reason_map") or {}
    if loser_map:
        loser_reason_codes = list(loser_map.keys())
    else:
        router_dec = event.metadata.get("router_decision") or {}
        loser_reason_codes = list(router_dec.get("loser_reason_map", {}).keys())

    return {
        "selected_capability": cap_meta.get("selected_capability") or event.skill_name,
        "winner_artifact_id": event.skill_artifact_id,
        "fallback_chain": list(event.metadata.get("fallback_chain") or []),
        "loser_reason_codes": loser_reason_codes,
        "confidence": confidence,
        "resolution_mode": cap_meta.get("resolution_mode") or event.resolver_status,
        "reason_codes": list(cap_meta.get("reason_codes") or [event.selection_reason]),
    }


def build_candidate_summaries(event: SkillUsageEvent | None) -> list[dict[str, Any]]:
    """Build summaries for candidates comparison."""
    if event is None:
        return []
    router_decision = event.metadata.get("router_decision") or {}
    candidates = router_decision.get("ranked_candidates") or []
    summaries = []
    for c in candidates:
        summaries.append({
            "candidate_id": c.get("candidate_id") or c.get("artifact_id"),
            "skill_name": c.get("skill_name"),
            "artifact_id": c.get("artifact_id"),
            "artifact_status": c.get("artifact_status"),
        })
    return summaries


def build_template_summary(event: SkillUsageEvent | None) -> dict[str, Any] | None:
    """Build template details summary."""
    if event is None:
        return None
    cap_meta = event.metadata.get("capability") or {}
    template_id = event.metadata.get("selected_template_id") or cap_meta.get("template_id")
    template_source = event.metadata.get("selected_template_source")
    seq_ver = event.metadata.get("sequence_contract_version") or event.metadata.get("tool_plan_policy_version")
    
    steps_count = None
    if "tool_plan" in event.metadata:
        steps_count = len(event.metadata["tool_plan"] or [])
    elif "steps" in event.metadata:
        steps_count = len(event.metadata["steps"] or [])

    return {
        "template_id": template_id,
        "template_source": template_source,
        "sequence_contract_version": seq_ver,
        "steps_count": steps_count,
    }


def build_rollout_governance_summary(
    rollout: ReflectionProposalRollout | None,
    observation: ReflectionProposalRolloutObservation | None,
) -> dict[str, Any] | None:
    """Build rollout and observation status summary."""
    if rollout is None:
        return None
    return {
        "rollout_status": rollout.status,
        "staged": rollout.status == "staged",
        "approved_by": rollout.activated_by,
        "recent_observation_recommendation": observation.recommendation if observation is not None else None,
    }


def build_runtime_evidence_contract(
    event: SkillUsageEvent | None,
    rollout: ReflectionProposalRollout | None = None,
    observation: ReflectionProposalRolloutObservation | None = None,
) -> dict[str, Any]:
    """Build normalized runtime evidence dictionary."""
    return {
        "capability_request": build_capability_request_summary(event),
        "capability_selection": build_capability_selection_summary(event),
        "candidates": build_candidate_summaries(event),
        "template_summary": build_template_summary(event),
        "rollout_governance": build_rollout_governance_summary(rollout, observation),
    }
