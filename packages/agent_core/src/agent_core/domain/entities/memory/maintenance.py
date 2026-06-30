from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from agent_core.domain.errors import ValidationError

MEMORY_MAINTENANCE_JOB_TYPES = {
    "knowledge_governance",
    "knowledge_promotion_eligibility",
    "behavior_governance",
    "knowledge_compression",
    "behavior_compression",
    "conflict_refresh",
}
MEMORY_MAINTENANCE_JOB_STATUSES = {"scheduled", "claimed", "completed", "failed"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class MemoryMaintenanceJob:
    id: str
    job_type: str
    status: str
    learner_profile_id: str
    cursor: str | None
    payload: dict[str, Any]
    due_at: datetime
    lease_owner: str | None
    lease_expires_at: datetime | None
    attempt_count: int
    max_attempts: int
    idempotency_key: str
    error_code: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def build(
        cls,
        *,
        job_type: str,
        learner_profile_id: str,
        due_at: datetime,
        idempotency_key: str,
        payload: dict[str, Any] | None = None,
        max_attempts: int = 3,
    ) -> "MemoryMaintenanceJob":
        if job_type not in MEMORY_MAINTENANCE_JOB_TYPES:
            raise ValidationError("Unsupported memory maintenance job type.")
        if max_attempts < 1:
            raise ValidationError("max_attempts must be at least 1.")
        now = _utcnow()
        return cls(
            id=str(uuid4()),
            job_type=job_type,
            status="scheduled",
            learner_profile_id=learner_profile_id,
            cursor=None,
            payload=payload or {},
            due_at=due_at,
            lease_owner=None,
            lease_expires_at=None,
            attempt_count=0,
            max_attempts=max_attempts,
            idempotency_key=idempotency_key,
            error_code=None,
            created_at=now,
            updated_at=now,
        )

    def claim(self, *, lease_owner: str, lease_seconds: int) -> "MemoryMaintenanceJob":
        now = _utcnow()
        if self.status == "scheduled":
            pass
        elif self.status == "claimed" and self.lease_expires_at is not None and self.lease_expires_at <= now:
            pass
        else:
            raise ValidationError("Only due scheduled memory maintenance jobs can be claimed.")
        return MemoryMaintenanceJob(
            id=self.id,
            job_type=self.job_type,
            status="claimed",
            learner_profile_id=self.learner_profile_id,
            cursor=self.cursor,
            payload=dict(self.payload),
            due_at=self.due_at,
            lease_owner=lease_owner,
            lease_expires_at=now + timedelta(seconds=max(lease_seconds, 1)),
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            error_code=None,
            created_at=self.created_at,
            updated_at=now,
        )

    def progress(self, *, cursor: str | None, due_at: datetime) -> "MemoryMaintenanceJob":
        now = _utcnow()
        return MemoryMaintenanceJob(
            id=self.id,
            job_type=self.job_type,
            status="scheduled",
            learner_profile_id=self.learner_profile_id,
            cursor=cursor,
            payload=dict(self.payload),
            due_at=due_at,
            lease_owner=None,
            lease_expires_at=None,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            error_code=None,
            created_at=self.created_at,
            updated_at=now,
        )

    def complete(self) -> "MemoryMaintenanceJob":
        now = _utcnow()
        return MemoryMaintenanceJob(
            id=self.id,
            job_type=self.job_type,
            status="completed",
            learner_profile_id=self.learner_profile_id,
            cursor=self.cursor,
            payload=dict(self.payload),
            due_at=self.due_at,
            lease_owner=self.lease_owner,
            lease_expires_at=self.lease_expires_at,
            attempt_count=self.attempt_count,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            error_code=None,
            created_at=self.created_at,
            updated_at=now,
        )

    def retry(self, *, due_at: datetime, error_code: str | None) -> "MemoryMaintenanceJob":
        now = _utcnow()
        return MemoryMaintenanceJob(
            id=self.id,
            job_type=self.job_type,
            status="scheduled",
            learner_profile_id=self.learner_profile_id,
            cursor=self.cursor,
            payload=dict(self.payload),
            due_at=due_at,
            lease_owner=None,
            lease_expires_at=None,
            attempt_count=self.attempt_count + 1,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            error_code=error_code,
            created_at=self.created_at,
            updated_at=now,
        )

    def fail(self, *, error_code: str | None) -> "MemoryMaintenanceJob":
        now = _utcnow()
        return MemoryMaintenanceJob(
            id=self.id,
            job_type=self.job_type,
            status="failed",
            learner_profile_id=self.learner_profile_id,
            cursor=self.cursor,
            payload=dict(self.payload),
            due_at=self.due_at,
            lease_owner=self.lease_owner,
            lease_expires_at=self.lease_expires_at,
            attempt_count=self.attempt_count + 1,
            max_attempts=self.max_attempts,
            idempotency_key=self.idempotency_key,
            error_code=error_code,
            created_at=self.created_at,
            updated_at=now,
        )
