from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.infrastructure.observability.metrics import observe_skill_rollout_auto_decision
from agent_core.domain.entities.reflection_closure import (
    ReflectionProposalRollout,
    ReflectionProposalRolloutObservation,
)
from agent_core.infrastructure.db.repositories import (
    ReflectionProposalRolloutObservationRepository,
    ReflectionProposalRolloutRepository,
)


AUTO_ROLLOUT_ACTOR = "system:auto_rollout_governor"


@dataclass(frozen=True)
class RolloutAutoGovernanceConfig:
    enabled: bool = True
    auto_promote_enabled: bool = True
    auto_rollback_enabled: bool = True
    promote_surfaces: frozenset[str] = frozenset({"review_scheduling", "assessment_generation", "replan"})
    rollback_surfaces: frozenset[str] = frozenset({"review_scheduling", "assessment_generation", "replan"})


class ReflectionProposalRolloutDecisionScheduler:
    def __init__(
        self,
        *,
        rollout_repository: ReflectionProposalRolloutRepository,
        autonomy_job_service: AutonomyJobService | None,
        audit_service: AuditService,
    ) -> None:
        self._rollout_repository = rollout_repository
        self._autonomy_job_service = autonomy_job_service
        self._audit_service = audit_service

    async def schedule_rollout_decision(
        self,
        *,
        rollout_id: str,
        trigger_source: str,
        source_ref: str,
    ) -> str | None:
        if self._autonomy_job_service is None:
            return None
        rollout = await self._rollout_repository.get_by_id(rollout_id)
        if rollout is None or rollout.status != "staged":
            return None
        job = await self._autonomy_job_service.create_job(
            learner_goal_id=rollout.learner_goal_id,
            job_type="reflection_proposal_rollout_decision",
            trigger_source=trigger_source,
            due_at=rollout.updated_at,
            idempotency_key=f"rollout:{rollout.id}:decision:{source_ref}",
            payload={
                "rollout_id": rollout.id,
                "surface": rollout.surface,
                "source_ref": source_ref,
            },
        )
        if job is None:
            return None
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.auto_decision.queued",
            resource_type="reflection_proposal_rollout",
            resource_id=rollout.id,
            actor="system",
            event_data={
                "rollout_id": rollout.id,
                "job_id": job.id,
                "trigger_source": trigger_source,
                "source_ref": source_ref,
            },
        )
        observe_skill_rollout_auto_decision(
            event="queued",
            decision="pending",
            surface=rollout.surface,
            reason_code="decision_job_enqueued",
        )
        return job.id


class ReflectionProposalRolloutDecisionOrchestrator:
    def __init__(
        self,
        *,
        rollout_repository: ReflectionProposalRolloutRepository,
        observation_repository: ReflectionProposalRolloutObservationRepository,
        rollout_service: Any,
        audit_service: AuditService,
        config: RolloutAutoGovernanceConfig | None = None,
    ) -> None:
        self._rollout_repository = rollout_repository
        self._observation_repository = observation_repository
        self._rollout_service = rollout_service
        self._audit_service = audit_service
        self._config = config or RolloutAutoGovernanceConfig()

    async def evaluate_and_execute(
        self,
        *,
        rollout_id: str,
        source_ref: str,
    ) -> ReflectionProposalRollout | None:
        rollout = await self._rollout_repository.get_by_id(rollout_id)
        if rollout is None:
            return None
        if not self._config.enabled or rollout.status != "staged":
            await self._audit_skip(rollout=rollout, source_ref=source_ref, reason_code="auto_governance_disabled_or_inactive")
            return None
        observation = await self._latest_observation(rollout)
        if observation is None:
            await self._audit_skip(rollout=rollout, source_ref=source_ref, reason_code="missing_latest_observation")
            return None
        if observation.recommendation == "rollback":
            if not self._config.auto_rollback_enabled or rollout.surface not in self._config.rollback_surfaces:
                await self._audit_skip(rollout=rollout, source_ref=source_ref, reason_code="auto_rollback_surface_not_enabled")
                return None
            result = await self._rollout_service.rollback(
                rollout_id=rollout.id,
                operator_id=AUTO_ROLLOUT_ACTOR,
                reason_code="auto_rollback_observation_regressed",
                reason_note=f"source_ref={source_ref}",
            )
            await self._audit_execute(rollout=result, source_ref=source_ref, decision="rollback")
            return result
        if observation.recommendation == "promote":
            if not self._config.auto_promote_enabled or rollout.surface not in self._config.promote_surfaces:
                await self._audit_skip(rollout=rollout, source_ref=source_ref, reason_code="auto_promote_surface_not_enabled")
                return None
            result = await self._rollout_service.promote(
                rollout_id=rollout.id,
                operator_id=AUTO_ROLLOUT_ACTOR,
                reason_code="auto_promote_observation_ready",
                reason_note=f"source_ref={source_ref}",
            )
            await self._audit_execute(rollout=result, source_ref=source_ref, decision="promote")
            return result
        await self._audit_skip(rollout=rollout, source_ref=source_ref, reason_code="no_action_recommendation")
        return None

    async def _latest_observation(
        self,
        rollout: ReflectionProposalRollout,
    ) -> ReflectionProposalRolloutObservation | None:
        if rollout.latest_observation_id is None:
            return None
        observation = await self._observation_repository.get_by_id(rollout.latest_observation_id)
        if observation is None:
            return None
        if observation.rollout_id != rollout.id or observation.surface != rollout.surface:
            return None
        return observation

    async def _audit_skip(
        self,
        *,
        rollout: ReflectionProposalRollout,
        source_ref: str,
        reason_code: str,
    ) -> None:
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.auto_decision.skipped",
            resource_type="reflection_proposal_rollout",
            resource_id=rollout.id,
            actor="system",
            event_data={
                "rollout_id": rollout.id,
                "proposal_id": rollout.proposal_id,
                "surface": rollout.surface,
                "source_ref": source_ref,
                "reason_code": reason_code,
            },
        )
        observe_skill_rollout_auto_decision(
            event="skipped",
            decision="none",
            surface=rollout.surface,
            reason_code=reason_code,
        )

    async def _audit_execute(
        self,
        *,
        rollout: ReflectionProposalRollout,
        source_ref: str,
        decision: str,
    ) -> None:
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.auto_decision.executed",
            resource_type="reflection_proposal_rollout",
            resource_id=rollout.id,
            actor="system",
            event_data={
                "rollout_id": rollout.id,
                "proposal_id": rollout.proposal_id,
                "surface": rollout.surface,
                "source_ref": source_ref,
                "decision": decision,
                "status": rollout.status,
            },
        )
        observe_skill_rollout_auto_decision(
            event="executed",
            decision=decision,
            surface=rollout.surface,
            reason_code=f"auto_{decision}",
        )
