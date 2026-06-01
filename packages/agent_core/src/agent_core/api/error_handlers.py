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
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "service_unavailable", "message": str(exc)}},
        )
