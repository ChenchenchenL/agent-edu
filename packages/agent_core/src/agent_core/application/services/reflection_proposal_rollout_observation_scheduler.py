from __future__ import annotations

from datetime import datetime, timezone

from agent_core.application.services.audit import AuditService
from agent_core.application.services.autonomy_jobs import AutonomyJobService
from agent_core.application.services.reflection_proposal_rollout_auto_governance import (
    ReflectionProposalRolloutDecisionScheduler,
)
from agent_core.infrastructure.db.repositories import ReflectionProposalRolloutRepository


class ReflectionProposalRolloutObservationScheduler:
    def __init__(
        self,
        *,
        rollout_repository: ReflectionProposalRolloutRepository,
        autonomy_job_service: AutonomyJobService | None,
        audit_service: AuditService,
        decision_scheduler: ReflectionProposalRolloutDecisionScheduler | None = None,
    ) -> None:
        self._rollout_repository = rollout_repository
        self._autonomy_job_service = autonomy_job_service
        self._audit_service = audit_service
        self._decision_scheduler = decision_scheduler

    async def schedule_active(
        self,
        *,
        learner_goal_id: str,
        surface: str,
        trigger_source: str,
        source_ref: str,
    ) -> str | None:
        rollout = await self._rollout_repository.get_active_by_goal_and_surface(
            learner_goal_id,
            surface,
        )
        if rollout is None:
            return None
        return await self.schedule_rollout(
            rollout_id=rollout.id,
            trigger_source=trigger_source,
            source_ref=source_ref,
        )

    async def schedule_rollout(
        self,
        *,
        rollout_id: str,
        trigger_source: str,
        source_ref: str,
    ) -> str | None:
        if self._autonomy_job_service is None:
            return None
        rollout = await self._rollout_repository.get_by_id(rollout_id)
        if rollout is None or rollout.status == "rolled_back":
            return None
        job = await self._autonomy_job_service.create_job(
            learner_goal_id=rollout.learner_goal_id,
            job_type="reflection_proposal_rollout_observation",
            trigger_source=trigger_source,
            due_at=datetime.now(timezone.utc),
            idempotency_key=f"rollout:{rollout.id}:observe:{source_ref}",
            payload={
                "rollout_id": rollout.id,
                "surface": rollout.surface,
                "source_ref": source_ref,
            },
        )
        if job is None:
            return None
        await self._audit_service.record(
            event_type="reflection.proposal.rollout.observe.queued",
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
        return job.id

    async def schedule_decision(
        self,
        *,
        rollout_id: str,
        trigger_source: str,
        source_ref: str,
    ) -> str | None:
        if self._decision_scheduler is None:
            return None
        return await self._decision_scheduler.schedule_rollout_decision(
            rollout_id=rollout_id,
            trigger_source=trigger_source,
            source_ref=source_ref,
        )
