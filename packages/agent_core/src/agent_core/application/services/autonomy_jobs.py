from __future__ import annotations

from datetime import datetime
from typing import Any

from agent_core.application.services.audit import AuditService
from agent_core.domain.entities.autonomy import ScheduledAutonomyJob
from agent_core.infrastructure.db.repositories import ScheduledAutonomyJobRepository


class AutonomyJobService:
    def __init__(
        self,
        *,
        repository: ScheduledAutonomyJobRepository | None,
        audit_service: AuditService,
    ) -> None:
        self._repository = repository
        self._audit_service = audit_service

    async def create_job(
        self,
        *,
        learner_goal_id: str,
        job_type: str,
        trigger_source: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
    ) -> ScheduledAutonomyJob | None:
        if self._repository is None:
            return None
        job = await self._repository.create(
            ScheduledAutonomyJob.build(
                learner_goal_id=learner_goal_id,
                job_type=job_type,
                trigger_source=trigger_source,
                due_at=due_at,
                idempotency_key=idempotency_key,
                payload=dict(payload or {}),
            )
        )
        await self._audit_service.record(
            event_type="autonomy.job.created",
            resource_type="autonomy_job",
            resource_id=job.id,
            actor="system",
            event_data={
                "autonomy_job_id": job.id,
                "learner_goal_id": learner_goal_id,
                "job_type": job_type,
                "trigger_source": trigger_source,
                "due_at": due_at.isoformat(),
                "idempotency_key": idempotency_key,
            },
        )
        return job
