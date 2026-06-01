from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import get_db_session, get_redis_client
from agent_core.domain.schemas.health import HealthResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/readyz", response_model=HealthResponse)
async def readyz(session: AsyncSession = Depends(get_db_session)) -> HealthResponse:
    await session.execute(text("SELECT 1"))
    await get_redis_client().ping()
    return HealthResponse(status="ready")
