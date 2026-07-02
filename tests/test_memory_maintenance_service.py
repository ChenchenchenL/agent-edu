from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agent_core.application.services.audit import AuditService
from agent_core.application.services.memory import MemoryMaintenanceBatchResult
from agent_core.application.services.memory_maintenance import (
    MEMORY_MAINTENANCE_JOB_ORDER,
    MemoryMaintenanceService,
)
from agent_core.domain.entities.audit import AuditEvent
from agent_core.domain.entities.learner_profile import LearnerProfile
from agent_core.domain.entities.memory_maintenance import MemoryMaintenanceJob
from agent_core.domain.errors import ValidationError
from agent_core.infrastructure.db.base import Base
from agent_core.infrastructure.db.repositories import LearnerProfileRepository, MemoryMaintenanceJobRepository


class StubAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def create(self, entity: AuditEvent) -> None:
        self.events.append(entity)


class StubDbSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class StubMemoryMaintenanceJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, MemoryMaintenanceJob] = {}
        self.create_calls = 0
        self.claim_failure_ids: set[str] = set()

    async def create(self, entity: MemoryMaintenanceJob) -> MemoryMaintenanceJob:
        self.create_calls += 1
        existing = await self.get_by_idempotency_key(entity.idempotency_key)
        if existing is not None:
            return existing
        self.jobs[entity.id] = entity
        return entity

    async def get_by_idempotency_key(self, idempotency_key: str) -> MemoryMaintenanceJob | None:
        for job in self.jobs.values():
            if job.idempotency_key == idempotency_key:
                return job
        return None

    async def list_due(self, *, now: datetime, limit: int) -> list[MemoryMaintenanceJob]:
        due = [
            job
            for job in self.jobs.values()
            if (job.status == "scheduled" and job.due_at <= now)
            or (job.status == "claimed" and job.lease_expires_at is not None and job.lease_expires_at <= now)
        ]
        return due[:limit]

    async def claim(
        self,
        entity: MemoryMaintenanceJob,
        *,
        lease_owner: str,
        lease_seconds: int,
    ) -> MemoryMaintenanceJob:
        if entity.id in self.claim_failure_ids:
            raise ValidationError("Memory maintenance job cannot be claimed.")
        claimed = entity.claim(lease_owner=lease_owner, lease_seconds=lease_seconds)
        self.jobs[claimed.id] = claimed
        return claimed

    async def update(self, entity: MemoryMaintenanceJob) -> None:
        self.jobs[entity.id] = entity


class StubMemoryService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []
        self.profile_ids = ["profile-1"]
        self.fail_job_types: set[str] = set()
        self.validation_fail_job_types: set[str] = set()
        self.progress_job_types: set[str] = set()

    async def list_maintenance_profile_ids(self) -> list[str]:
        return list(self.profile_ids)

    async def run_knowledge_governance_batch(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._run("knowledge_governance", cursor, batch_size)

    async def run_knowledge_promotion_eligibility_batch(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._run("knowledge_promotion_eligibility", cursor, batch_size)

    async def run_behavior_governance_batch(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._run("behavior_governance", cursor, batch_size)

    async def compress_knowledge_memories_for_profile(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._run("knowledge_compression", cursor, batch_size)

    async def compress_behavior_memories_for_profile(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._run("behavior_compression", cursor, batch_size)

    async def refresh_conflict_sets_for_profile(
        self,
        *,
        learner_profile_id: str,
        cursor: str | None,
        batch_size: int,
    ) -> MemoryMaintenanceBatchResult:
        return await self._run("conflict_refresh", cursor, batch_size)

    async def _run(self, job_type: str, cursor: str | None, batch_size: int) -> MemoryMaintenanceBatchResult:
        self.calls.append((job_type, cursor, batch_size))
        if job_type in self.validation_fail_job_types:
            raise ValidationError(f"{job_type} invalid")
        if job_type in self.fail_job_types:
            raise RuntimeError(f"{job_type} failed")
        if job_type in self.progress_job_types:
            return MemoryMaintenanceBatchResult(
                processed_count=batch_size,
                changed_count=1,
                next_cursor=f"{job_type}-cursor",
                completed=False,
                metadata={"changed": 1},
            )
        return MemoryMaintenanceBatchResult(
            processed_count=1,
            changed_count=1,
            next_cursor=None,
            completed=True,
            metadata={"changed": 1},
        )


def _service(
    *,
    repository: StubMemoryMaintenanceJobRepository | None = None,
    memory_service: StubMemoryService | None = None,
    audit_repository: StubAuditRepository | None = None,
    db_session: StubDbSession | None = None,
    jobs_per_tick: int = 6,
    batch_size: int = 20,
    max_attempts: int = 3,
) -> tuple[MemoryMaintenanceService, StubMemoryMaintenanceJobRepository, StubMemoryService, StubAuditRepository, StubDbSession]:
    job_repository = repository or StubMemoryMaintenanceJobRepository()
    memory = memory_service or StubMemoryService()
    audit = audit_repository or StubAuditRepository()
    session = db_session or StubDbSession()
    return (
        MemoryMaintenanceService(
            repository=job_repository,
            memory_service=memory,
            audit_service=AuditService(audit),
            db_session=session,
            jobs_per_tick=jobs_per_tick,
            batch_size=batch_size,
            lease_seconds=60,
            max_attempts=max_attempts,
        ),
        job_repository,
        memory,
        audit,
        session,
    )


@pytest.mark.asyncio
async def test_memory_maintenance_seeding_is_idempotent_per_profile_type_and_window():
    service, repository, _, audit_repository, _ = _service()
    due_at = datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc)

    first = await service.seed_due_jobs(due_at=due_at)
    second = await service.seed_due_jobs(due_at=due_at)

    assert first.created_count == 6
    assert first.existing_count == 0
    assert second.created_count == 0
    assert second.existing_count == 6
    assert repository.create_calls == 6
    assert len(repository.jobs) == 6
    assert [job.job_type for job in repository.jobs.values()] == list(MEMORY_MAINTENANCE_JOB_ORDER)
    assert len([event for event in audit_repository.events if event.event_type == "memory_maintenance.job.created"]) == 6


@pytest.mark.asyncio
async def test_memory_maintenance_runner_dispatches_each_job_type_and_completes():
    service, repository, memory_service, audit_repository, db_session = _service(batch_size=7)

    processed = await service.run_due_jobs(lease_owner="test-worker")
    print("CALLS:", memory_service.calls)

    assert processed == 6, f"Processed {processed}, calls: {memory_service.calls}"
    assert [call[0] for call in memory_service.calls] == list(MEMORY_MAINTENANCE_JOB_ORDER)
    assert all(call[2] == 7 for call in memory_service.calls)
    assert {job.status for job in repository.jobs.values()} == {"completed"}
    assert len([event for event in audit_repository.events if event.event_type == "memory_maintenance.job.completed"]) == 6
    assert db_session.commit_count >= 5


@pytest.mark.asyncio
async def test_memory_maintenance_runner_preserves_cursor_for_incomplete_batch():
    memory_service = StubMemoryService()
    memory_service.progress_job_types = {"knowledge_promotion_eligibility"}
    service, repository, _, audit_repository, _ = _service(
        memory_service=memory_service,
        jobs_per_tick=1,
        batch_size=3,
    )

    processed = await service.run_due_jobs(lease_owner="test-worker")

    assert processed == 1
    progressed = next(job for job in repository.jobs.values() if job.job_type == "knowledge_promotion_eligibility")
    assert progressed.status == "scheduled"
    assert progressed.cursor == "knowledge_promotion_eligibility-cursor"
    assert progressed.attempt_count == 0
    assert any(event.event_type == "memory_maintenance.job.progressed" for event in audit_repository.events)


@pytest.mark.asyncio
async def test_memory_maintenance_runner_retries_then_fails_after_max_attempts():
    memory_service = StubMemoryService()
    memory_service.fail_job_types = {"knowledge_promotion_eligibility"}
    service, repository, _, audit_repository, _ = _service(
        memory_service=memory_service,
        jobs_per_tick=1,
        max_attempts=2,
    )

    first_processed = await service.run_due_jobs(lease_owner="test-worker")
    retried = next(job for job in repository.jobs.values() if job.job_type == "knowledge_promotion_eligibility")
    for job_id, job in list(repository.jobs.items()):
        repository.jobs[job_id] = replace(
            job,
            due_at=datetime.now(timezone.utc) + timedelta(days=1),
        )
    repository.jobs[retried.id] = replace(retried, due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    second_processed = await service.run_due_jobs(lease_owner="test-worker")
    failed = repository.jobs[retried.id]

    assert first_processed == 1
    assert second_processed == 1
    assert failed.status == "failed"
    assert failed.attempt_count == 2
    assert failed.error_code == "RuntimeError"
    retry_event = next(
        event for event in audit_repository.events if event.event_type == "memory_maintenance.job.retry_scheduled"
    )
    failed_event = next(event for event in audit_repository.events if event.event_type == "memory_maintenance.job.failed")
    assert retry_event.event_data["error_code"] == "RuntimeError"
    assert "knowledge_promotion_eligibility failed" in retry_event.event_data["error_message"]
    assert "RuntimeError" in retry_event.event_data["traceback"]
    assert failed_event.event_data["retryable"] is True


@pytest.mark.asyncio
async def test_memory_maintenance_runner_does_not_retry_validation_failures():
    memory_service = StubMemoryService()
    memory_service.validation_fail_job_types = {"knowledge_promotion_eligibility"}
    service, repository, _, audit_repository, _ = _service(
        memory_service=memory_service,
        jobs_per_tick=1,
        max_attempts=3,
    )

    processed = await service.run_due_jobs(lease_owner="test-worker")
    failed = next(job for job in repository.jobs.values() if job.job_type == "knowledge_promotion_eligibility")
    failed_event = next(event for event in audit_repository.events if event.event_type == "memory_maintenance.job.failed")

    assert processed == 1
    assert failed.status == "failed"
    assert failed.attempt_count == 1
    assert failed.error_code == "ValidationError"
    assert failed_event.event_data["retryable"] is False
    assert not any(event.event_type == "memory_maintenance.job.retry_scheduled" for event in audit_repository.events)


@pytest.mark.asyncio
async def test_memory_maintenance_runner_skips_jobs_claimed_by_another_worker():
    service, repository, memory_service, _, db_session = _service(jobs_per_tick=1)
    seed = await service.seed_due_jobs(due_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    first_job = next(job for job in repository.jobs.values() if job.job_type == "knowledge_promotion_eligibility")
    repository.claim_failure_ids.add(first_job.id)

    processed = await service.run_due_jobs(lease_owner="test-worker", limit=1)

    assert seed.created_count == 6
    assert processed == 0
    assert memory_service.calls == []
    assert db_session.rollback_count == 1


@pytest.mark.asyncio
async def test_memory_maintenance_job_repository_lifecycle(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'memory-maintenance-jobs.db'}"
    engine = create_async_engine(database_url, future=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as session:
            profile = LearnerProfile.build()
            await LearnerProfileRepository(session).create(profile)
            repository = MemoryMaintenanceJobRepository(session)
            due_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            job = MemoryMaintenanceJob.build(
                job_type="knowledge_governance",
                learner_profile_id=profile.id,
                due_at=due_at,
                idempotency_key="memory-maintenance:test:profile:knowledge",
            )

            created = await repository.create(job)
            duplicate = await repository.create(job)
            due_jobs = await repository.list_due(now=datetime.now(timezone.utc), limit=10)
            claimed = await repository.claim(created, lease_owner="test-worker", lease_seconds=1)
            active_lease_rejected = False
            try:
                await repository.claim(created, lease_owner="other-worker", lease_seconds=60)
            except ValidationError:
                active_lease_rejected = True
            active_claim_stored = await repository.get_by_id(created.id)
            await repository.update(replace(claimed, lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
            expired_due = await repository.list_due(now=datetime.now(timezone.utc), limit=10)
            reclaimed = await repository.claim(expired_due[0], lease_owner="recovery-worker", lease_seconds=60)
            retried = reclaimed.retry(
                due_at=datetime.now(timezone.utc) + timedelta(minutes=5),
                error_code="RuntimeError",
            )
            await repository.update(retried)
            completed = retried.complete()
            await repository.update(completed)
            completed_stored = await repository.get_by_id(completed.id)

            failing = MemoryMaintenanceJob.build(
                job_type="behavior_governance",
                learner_profile_id=profile.id,
                due_at=due_at,
                idempotency_key="memory-maintenance:test:profile:behavior",
            )
            await repository.create(failing)
            failed = failing.fail(error_code="RuntimeError")
            await repository.update(failed)
            failed_stored = await repository.get_by_id(failed.id)

            await session.commit()

        assert duplicate.id == created.id
        assert len(due_jobs) == 1
        assert claimed.status == "claimed"
        assert claimed.lease_owner == "test-worker"
        assert active_lease_rejected is True
        assert active_claim_stored is not None
        assert active_claim_stored.lease_owner == "test-worker"
        assert len(expired_due) == 1
        assert reclaimed.lease_owner == "recovery-worker"
        assert completed_stored is not None
        assert completed_stored.status == "completed"
        assert completed_stored.attempt_count == 1
        assert failed_stored is not None
        assert failed_stored.status == "failed"
        assert failed_stored.attempt_count == 1
        assert failed_stored.error_code == "RuntimeError"
    finally:
        await engine.dispose()
