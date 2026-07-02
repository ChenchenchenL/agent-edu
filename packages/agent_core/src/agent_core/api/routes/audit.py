from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import get_db_session, require_operator_api_key
from agent_core.domain.schemas.audit import AuditEventResponse
from agent_core.infrastructure.db.repositories import AuditRepository

router = APIRouter(tags=["audit"], dependencies=[Depends(require_operator_api_key)])


@router.get("/audit/events", response_model=list[AuditEventResponse])
async def list_audit_events(
    event_type: str | None = Query(default=None, max_length=128),
    resource_type: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEventResponse]:
    repo = AuditRepository(session)
    events = await repo.list_recent(
        event_type=event_type,
        resource_type=resource_type,
        limit=limit,
    )
    return [AuditEventResponse.model_validate(e) for e in events]
