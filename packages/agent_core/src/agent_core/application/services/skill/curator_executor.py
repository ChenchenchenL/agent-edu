"""Curator executor service.

Advances eligible recommendations through the governed pipeline:
recommendation -> proposal -> sandbox -> evaluation -> stage.

This service is the restricted executor -- it can only perform
whitelisted actions and must call existing governance services
for each step.  It does not own sandbox or staging logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from agent_core.application.services.audit import AuditService
from agent_core.application.services.skill.curator_execution_policy import (
    AUTO_EXECUTABLE_RECOMMENDATION_TYPES,
    CURATOR_EXECUTION_STATUSES,
    CuratorExecutionEligibility,
    CuratorExecutionEligibilityService,
)
from agent_core.domain.entities.skill import SkillCuratorRecommendation
from agent_core.infrastructure.observability.metrics import observe_curator_execution


class ProposalCreationService(Protocol):
    """Protocol for creating proposals from recommendations."""

    async def create_proposal_from_recommendation(
        self,
        recommendation: SkillCuratorRecommendation,
        *,
        operator_id: str,
    ) -> dict[str, Any]: ...


class SandboxExecutionService(Protocol):
    """Protocol for running sandbox evaluation."""

    async def execute_sandbox_for_proposal(
        self,
        proposal_id: str,
    ) -> dict[str, Any]: ...


class StagingService(Protocol):
    """Protocol for staging artifacts from proposals."""

    async def auto_stage_from_proposal(
        self,
        proposal_id: str,
        *,
        operator_id: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CuratorExecutionRequest:
    """Input to the curator executor."""

    recommendation: SkillCuratorRecommendation
    operator_id: str = "system"
    auto_stage_enabled: bool = True


def recovery_strategy_for_reason(reason_code: str) -> str | None:
    if not reason_code:
        return None
    strategies = {
        "proposal_service_unavailable": "retry_proposal_service",
        "sandbox_failed": "re_run_sandbox_isolated",
        "evaluation_inconclusive": "adjust_evaluation_parameters_or_samples",
        "auto_stage_failed": "manual_override_staging",
        "privilege_delta_detected": "request_operator_privilege_escalation",
        "scope_broadening_detected": "request_operator_scope_escalation",
        "evidence_incomplete": "wait_for_metrics_sync",
    }
    return strategies.get(reason_code, "manual_operator_intervention")


@dataclass
class CuratorExecutionResult:
    """Output of the curator executor."""

    recommendation_id: str
    status: str
    current_step: str = "detected"
    reason_code: str = ""
    reason_note: str = ""
    proposal_id: str | None = None
    sandbox_run_id: str | None = None
    artifact_id: str | None = None
    attempt_count: int = 0
    execution_log: list[dict[str, Any]] = field(default_factory=list)
    recovery_strategy: str | None = None

    def record_step(self, step: str, *, status: str, reason_code: str = "", **extra: Any) -> None:
        self.current_step = step
        self.status = status
        if reason_code:
            self.reason_code = reason_code
            if status in {"suspended", "rejected", "failed"}:
                self.recovery_strategy = recovery_strategy_for_reason(reason_code)
        self.attempt_count += 1
        self.execution_log.append({
            "step": step,
            "status": status,
            "reason_code": reason_code,
            "recovery_strategy": self.recovery_strategy,
            **extra,
        })


class CuratorExecutorService:
    """Execute eligible recommendations through the governed pipeline.

    Pipeline steps:
    1. Eligibility check
    2. Create proposal (patch_needed -> skill_patch_request, merge_candidate -> merge proposal)
    3. Enqueue sandbox
    4. Run sandbox/evaluation
    5. Auto-stage if eligible

    Each step is idempotent -- repeated calls do not duplicate work.
    """

    def __init__(
        self,
        *,
        eligibility_service: CuratorExecutionEligibilityService | None = None,
        proposal_service: ProposalCreationService | None = None,
        sandbox_service: SandboxExecutionService | None = None,
        staging_service: StagingService | None = None,
        audit_service: AuditService,
    ) -> None:
        self._eligibility_service = eligibility_service or CuratorExecutionEligibilityService()
        self._proposal_service = proposal_service
        self._sandbox_service = sandbox_service
        self._staging_service = staging_service
        self._audit_service = audit_service

    async def execute(self, request: CuratorExecutionRequest) -> CuratorExecutionResult:
        recommendation = request.recommendation
        result = CuratorExecutionResult(
            recommendation_id=recommendation.id,
            status="detected",
            current_step="detected",
        )

        eligibility = self._eligibility_service.check(recommendation)
        if not eligibility.eligible:
            result.record_step(
                "eligibility_check",
                status="manual_gate",
                reason_code=",".join(eligibility.reason_codes) or "ineligible",
                risk_level=eligibility.risk_level,
            )
            await self._audit(result, "skill.curator.execution.manual_gate")
            observe_curator_execution(
                event="manual_gate",
                reason_code=result.reason_code,
            )
            return result

        result.record_step("eligibility_check", status="eligible")

        proposal_result = await self._create_proposal(recommendation, request.operator_id)
        if proposal_result is None:
            result.record_step(
                "proposal_creation",
                status="suspended",
                reason_code="proposal_service_unavailable",
            )
            await self._audit(result, "skill.curator.execution.suspended")
            observe_curator_execution(event="suspended", reason_code="proposal_service_unavailable")
            return result

        if proposal_result.get("error"):
            result.record_step(
                "proposal_creation",
                status="suspended",
                reason_code=str(proposal_result.get("error_code", "proposal_creation_failed")),
                reason_note=str(proposal_result.get("error", "")),
            )
            await self._audit(result, "skill.curator.execution.suspended")
            observe_curator_execution(event="suspended", reason_code=result.reason_code)
            return result

        result.proposal_id = proposal_result.get("proposal_id")
        result.record_step("proposal_creation", status="proposal_created")
        await self._audit(result, "skill.curator.execution.proposal_created")
        observe_curator_execution(event="proposal_created", reason_code="auto_created")

        if self._sandbox_service is not None and result.proposal_id:
            sandbox_result = await self._sandbox_service.execute_sandbox_for_proposal(
                result.proposal_id,
            )
            result.sandbox_run_id = sandbox_result.get("sandbox_run_id")

            if sandbox_result.get("error"):
                result.record_step(
                    "sandbox_execution",
                    status="suspended",
                    reason_code="sandbox_failed",
                    reason_note=str(sandbox_result.get("error", "")),
                )
                await self._audit(result, "skill.curator.execution.suspended")
                observe_curator_execution(event="suspended", reason_code="sandbox_failed")
                return result

            eval_status = sandbox_result.get("evaluation_status", "pending")
            if eval_status == "ineffective":
                result.record_step(
                    "evaluation",
                    status="rejected",
                    reason_code="evaluation_ineffective",
                )
                await self._audit(result, "skill.curator.execution.rejected")
                observe_curator_execution(event="rejected", reason_code="evaluation_ineffective")
                return result

            if eval_status == "inconclusive":
                result.record_step(
                    "evaluation",
                    status="suspended",
                    reason_code="evaluation_inconclusive",
                )
                await self._audit(result, "skill.curator.execution.suspended")
                observe_curator_execution(event="suspended", reason_code="evaluation_inconclusive")
                return result

            result.record_step("evaluation", status="evaluation_completed")
            await self._audit(result, "skill.curator.execution.evaluation_completed")
            observe_curator_execution(event="evaluation_completed", reason_code="effective")

        if request.auto_stage_enabled and self._staging_service is not None and result.proposal_id:
            stage_result = await self._staging_service.auto_stage_from_proposal(
                result.proposal_id,
                operator_id=request.operator_id,
            )
            if stage_result.get("error"):
                result.record_step(
                    "auto_stage",
                    status="suspended",
                    reason_code=str(stage_result.get("error_code", "auto_stage_failed")),
                    reason_note=str(stage_result.get("error", "")),
                )
                await self._audit(result, "skill.curator.execution.suspended")
                observe_curator_execution(event="suspended", reason_code=result.reason_code)
                return result

            result.artifact_id = stage_result.get("artifact_id")
            result.record_step("auto_stage", status="staged")
            await self._audit(result, "skill.curator.execution.artifact_auto_staged")
            observe_curator_execution(event="artifact_auto_staged", reason_code="auto_staged")

        result.status = "completed"
        result.current_step = "completed"
        return result

    async def _create_proposal(
        self,
        recommendation: SkillCuratorRecommendation,
        operator_id: str,
    ) -> dict[str, Any] | None:
        if self._proposal_service is None:
            return None
        return await self._proposal_service.create_proposal_from_recommendation(
            recommendation,
            operator_id=operator_id,
        )

    async def _audit(self, result: CuratorExecutionResult, event_type: str) -> None:
        await self._audit_service.record(
            event_type=event_type,
            resource_type="skill_curator_execution",
            resource_id=result.recommendation_id,
            actor="system",
            event_data={
                "recommendation_id": result.recommendation_id,
                "status": result.status,
                "current_step": result.current_step,
                "reason_code": result.reason_code,
                "proposal_id": result.proposal_id,
                "sandbox_run_id": result.sandbox_run_id,
                "artifact_id": result.artifact_id,
                "attempt_count": result.attempt_count,
            },
        )
