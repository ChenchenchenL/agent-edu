"""Tests for Phase 4: curator executor and execution policy.

Covers:
- CuratorExecutionEligibilityService: auto-executable vs manual gate
- CuratorExecutorService: full pipeline advancement
- High-risk stops at manual gate
- Missing evidence causes suspension
- Sandbox failure stops advancement
- Evaluation ineffective stops advancement
- Idempotent execution
- Activation/replace/broaden cannot be auto-executed
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from agent_core.application.services.skill.curator_execution_policy import (
    AUTO_EXECUTABLE_RECOMMENDATION_TYPES,
    CURATOR_EXECUTION_STATUSES,
    FAILURE_REASON_CODES,
    MANUAL_GATE_RECOMMENDATION_TYPES,
    CuratorExecutionEligibility,
    CuratorExecutionEligibilityService,
)
from agent_core.application.services.skill.curator_executor import (
    CuratorExecutionRequest,
    CuratorExecutionResult,
    CuratorExecutorService,
)
from agent_core.domain.entities.skill import SkillCuratorRecommendation


def _make_recommendation(
    *,
    recommendation_type: str = "patch_needed",
    status: str = "pending",
    risk_level: str = "low",
    source: str = "skill_curator_job",
    artifact_suppressed: bool = False,
    privilege_delta_detected: bool = False,
    scope_broadening_detected: bool = False,
    artifact_id: str | None = None,
) -> SkillCuratorRecommendation:
    action_map = {
        "activate_candidate": "activate_staged",
        "replace_candidate": "replace_selectable",
        "promote_candidate": "stabilize_active",
        "archive_candidate": "archive_deprecated",
        "restore_candidate": "restore_suppressed",
    }
    recommended_action = action_map.get(recommendation_type, "none")
    effective_artifact_id = artifact_id or ("art-1" if recommended_action != "none" else None)
    return SkillCuratorRecommendation.build(
        recommendation_type=recommendation_type,
        recommended_action=recommended_action,
        reason_code="coverage_regression",
        created_by="skill_curator_job",
        artifact_id=effective_artifact_id,
        skill_name="explain_concept",
        scope="chat",
        surface="chat",
        evidence_snapshot={
            "risk_level": risk_level,
            "source": source,
            "artifact_suppressed": artifact_suppressed,
            "privilege_delta_detected": privilege_delta_detected,
            "scope_broadening_detected": scope_broadening_detected,
        },
    )


# ---------------------------------------------------------------------------
# Policy constants
# ---------------------------------------------------------------------------


class TestPolicyConstants:
    def test_auto_executable_types(self) -> None:
        assert "patch_needed" in AUTO_EXECUTABLE_RECOMMENDATION_TYPES
        assert "merge_candidate" in AUTO_EXECUTABLE_RECOMMENDATION_TYPES
        assert "activate_candidate" not in AUTO_EXECUTABLE_RECOMMENDATION_TYPES

    def test_manual_gate_types(self) -> None:
        assert "activate_candidate" in MANUAL_GATE_RECOMMENDATION_TYPES
        assert "replace_candidate" in MANUAL_GATE_RECOMMENDATION_TYPES
        assert "patch_needed" not in MANUAL_GATE_RECOMMENDATION_TYPES

    def test_execution_statuses(self) -> None:
        assert "detected" in CURATOR_EXECUTION_STATUSES
        assert "staged" in CURATOR_EXECUTION_STATUSES
        assert "suspended" in CURATOR_EXECUTION_STATUSES
        assert "manual_gate" in CURATOR_EXECUTION_STATUSES

    def test_failure_reason_codes(self) -> None:
        assert "high_risk_manual_gate" in FAILURE_REASON_CODES
        assert "sandbox_failed" in FAILURE_REASON_CODES
        assert "evaluation_ineffective" in FAILURE_REASON_CODES


# ---------------------------------------------------------------------------
# Eligibility service
# ---------------------------------------------------------------------------


class TestCuratorExecutionEligibilityService:
    def setup_method(self) -> None:
        self.service = CuratorExecutionEligibilityService()

    def test_patch_needed_low_risk_eligible(self) -> None:
        rec = _make_recommendation(recommendation_type="patch_needed", risk_level="low")
        result = self.service.check(rec)
        assert result.eligible is True
        assert result.risk_level == "low"

    def test_merge_candidate_low_risk_eligible(self) -> None:
        rec = _make_recommendation(recommendation_type="merge_candidate", risk_level="low")
        result = self.service.check(rec)
        assert result.eligible is True

    def test_activate_candidate_not_eligible(self) -> None:
        rec = _make_recommendation(recommendation_type="activate_candidate")
        result = self.service.check(rec)
        assert result.eligible is False
        assert "recommendation_not_auto_executable" in result.reason_codes

    def test_replace_candidate_not_eligible(self) -> None:
        rec = _make_recommendation(recommendation_type="replace_candidate")
        result = self.service.check(rec)
        assert result.eligible is False
        assert "recommendation_not_auto_executable" in result.reason_codes

    def test_high_risk_not_eligible(self) -> None:
        rec = _make_recommendation(risk_level="high")
        result = self.service.check(rec)
        assert result.eligible is False
        assert "high_risk_manual_gate" in result.reason_codes

    def test_non_pending_not_eligible(self) -> None:
        rec = _make_recommendation()
        from dataclasses import replace as dc_replace
        rec = dc_replace(rec, status="dismissed")
        result = self.service.check(rec)
        assert result.eligible is False
        assert "recommendation_not_pending" in result.reason_codes

    def test_suppressed_artifact_not_eligible(self) -> None:
        rec = _make_recommendation(artifact_suppressed=True)
        result = self.service.check(rec)
        assert result.eligible is False
        assert "suppressed_artifact" in result.reason_codes

    def test_privilege_delta_not_eligible(self) -> None:
        rec = _make_recommendation(privilege_delta_detected=True)
        result = self.service.check(rec)
        assert result.eligible is False
        assert "privilege_delta_detected" in result.reason_codes

    def test_scope_broadening_not_eligible(self) -> None:
        rec = _make_recommendation(scope_broadening_detected=True)
        result = self.service.check(rec)
        assert result.eligible is False
        assert "scope_broadening_detected" in result.reason_codes


# ---------------------------------------------------------------------------
# Executor service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCuratorExecutorService:
    async def test_high_risk_stops_at_manual_gate(self) -> None:
        rec = _make_recommendation(risk_level="high")
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(audit_service=audit)
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "manual_gate"
        assert "high_risk_manual_gate" in result.reason_code

    async def test_non_executable_stops_at_manual_gate(self) -> None:
        rec = _make_recommendation(recommendation_type="activate_candidate")
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(audit_service=audit)
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "manual_gate"

    async def test_no_proposal_service_suspends(self) -> None:
        rec = _make_recommendation()
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=None,
            audit_service=audit,
        )
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "suspended"
        assert result.reason_code == "proposal_service_unavailable"

    async def test_proposal_creation_error_suspends(self) -> None:
        rec = _make_recommendation()
        proposal_svc = MagicMock()
        proposal_svc.create_proposal_from_recommendation = AsyncMock(
            return_value={"error": "creation_failed", "error_code": "duplicate"},
        )
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=proposal_svc,
            audit_service=audit,
        )
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "suspended"

    async def test_sandbox_failure_stops_advancement(self) -> None:
        rec = _make_recommendation()
        proposal_svc = MagicMock()
        proposal_svc.create_proposal_from_recommendation = AsyncMock(
            return_value={"proposal_id": "prop-1"},
        )
        sandbox_svc = MagicMock()
        sandbox_svc.execute_sandbox_for_proposal = AsyncMock(
            return_value={"error": "replay_failed", "sandbox_run_id": "run-1"},
        )
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=proposal_svc,
            sandbox_service=sandbox_svc,
            audit_service=audit,
        )
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "suspended"
        assert result.reason_code == "sandbox_failed"
        assert result.proposal_id == "prop-1"

    async def test_evaluation_ineffective_stops_advancement(self) -> None:
        rec = _make_recommendation()
        proposal_svc = MagicMock()
        proposal_svc.create_proposal_from_recommendation = AsyncMock(
            return_value={"proposal_id": "prop-1"},
        )
        sandbox_svc = MagicMock()
        sandbox_svc.execute_sandbox_for_proposal = AsyncMock(
            return_value={"evaluation_status": "ineffective", "sandbox_run_id": "run-1"},
        )
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=proposal_svc,
            sandbox_service=sandbox_svc,
            audit_service=audit,
        )
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "rejected"
        assert result.reason_code == "evaluation_ineffective"

    async def test_full_pipeline_completes(self) -> None:
        rec = _make_recommendation()
        proposal_svc = MagicMock()
        proposal_svc.create_proposal_from_recommendation = AsyncMock(
            return_value={"proposal_id": "prop-1"},
        )
        sandbox_svc = MagicMock()
        sandbox_svc.execute_sandbox_for_proposal = AsyncMock(
            return_value={"evaluation_status": "effective", "sandbox_run_id": "run-1"},
        )
        staging_svc = MagicMock()
        staging_svc.auto_stage_from_proposal = AsyncMock(
            return_value={"artifact_id": "art-1"},
        )
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=proposal_svc,
            sandbox_service=sandbox_svc,
            staging_service=staging_svc,
            audit_service=audit,
        )
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "completed"
        assert result.proposal_id == "prop-1"
        assert result.sandbox_run_id == "run-1"
        assert result.artifact_id == "art-1"

    async def test_auto_stage_disabled_skips_staging(self) -> None:
        rec = _make_recommendation()
        proposal_svc = MagicMock()
        proposal_svc.create_proposal_from_recommendation = AsyncMock(
            return_value={"proposal_id": "prop-1"},
        )
        sandbox_svc = MagicMock()
        sandbox_svc.execute_sandbox_for_proposal = AsyncMock(
            return_value={"evaluation_status": "effective", "sandbox_run_id": "run-1"},
        )
        staging_svc = MagicMock()
        staging_svc.auto_stage_from_proposal = AsyncMock()
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=proposal_svc,
            sandbox_service=sandbox_svc,
            staging_service=staging_svc,
            audit_service=audit,
        )
        result = await executor.execute(
            CuratorExecutionRequest(recommendation=rec, auto_stage_enabled=False),
        )
        assert result.status == "completed"
        assert result.artifact_id is None
        staging_svc.auto_stage_from_proposal.assert_not_called()

    async def test_execution_log_records_all_steps(self) -> None:
        rec = _make_recommendation()
        proposal_svc = MagicMock()
        proposal_svc.create_proposal_from_recommendation = AsyncMock(
            return_value={"proposal_id": "prop-1"},
        )
        sandbox_svc = MagicMock()
        sandbox_svc.execute_sandbox_for_proposal = AsyncMock(
            return_value={"evaluation_status": "effective", "sandbox_run_id": "run-1"},
        )
        staging_svc = MagicMock()
        staging_svc.auto_stage_from_proposal = AsyncMock(
            return_value={"artifact_id": "art-1"},
        )
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=proposal_svc,
            sandbox_service=sandbox_svc,
            staging_service=staging_svc,
            audit_service=audit,
        )
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        steps = [entry["step"] for entry in result.execution_log]
        assert "eligibility_check" in steps
        assert "proposal_creation" in steps
        assert "evaluation" in steps
        assert "auto_stage" in steps

    def test_new_recommendation_types_auto_executable(self) -> None:
        eligibility_svc = CuratorExecutionEligibilityService()
        for rec_type in (
            "patch_routing_policy",
            "patch_template_policy",
            "patch_skill_package",
            "select_replacement_skill_package",
        ):
            rec = _make_recommendation(recommendation_type=rec_type, risk_level="low")
            res = eligibility_svc.check(rec)
            assert res.eligible is True

    async def test_recovery_strategy_recorded_on_failure(self) -> None:
        rec = _make_recommendation()
        proposal_svc = MagicMock()
        proposal_svc.create_proposal_from_recommendation = AsyncMock(
            return_value={"proposal_id": "prop-1"},
        )
        sandbox_svc = MagicMock()
        sandbox_svc.execute_sandbox_for_proposal = AsyncMock(
            return_value={"error": "replay_failed", "sandbox_run_id": "run-1"},
        )
        audit = MagicMock()
        audit.record = AsyncMock()
        executor = CuratorExecutorService(
            proposal_service=proposal_svc,
            sandbox_service=sandbox_svc,
            audit_service=audit,
        )
        result = await executor.execute(CuratorExecutionRequest(recommendation=rec))
        assert result.status == "suspended"
        assert result.reason_code == "sandbox_failed"
        assert result.recovery_strategy == "re_run_sandbox_isolated"
        
        # Verify recovery_strategy is also saved in the last step of the log
        last_log = result.execution_log[-1]
        assert last_log["status"] == "suspended"
        assert last_log["reason_code"] == "sandbox_failed"
        assert last_log["recovery_strategy"] == "re_run_sandbox_isolated"
