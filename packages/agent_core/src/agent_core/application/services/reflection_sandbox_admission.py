"""Sandbox admission service.

Decides whether a proposal is allowed to enter the sandbox, and if so,
which profile it receives.  This is independent of activation
governance -- a proposal can be admitted to sandbox but still blocked
from production activation.

Fail-closed: missing critical governance information results in
``blocked`` status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_core.application.services.reflection_sandbox_policy import (
    SandboxProfile,
    profile_for_risk_level,
)
from agent_core.domain.entities.reflection.proposal import ReflectionProposal


@dataclass(frozen=True)
class SandboxAdmissionRequest:
    """Input to the admission decision."""

    proposal: ReflectionProposal
    resource_id: str | None = None


@dataclass(frozen=True)
class SandboxAdmissionDecision:
    """Output of the admission decision."""

    status: str
    profile: SandboxProfile | None = None
    reason_codes: list[str] = field(default_factory=list)
    profile_summary: dict[str, Any] | None = None
    privilege_delta_summary: dict[str, Any] | None = None

    @property
    def allowed(self) -> bool:
        return self.status == "allowed"


class SandboxAdmissionService:
    """Evaluate whether a proposal may enter the sandbox.

    Rules:
    - low/medium risk: automatic admission with baseline profile
    - high risk: admission allowed with restricted profile when
      the proposal has a valid type and scope
    - missing critical information: fail-closed (blocked)
    """

    _ADMISSIBLE_PROPOSAL_TYPES = {
        "skill_package",
        "skill_patch_request",
        "prompt_optimization",
        "workflow_optimization",
        "routing_policy",
        "template_policy",
    }

    def decide(self, request: SandboxAdmissionRequest) -> SandboxAdmissionDecision:
        proposal = request.proposal
        reason_codes: list[str] = []

        if proposal.proposal_type not in self._ADMISSIBLE_PROPOSAL_TYPES:
            return SandboxAdmissionDecision(
                status="blocked",
                reason_codes=["unsupported_proposal_type"],
            )

        if not proposal.target_scope:
            return SandboxAdmissionDecision(
                status="blocked",
                reason_codes=["missing_target_scope"],
            )

        risk_level = proposal.risk_level or "low"
        profile = profile_for_risk_level(risk_level)

        if risk_level == "high":
            reason_codes.append("high_risk_restricted_profile")

        if proposal.status in ("approved", "rejected", "archived"):
            return SandboxAdmissionDecision(
                status="blocked",
                profile=profile,
                reason_codes=[*reason_codes, "proposal_already_terminal"],
                profile_summary=profile.to_summary(),
            )

        return SandboxAdmissionDecision(
            status="allowed",
            profile=profile,
            reason_codes=reason_codes,
            profile_summary=profile.to_summary(),
        )
