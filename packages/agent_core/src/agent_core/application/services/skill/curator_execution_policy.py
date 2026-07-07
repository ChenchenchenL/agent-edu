"""Curator execution eligibility policy.

Defines which recommendation types can be auto-executed and the
conditions under which auto-execution is permitted.  This is the
gatekeeper that prevents high-risk or high-blast-radius actions
from being automatically advanced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.domain.entities.skill import SkillCuratorRecommendation


AUTO_EXECUTABLE_RECOMMENDATION_TYPES = frozenset({
    "patch_needed",
    "merge_candidate",
    "patch_routing_policy",
    "patch_template_policy",
    "patch_skill_package",
    "select_replacement_skill_package",
})

MANUAL_GATE_RECOMMENDATION_TYPES = frozenset({
    "activate_candidate",
    "replace_candidate",
    "archive_candidate",
    "restore_candidate",
    "promote_candidate",
    "rollback_review",
    "flag_for_review",
})

CURATOR_EXECUTION_STATUSES = frozenset({
    "detected",
    "proposal_created",
    "sandbox_enqueued",
    "sandbox_running",
    "sandbox_completed",
    "evaluation_completed",
    "staged",
    "completed",
    "suspended",
    "rejected",
    "suppressed",
    "rollback_required",
    "manual_gate",
})

FAILURE_REASON_CODES = frozenset({
    "missing_anchor",
    "non_trusted_source",
    "high_risk_manual_gate",
    "blast_radius_too_large",
    "sandbox_failed",
    "evaluation_ineffective",
    "auto_staging_disabled",
    "privilege_delta_detected",
    "scope_broadening_detected",
    "suppressed_artifact",
    "recommendation_not_auto_executable",
    "duplicate_execution",
    "evidence_incomplete",
})


@dataclass(frozen=True)
class CuratorExecutionEligibility:
    """Result of eligibility check for a recommendation."""

    eligible: bool
    reason_codes: list[str] = field(default_factory=list)
    risk_level: str = "low"
    blast_radius_summary: dict[str, Any] | None = None
    trusted_source: bool = True


class CuratorExecutionEligibilityService:
    """Determine whether a recommendation can be auto-executed."""

    _TRUSTED_SOURCES = frozenset({
        "skill_patch_request_realization",
        "skill_curator_merge_recommendation",
        "skill_curator_job",
    })

    def check(self, recommendation: SkillCuratorRecommendation) -> CuratorExecutionEligibility:
        reason_codes: list[str] = []

        if recommendation.recommendation_type not in AUTO_EXECUTABLE_RECOMMENDATION_TYPES:
            return CuratorExecutionEligibility(
                eligible=False,
                reason_codes=["recommendation_not_auto_executable"],
            )

        if recommendation.status != "pending":
            return CuratorExecutionEligibility(
                eligible=False,
                reason_codes=["recommendation_not_pending"],
            )

        evidence = recommendation.evidence_snapshot or {}
        risk_level = str(evidence.get("risk_level", "low"))

        if risk_level == "high":
            return CuratorExecutionEligibility(
                eligible=False,
                reason_codes=["high_risk_manual_gate"],
                risk_level=risk_level,
            )

        source = str(evidence.get("source", ""))
        trusted = source in self._TRUSTED_SOURCES or source == ""
        if not trusted:
            reason_codes.append("non_trusted_source")

        if evidence.get("privilege_delta_detected"):
            reason_codes.append("privilege_delta_detected")

        if evidence.get("scope_broadening_detected"):
            reason_codes.append("scope_broadening_detected")

        artifact_suppressed = evidence.get("artifact_suppressed", False)
        if artifact_suppressed:
            reason_codes.append("suppressed_artifact")

        blast_radius = {
            "artifact_id": recommendation.artifact_id,
            "skill_name": recommendation.skill_name,
            "scope": recommendation.scope,
            "surface": recommendation.surface,
            "recommendation_type": recommendation.recommendation_type,
        }

        return CuratorExecutionEligibility(
            eligible=len(reason_codes) == 0,
            reason_codes=reason_codes,
            risk_level=risk_level,
            blast_radius_summary=blast_radius,
            trusted_source=trusted,
        )
