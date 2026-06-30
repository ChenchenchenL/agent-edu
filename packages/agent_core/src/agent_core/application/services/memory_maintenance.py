from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
from traceback import format_exception

from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.application.services.audit import AuditService
from agent_core.application.services.memory import MemoryMaintenanceBatchResult, MemoryService
from agent_core.domain.entities.memory_maintenance import MEMORY_MAINTENANCE_JOB_TYPES, MemoryMaintenanceJob
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.db.repositories import MemoryMaintenanceJobRepository
from agent_core.infrastructure.observability.metrics import observe_memory_maintenance_job

MEMORY_MAINTENANCE_JOB_ORDER = (
    "knowledge_promotion_eligibility",
    "knowledge_governance",
    "behavior_governance",
    "knowledge_compression",
    "behavior_compression",
    "conflict_refresh",
)


@dataclass(frozen=True)
class MemoryMaintenanceSeedResult:
    created_count: int
    existing_count: int


@dataclass(frozen=True)
class MemoryMaintenanceFailure:
    error_code: str
    error_message: str
    traceback: str
    retryable: bool

    def to_event_data(self) -> dict[str, str | bool]:
        return {
            "error_code": self.error_code,
            "error_message": self.error_message,
            "traceback": self.traceback,
            "retryable": self.retryable,
        }


def memory_maintenance_backoff(attempt_count: int) -> timedelta:
    if attempt_count <= 1:
        return timedelta(minutes=5)
    if attempt_count == 2:
        return timedelta(minutes=15)
    return timedelta(minutes=45)


class MemoryMaintenanceService:
    def __init__(
        self,
        *,
        repository: MemoryMaintenanceJobRepository,
        memory_service: MemoryService,
        audit_service: AuditService,
        db_session: AsyncSession,
        jobs_per_tick: int = 5,
        batch_size: int = 20,
        lease_seconds: int = 300,
        max_attempts: int = 3,
    ) -> None:
        self._repository = repository
        self._memory_service = memory_service
        self._audit_service = audit_service
        self._db_session = db_session
        self._jobs_per_tick = max(jobs_per_tick, 1)
        self._batch_size = max(batch_size, 1)
        self._lease_seconds = max(lease_seconds, 1)
        self._max_attempts = max(max_attempts, 1)

    async def seed_due_jobs(self, *, due_at: datetime | None = None) -> MemoryMaintenanceSeedResult:
        now = due_at or datetime.now(timezone.utc)
        window_key = now.strftime("%Y%m%d")
        created_count = 0
        existing_count = 0
        for learner_profile_id in await self._memory_service.list_maintenance_profile_ids():
            for job_type in MEMORY_MAINTENANCE_JOB_ORDER:
                idempotency_key = self._idempotency_key(
                    learner_profile_id=learner_profile_id,
                    job_type=job_type,
                    window_key=window_key,
                )
                existing = await self._repository.get_by_idempotency_key(idempotency_key)
                if existing is not None:
                    existing_count += 1
                    continue
                candidate = MemoryMaintenanceJob.build(
                    job_type=job_type,
                    learner_profile_id=learner_profile_id,
                    due_at=now,
                    idempotency_key=idempotency_key,
                    payload={"window_key": window_key},
                    max_attempts=self._max_attempts,
                )
                job = await self._repository.create(candidate)
                if job.id != candidate.id:
                    existing_count += 1
                    continue
                await self._audit_service.record(
                    event_type="memory_maintenance.job.created",
                    resource_type="memory_maintenance_job",
                    resource_id=job.id,
                    actor="system",
                    event_data={
                        "memory_maintenance_job_id": job.id,
                        "learner_profile_id": learner_profile_id,
                        "job_type": job_type,
                        "due_at": now.isoformat(),
                        "idempotency_key": idempotency_key,
                    },
                )
                created_count += 1
        return MemoryMaintenanceSeedResult(created_count=created_count, existing_count=existing_count)

    async def run_due_jobs(
        self,
        *,
        raise_on_error: bool = False,
        lease_owner: str = "worker",
        limit: int | None = None,
    ) -> int:
        await self.seed_due_jobs()
        await self._db_session.commit()
        processed = 0
        target = max(limit or self._jobs_per_tick, 1)
        while processed < target:
            due_jobs = await self._repository.list_due(
                now=datetime.now(timezone.utc),
                limit=target - processed,
            )
            if not due_jobs:
                break
            claimed_any = False
            for job in due_jobs:
                try:
                    claimed = await self._repository.claim(
                        job,
                        lease_owner=lease_owner,
                        lease_seconds=self._lease_seconds,
                    )
                except ValidationError:
                    await self._db_session.rollback()
                    continue
                claimed_any = True
                await self._audit_service.record(
                    event_type="memory_maintenance.job.claimed",
                    resource_type="memory_maintenance_job",
                    resource_id=claimed.id,
                    actor="system",
                    event_data=self._job_event_data(claimed),
                )
                await self._db_session.commit()
                job_started_at = perf_counter()
                try:
                    result = await self._process_job(claimed)
                    if result.completed:
                        observe_memory_maintenance_job(
                            job_type=claimed.job_type,
                            status="completed",
                            duration_seconds=perf_counter() - job_started_at,
                        )
                        completed = claimed.complete()
                        await self._repository.update(completed)
                        await self._audit_service.record(
                            event_type="memory_maintenance.job.completed",
                            resource_type="memory_maintenance_job",
                            resource_id=completed.id,
                            actor="system",
                            event_data={
                                **self._job_event_data(completed),
                                "processed_count": result.processed_count,
                                "changed_count": result.changed_count,
                                "metadata": result.metadata,
                            },
                        )
                    else:
                        observe_memory_maintenance_job(
                            job_type=claimed.job_type,
                            status="progressed",
                            duration_seconds=perf_counter() - job_started_at,
                        )
                        progressed = claimed.progress(
                            cursor=result.next_cursor,
                            due_at=datetime.now(timezone.utc),
                        )
                        await self._repository.update(progressed)
                        await self._audit_service.record(
                            event_type="memory_maintenance.job.progressed",
                            resource_type="memory_maintenance_job",
                            resource_id=progressed.id,
                            actor="system",
                            event_data={
                                **self._job_event_data(progressed),
                                "processed_count": result.processed_count,
                                "changed_count": result.changed_count,
                                "metadata": result.metadata,
                            },
                        )
                    await self._db_session.commit()
                    processed += 1
                except Exception as exc:
                    observe_memory_maintenance_job(
                        job_type=claimed.job_type,
                        status="failed",
                        duration_seconds=perf_counter() - job_started_at,
                    )
                    await self._handle_failure(claimed, exc, raise_on_error=raise_on_error)
                    processed += 1
            if not claimed_any:
                break
        if hasattr(self._memory_service, "refresh_observability_metrics"):
            await self._memory_service.refresh_observability_metrics()
        return processed

    async def _handle_failure(
        self,
        job: MemoryMaintenanceJob,
        exc: Exception,
        *,
        raise_on_error: bool,
    ) -> None:
        failure = self._classify_failure(exc)
        failed_attempt_count = job.attempt_count + 1
        await self._db_session.rollback()
        if failure.retryable and failed_attempt_count < job.max_attempts:
            retry = job.retry(
                due_at=datetime.now(timezone.utc) + memory_maintenance_backoff(failed_attempt_count),
                error_code=failure.error_code,
            )
            await self._repository.update(retry)
            await self._audit_service.record_durable(
                event_type="memory_maintenance.job.retry_scheduled",
                resource_type="memory_maintenance_job",
                resource_id=retry.id,
                actor="system",
                event_data={
                    **self._job_event_data(retry),
                    "retry_due_at": retry.due_at.isoformat(),
                    **failure.to_event_data(),
                },
            )
            await self._db_session.commit()
            return
        failed = job.fail(error_code=failure.error_code)
        await self._repository.update(failed)
        await self._audit_service.record_durable(
            event_type="memory_maintenance.job.failed",
            resource_type="memory_maintenance_job",
            resource_id=failed.id,
            actor="system",
            event_data={
                **self._job_event_data(failed),
                **failure.to_event_data(),
            },
        )
        await self._db_session.commit()
        if raise_on_error:
            raise exc

    @staticmethod
    def _classify_failure(exc: Exception) -> MemoryMaintenanceFailure:
        error_message = str(exc)[:2000]
        traceback = "".join(format_exception(type(exc), exc, exc.__traceback__))[:8000]
        return MemoryMaintenanceFailure(
            error_code=type(exc).__name__,
            error_message=error_message,
            traceback=traceback,
            retryable=not isinstance(exc, ValidationError),
        )

    async def _process_job(self, job: MemoryMaintenanceJob) -> MemoryMaintenanceBatchResult:
        if job.job_type == "knowledge_governance":
            return await self._memory_service.run_knowledge_governance_batch(
                learner_profile_id=job.learner_profile_id,
                cursor=job.cursor,
                batch_size=self._batch_size,
            )
        if job.job_type == "knowledge_promotion_eligibility":
            return await self._memory_service.run_knowledge_promotion_eligibility_batch(
                learner_profile_id=job.learner_profile_id,
                cursor=job.cursor,
                batch_size=self._batch_size,
            )
        if job.job_type == "behavior_governance":
            return await self._memory_service.run_behavior_governance_batch(
                learner_profile_id=job.learner_profile_id,
                cursor=job.cursor,
                batch_size=self._batch_size,
            )
        if job.job_type == "knowledge_compression":
            return await self._memory_service.compress_knowledge_memories_for_profile(
                learner_profile_id=job.learner_profile_id,
                cursor=job.cursor,
                batch_size=self._batch_size,
            )
        if job.job_type == "behavior_compression":
            return await self._memory_service.compress_behavior_memories_for_profile(
                learner_profile_id=job.learner_profile_id,
                cursor=job.cursor,
                batch_size=self._batch_size,
            )
        if job.job_type == "conflict_refresh":
            return await self._memory_service.refresh_conflict_sets_for_profile(
                learner_profile_id=job.learner_profile_id,
                cursor=job.cursor,
                batch_size=self._batch_size,
            )
        raise ValidationError("Unsupported memory maintenance job type.")

    @staticmethod
    def _idempotency_key(*, learner_profile_id: str, job_type: str, window_key: str) -> str:
        if job_type not in MEMORY_MAINTENANCE_JOB_TYPES:
            raise ValidationError("Unsupported memory maintenance job type.")
        return f"memory-maintenance:{window_key}:{learner_profile_id}:{job_type}"

    @staticmethod
    def _job_event_data(job: MemoryMaintenanceJob) -> dict[str, object]:
        return {
            "memory_maintenance_job_id": job.id,
            "learner_profile_id": job.learner_profile_id,
            "job_type": job.job_type,
            "status": job.status,
            "cursor": job.cursor,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            "idempotency_key": job.idempotency_key,
        }
