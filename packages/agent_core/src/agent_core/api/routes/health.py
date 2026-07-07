from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.api.dependencies import (
    get_circuit_breaker,
    get_db_session,
    get_embedding_circuit_breaker,
    get_llm_call_guard,
    get_redis_client,
)
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


@router.get("/guardrails/status")
async def guardrails_status() -> dict:
    guard = get_llm_call_guard()
    llm_breaker = get_circuit_breaker()
    embedding_breaker = get_embedding_circuit_breaker()
    result: dict = {}
    if guard is None:
        result["llm_call_guard"] = {"enabled": False}
    else:
        result["llm_call_guard"] = guard.current_usage
    if llm_breaker is None:
        result["llm_circuit_breaker"] = {"enabled": False}
        # Backward-compatible alias for existing consumers.
        result["circuit_breaker"] = {"enabled": False}
    else:
        result["llm_circuit_breaker"] = llm_breaker.status
        result["circuit_breaker"] = llm_breaker.status
    if embedding_breaker is None:
        result["embedding_circuit_breaker"] = {"enabled": False}
    else:
        result["embedding_circuit_breaker"] = embedding_breaker.status
    return result
