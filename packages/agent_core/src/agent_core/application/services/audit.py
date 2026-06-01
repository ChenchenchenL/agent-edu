from __future__ import annotations

from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_core.domain.entities.audit import AuditEvent
from agent_core.infrastructure.db.repositories import AuditRepository
from agent_core.infrastructure.observability.metrics import observe_audit_write


class AuditService:
    def __init__(
        self,
        repository: AuditRepository,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._repository = repository
        self._session_factory = session_factory

    async def record(
        self,
        *,
        event_type: str,
        resource_type: str,
        resource_id: str | None,
        actor: str,
        event_data: dict[str, Any],
    ) -> AuditEvent:
        started_at = perf_counter()
        event = AuditEvent.build(
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            event_data=event_data,
        )
        try:
            await self._repository.create(event)
        except Exception:
            observe_audit_write(
                mode="transactional",
                status="failed",
                duration_seconds=perf_counter() - started_at,
            )
            raise
        observe_audit_write(
            mode="transactional",
            status="completed",
            duration_seconds=perf_counter() - started_at,
        )
        return event

    async def record_durable(
        self,
        *,
        event_type: str,
        resource_type: str,
        resource_id: str | None,
        actor: str,
        event_data: dict[str, Any],
    ) -> AuditEvent:
        started_at = perf_counter()
        event = AuditEvent.build(
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            event_data=event_data,
        )
        if self._session_factory is None:
            try:
                await self._repository.create(event)
            except Exception:
                observe_audit_write(
                    mode="durable",
                    status="failed",
                    duration_seconds=perf_counter() - started_at,
                )
                raise
            observe_audit_write(
                mode="durable",
                status="completed",
                duration_seconds=perf_counter() - started_at,
            )
            return event

        async with self._session_factory() as session:
            repository = AuditRepository(session)
            try:
                await repository.create(event)
                await session.commit()
            except Exception:
                await session.rollback()
                observe_audit_write(
                    mode="durable",
                    status="failed",
                    duration_seconds=perf_counter() - started_at,
                )
                raise
        observe_audit_write(
            mode="durable",
            status="completed",
            duration_seconds=perf_counter() - started_at,
        )
        return event
