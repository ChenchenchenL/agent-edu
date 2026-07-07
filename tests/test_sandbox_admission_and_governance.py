"""Tests for Phase 3: sandbox admission and activation governance.

Covers:
- SandboxAdmissionService: low/medium auto-admit, high-risk restricted, fail-closed
- ActivationGovernanceService: activate/replace/stage/broaden/privilege rules
- Sandbox profiles: baseline vs restricted_high_risk
- Privilege delta evaluation
- Curator integration with admission/governance services
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from agent_core.application.services.reflection_sandbox_admission import (
    SandboxAdmissionDecision,
    SandboxAdmissionRequest,
    SandboxAdmissionService,
)
from agent_core.application.services.reflection_sandbox_policy import (
    BASELINE_PROFILE,
    RESTRICTED_HIGH_RISK_PROFILE,
    STRICTER_HIGH_RISK_PROFILE,
    PRIVILEGED_REVIEW_PROFILE,
    SandboxProfile,
    get_profile,
    profile_for_risk_level,
)
from agent_core.application.services.skill.activation_governance import (
    ActivationGovernanceDecision,
    ActivationGovernanceRequest,
    ActivationGovernanceService,
    evaluate_privilege_delta,
)
from dataclasses import replace as dc_replace
from agent_core.domain.entities.reflection.proposal import ReflectionProposal


def _make_proposal(
    *,
    risk_level: str = "low",
    proposal_type: str = "skill_package",
    status: str = "proposed",
    target_scope: str = "chat",
    evidence_snapshot: dict | None = None,
) -> ReflectionProposal:
    return ReflectionProposal.build(
        reflection_record_id="rec-1",
        learner_goal_id="goal-1",
        proposal_type=proposal_type,
        target_scope=target_scope,
        hypothesis="test",
        change_summary="test",
        structured_patch_payload={},
        expected_improvement="test",
        risk_level=risk_level,
        evidence_snapshot=evidence_snapshot or {},
        priority_score=0.5,
    )


# ---------------------------------------------------------------------------
# Sandbox profile tests
# ---------------------------------------------------------------------------


class TestSandboxProfiles:
    def test_baseline_profile_exists(self) -> None:
        assert BASELINE_PROFILE.name == "baseline_profile"
        assert BASELINE_PROFILE.allow_tool_plan_preview is True
        assert BASELINE_PROFILE.sample_count_cap == 5

    def test_restricted_high_risk_profile(self) -> None:
        assert RESTRICTED_HIGH_RISK_PROFILE.name == "restricted_high_risk_profile"
        assert RESTRICTED_HIGH_RISK_PROFILE.allow_live_llm_replay is False
        assert RESTRICTED_HIGH_RISK_PROFILE.sample_count_cap == 3
        assert "Bash" not in RESTRICTED_HIGH_RISK_PROFILE.allowed_tools

    def test_profile_for_risk_level(self) -> None:
        assert profile_for_risk_level("low") is BASELINE_PROFILE
        assert profile_for_risk_level("medium") is BASELINE_PROFILE
        assert profile_for_risk_level("high") is STRICTER_HIGH_RISK_PROFILE

    def test_get_profile_known(self) -> None:
        p = get_profile("baseline_profile")
        assert p.name == "baseline_profile"

    def test_get_profile_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            get_profile("nonexistent")

    def test_profile_to_summary(self) -> None:
        summary = BASELINE_PROFILE.to_summary()
        assert summary["profile"] == "baseline_profile"
        assert isinstance(summary["allowed_tools"], list)


# ---------------------------------------------------------------------------
# SandboxAdmissionService tests
# ---------------------------------------------------------------------------


class TestSandboxAdmissionService:
    def setup_method(self) -> None:
        self.service = SandboxAdmissionService()

    def test_low_risk_auto_admitted(self) -> None:
        proposal = _make_proposal(risk_level="low")
        decision = self.service.decide(SandboxAdmissionRequest(proposal=proposal))
        assert decision.allowed is True
        assert decision.profile is BASELINE_PROFILE

    def test_medium_risk_auto_admitted(self) -> None:
        proposal = _make_proposal(risk_level="medium")
        decision = self.service.decide(SandboxAdmissionRequest(proposal=proposal))
        assert decision.allowed is True
        assert decision.profile is BASELINE_PROFILE

    def test_high_risk_admitted_with_restricted_profile(self) -> None:
        proposal = _make_proposal(risk_level="high")
        decision = self.service.decide(SandboxAdmissionRequest(proposal=proposal))
        assert decision.allowed is True
        assert decision.profile is STRICTER_HIGH_RISK_PROFILE
        assert "high_risk_restricted_profile" in decision.reason_codes

    def test_missing_target_scope_blocked(self) -> None:
        proposal = dc_replace(_make_proposal(), target_scope="")
        decision = self.service.decide(SandboxAdmissionRequest(proposal=proposal))
        assert decision.allowed is False
        assert "missing_target_scope" in decision.reason_codes

    def test_unsupported_proposal_type_blocked(self) -> None:
        proposal = dc_replace(_make_proposal(), proposal_type="unknown_type")
        decision = self.service.decide(SandboxAdmissionRequest(proposal=proposal))
        assert decision.allowed is False
        assert "unsupported_proposal_type" in decision.reason_codes

    def test_approved_proposal_blocked(self) -> None:
        proposal = _make_proposal()
        approved = dc_replace(proposal, status="approved")
        decision = self.service.decide(SandboxAdmissionRequest(proposal=approved))
        assert decision.allowed is False
        assert "proposal_already_terminal" in decision.reason_codes


# ---------------------------------------------------------------------------
# ActivationGovernanceService tests
# ---------------------------------------------------------------------------


class TestActivationGovernanceService:
    def setup_method(self) -> None:
        self.service = ActivationGovernanceService()

    def test_low_risk_activate_allowed(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="activate",
            risk_level="low",
        ))
        assert decision.allowed is True

    def test_high_risk_activate_manual_review(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="activate",
            risk_level="high",
        ))
        assert decision.manual_review_required is True
        assert "high_risk_requires_manual_review" in decision.reason_codes

    def test_high_risk_replace_manual_review(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="replace",
            risk_level="high",
        ))
        assert decision.manual_review_required is True

    def test_broaden_scope_always_manual_review(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="broaden_scope",
            risk_level="low",
        ))
        assert decision.manual_review_required is True
        assert "broaden_scope_requires_manual_review" in decision.reason_codes

    def test_privilege_change_always_manual_review(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="privilege_change",
            risk_level="low",
        ))
        assert decision.manual_review_required is True
        assert "privilege_change_requires_manual_review" in decision.reason_codes

    def test_privilege_broadening_triggers_manual_review(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="activate",
            risk_level="low",
            privilege_delta={"tools_added": ["Bash"]},
        ))
        assert decision.manual_review_required is True
        assert "privilege_broadening_detected" in decision.reason_codes

    def test_scope_broadening_triggers_manual_review(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="replace",
            risk_level="low",
            scope_delta={"surfaces_added": ["quiz"]},
        ))
        assert decision.manual_review_required is True
        assert "scope_broadening_detected" in decision.reason_codes

    def test_unknown_action_blocked(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="nonexistent",
        ))
        assert decision.blocked is True
        assert "unknown_action" in decision.reason_codes

    def test_stage_low_risk_governed_source_allowed(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="stage",
            risk_level="low",
            source_proposal_type="skill_patch_request_realization",
        ))
        assert decision.allowed is True

    def test_stage_non_governed_source_manual_review(self) -> None:
        decision = self.service.decide(ActivationGovernanceRequest(
            action="stage",
            risk_level="low",
            source_proposal_type="unknown_source",
        ))
        assert decision.manual_review_required is True
        assert "non_governed_source" in decision.reason_codes

    def test_blast_radius_includes_replacement_info(self) -> None:
        from agent_core.domain.entities.skill import SkillArtifact
        existing = SkillArtifact.build(
            name="test", version="1.0.0", lineage_id="lin-1",
            skill_type="baseline", scope="chat", description="test",
            definition={}, compatibility_contract={},
            created_by="system", status="active",
        )
        decision = self.service.decide(ActivationGovernanceRequest(
            action="replace",
            risk_level="low",
            existing_selectable=existing,
        ))
        assert decision.blast_radius_summary is not None
        assert decision.blast_radius_summary["replaces_artifact_id"] == existing.id


# ---------------------------------------------------------------------------
# Privilege delta evaluation
# ---------------------------------------------------------------------------


class TestPrivilegeDelta:
    def test_tools_added_detected(self) -> None:
        delta = evaluate_privilege_delta(
            current_tools=frozenset({"Read"}),
            proposed_tools=frozenset({"Read", "Bash"}),
            current_surfaces=None,
            proposed_surfaces=None,
        )
        assert delta["tools_added"] == ["Bash"]
        assert delta["has_broadening"] is True

    def test_no_broadening(self) -> None:
        delta = evaluate_privilege_delta(
            current_tools=frozenset({"Read", "Bash"}),
            proposed_tools=frozenset({"Read"}),
            current_surfaces=None,
            proposed_surfaces=None,
        )
        assert delta["tools_added"] == []
        assert delta["tools_removed"] == ["Bash"]
        assert delta["has_broadening"] is False

    def test_surfaces_added_detected(self) -> None:
        delta = evaluate_privilege_delta(
            current_tools=None,
            proposed_tools=None,
            current_surfaces={"chat"},
            proposed_surfaces={"chat", "hint"},
        )
        assert delta["surfaces_added"] == ["hint"]
        assert delta["has_broadening"] is True

    def test_none_inputs_no_broadening(self) -> None:
        delta = evaluate_privilege_delta(
            current_tools=None,
            proposed_tools=None,
            current_surfaces=None,
            proposed_surfaces=None,
        )
        assert delta["has_broadening"] is False


# ---------------------------------------------------------------------------
# Tests: Condition 3 — high-risk proposal can auto-enter restricted sandbox
# ---------------------------------------------------------------------------


class TestHighRiskSandboxAdmission:
    """Verify that high-risk proposals are admitted with the restricted profile.

    This covers the Phase 3 acceptance criterion: high-risk proposals must
    be able to enter a restricted sandbox automatically, not just be parked
    in manual review.  The SandboxAdmissionService must return
    ``allowed=True`` so the curator can proceed to enqueue the sandbox run.
    """

    def test_high_risk_allowed_with_restricted_profile(self) -> None:
        svc = SandboxAdmissionService()
        proposal = _make_proposal(risk_level="high")
        decision = svc.decide(SandboxAdmissionRequest(proposal=proposal))
        # Must be allowed — high-risk should enter the restricted sandbox,
        # not be blocked before it even runs.
        assert decision.allowed is True
        assert decision.status == "allowed"
        # Must receive the restricted profile, not the baseline profile.
        assert decision.profile is not None
        assert decision.profile.name == STRICTER_HIGH_RISK_PROFILE.name
        # The reason code must signal that a restricted profile was applied.
        assert "high_risk_restricted_profile" in decision.reason_codes

    def test_high_risk_profile_more_restrictive_than_baseline(self) -> None:
        """Restricted profile must have tighter constraints than baseline."""
        restricted = STRICTER_HIGH_RISK_PROFILE
        baseline = BASELINE_PROFILE
        # Restricted profile has lower or equal sample cap
        assert restricted.sample_count_cap <= baseline.sample_count_cap
        # Restricted profile does not allow external side effects
        assert restricted.allow_external_side_effect_simulation is False
        # Restricted profile has a smaller allowed tools set
        assert len(restricted.allowed_tools) < len(baseline.allowed_tools)

    def test_approved_high_risk_proposal_blocked(self) -> None:
        """Already-approved proposals must not re-enter sandbox (terminal state)."""
        import dataclasses
        svc = SandboxAdmissionService()
        # build() ignores status; override via replace to simulate a terminal proposal
        proposal = dataclasses.replace(_make_proposal(risk_level="high"), status="approved")
        decision = svc.decide(SandboxAdmissionRequest(proposal=proposal))
        assert decision.allowed is False
        assert "proposal_already_terminal" in decision.reason_codes

    def test_medium_risk_admitted_with_baseline(self) -> None:
        svc = SandboxAdmissionService()
        proposal = _make_proposal(risk_level="medium")
        decision = svc.decide(SandboxAdmissionRequest(proposal=proposal))
        assert decision.allowed is True
        assert decision.profile is not None
        # Medium-risk should not get the restricted profile
        assert decision.profile.name != RESTRICTED_HIGH_RISK_PROFILE.name

    def test_missing_scope_blocked_regardless_of_risk(self) -> None:
        """Proposals without a target_scope are blocked for all risk levels."""
        svc = SandboxAdmissionService()
        # Directly call with a proposal whose target_scope is falsy
        import dataclasses
        for risk in ("low", "medium", "high"):
            base_proposal = _make_proposal(risk_level=risk)
            # Override target_scope via dataclasses.replace to bypass entity validation
            proposal = dataclasses.replace(base_proposal, target_scope="")
            decision = svc.decide(SandboxAdmissionRequest(proposal=proposal))
            assert decision.allowed is False, f"Expected blocked for risk={risk}"
            assert "missing_target_scope" in decision.reason_codes
