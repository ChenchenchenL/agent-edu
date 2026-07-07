"""Activation governance service.

Unified governance evaluation for skill artifact lifecycle actions:
stage, activate, replace, broaden_scope, privilege_change.

This service replaces the scattered high-risk checks in the curator
and lifecycle services.  It outputs a governance decision, not an
artifact -- the lifecycle service consumes this decision to decide
whether to proceed with a state transition.

Fail-closed: missing information or high-risk with broadening
defaults to ``manual_review_required``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.domain.entities.skill import SkillArtifact


ACTIVATION_GOVERNANCE_ACTIONS = frozenset({
    "stage",
    "activate",
    "replace",
    "broaden_scope",
    "privilege_change",
})


@dataclass(frozen=True)
class ActivationGovernanceRequest:
    """Input to the activation governance decision."""

    action: str
    artifact: SkillArtifact | None = None
    risk_level: str | None = None
    existing_selectable: SkillArtifact | None = None
    privilege_delta: dict[str, Any] | None = None
    scope_delta: dict[str, Any] | None = None
    source_proposal_type: str | None = None


@dataclass(frozen=True)
class ActivationGovernanceDecision:
    """Output of the activation governance decision."""

    status: str
    action: str
    reason_codes: list[str] = field(default_factory=list)
    manual_review_required: bool = False
    blast_radius_summary: dict[str, Any] | None = None
    privilege_delta_summary: dict[str, Any] | None = None
    scope_delta_summary: dict[str, Any] | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"


class ActivationGovernanceService:
    """Evaluate whether a lifecycle action is permitted.

    Rules:
    - ``activate``: allowed unless high-risk or privilege broadening
    - ``replace``: allowed unless high-risk, scope broadening, or
      privilege broadening
    - ``broaden_scope``: always manual_review_required
    - ``privilege_change``: always manual_review_required
    - ``stage``: allowed unless high-risk with non-governed source
    """

    _GOVERNED_SOURCES = {
        "skill_patch_request_realization",
        "skill_curator_merge_recommendation",
    }

    def decide(self, request: ActivationGovernanceRequest) -> ActivationGovernanceDecision:
        if request.action not in ACTIVATION_GOVERNANCE_ACTIONS:
            return ActivationGovernanceDecision(
                status="blocked",
                action=request.action,
                reason_codes=["unknown_action"],
            )

        risk = request.risk_level or "low"
        reason_codes: list[str] = []
        manual_review = False

        if request.action == "broaden_scope":
            return ActivationGovernanceDecision(
                status="manual_review_required",
                action=request.action,
                reason_codes=["broaden_scope_requires_manual_review"],
                manual_review_required=True,
                scope_delta_summary=request.scope_delta,
            )

        if request.action == "privilege_change":
            return ActivationGovernanceDecision(
                status="manual_review_required",
                action=request.action,
                reason_codes=["privilege_change_requires_manual_review"],
                manual_review_required=True,
                privilege_delta_summary=request.privilege_delta,
            )

        has_privilege_broadening = self._has_privilege_broadening(request)
        has_scope_broadening = self._has_scope_broadening(request)

        if has_privilege_broadening:
            reason_codes.append("privilege_broadening_detected")
            manual_review = True

        if has_scope_broadening:
            reason_codes.append("scope_broadening_detected")
            manual_review = True

        if risk == "high":
            reason_codes.append("high_risk_requires_manual_review")
            manual_review = True

        if request.action == "stage" and not self._is_governed_source(request):
            reason_codes.append("non_governed_source")
            manual_review = True

        if request.action in ("activate", "replace") and request.existing_selectable is not None:
            blast_radius = {
                "replaces_artifact_id": request.existing_selectable.id,
                "replaces_artifact_status": request.existing_selectable.status,
                "action": request.action,
            }
        else:
            blast_radius = {"action": request.action}

        if manual_review:
            return ActivationGovernanceDecision(
                status="manual_review_required",
                action=request.action,
                reason_codes=reason_codes,
                manual_review_required=True,
                blast_radius_summary=blast_radius,
                privilege_delta_summary=request.privilege_delta,
            )

        return ActivationGovernanceDecision(
            status="allowed",
            action=request.action,
            reason_codes=reason_codes,
            blast_radius_summary=blast_radius,
            privilege_delta_summary=request.privilege_delta,
        )

    @staticmethod
    def _has_privilege_broadening(request: ActivationGovernanceRequest) -> bool:
        if request.privilege_delta is None:
            return False
        return bool(request.privilege_delta.get("tools_added"))

    @staticmethod
    def _has_scope_broadening(request: ActivationGovernanceRequest) -> bool:
        if request.scope_delta is None:
            return False
        return bool(request.scope_delta.get("surfaces_added") or request.scope_delta.get("tenant_scope_expanded"))

    @classmethod
    def _is_governed_source(cls, request: ActivationGovernanceRequest) -> bool:
        if request.source_proposal_type is None:
            return True
        return request.source_proposal_type in cls._GOVERNED_SOURCES


def evaluate_privilege_delta(
    *,
    current_tools: frozenset[str] | None,
    proposed_tools: frozenset[str] | None,
    current_surfaces: set[str] | None,
    proposed_surfaces: set[str] | None,
) -> dict[str, Any]:
    """Evaluate the privilege delta between current and proposed state."""
    tools_added: list[str] = []
    tools_removed: list[str] = []
    surfaces_added: list[str] = []
    surfaces_removed: list[str] = []

    if current_tools is not None and proposed_tools is not None:
        tools_added = sorted(proposed_tools - current_tools)
        tools_removed = sorted(current_tools - proposed_tools)

    if current_surfaces is not None and proposed_surfaces is not None:
        surfaces_added = sorted(proposed_surfaces - current_surfaces)
        surfaces_removed = sorted(current_surfaces - proposed_surfaces)

    return {
        "tools_added": tools_added,
        "tools_removed": tools_removed,
        "surfaces_added": surfaces_added,
        "surfaces_removed": surfaces_removed,
        "has_broadening": bool(tools_added or surfaces_added),
    }
