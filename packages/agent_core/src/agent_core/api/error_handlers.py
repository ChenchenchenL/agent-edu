from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from agent_core.domain.errors import NotFoundError, ServiceError, ValidationError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotFoundError)
    async def handle_not_found(_: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": str(exc)}},
        )

    @app.exception_handler(ValidationError)
    async def handle_validation(_: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "validation_error", "message": str(exc)}},
        )

    @app.exception_handler(ServiceError)
    async def handle_service(_: Request, exc: ServiceError) -> JSONResponse:
        # ServiceError may carry a typed error_code (e.g. `circuit_open`,
        # `provider_unavailable`). Fall back to `service_unavailable` when not
        # provided, so clients always receive a stable machine-readable code.
        code = getattr(exc, "error_code", None) or "service_unavailable"
        return JSONResponse(
            status_code=503,
            content={"error": {"code": code, "message": str(exc)}},
        )
