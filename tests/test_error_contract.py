"""Error contract tests.

Verifies that backend errors surface a stable machine-readable `code` field
in the JSON envelope, and that the circuit breaker specifically returns
`circuit_open` (not the generic `service_unavailable`).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_core.api.error_handlers import register_error_handlers
from agent_core.domain.errors import NotFoundError, ProviderError, ServiceError, ValidationError


def _build_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise/service")
    async def raise_service() -> None:
        raise ServiceError("generic service failure")

    @app.get("/raise/circuit")
    async def raise_circuit() -> None:
        raise ServiceError("LLM provider circuit breaker is open.", error_code="circuit_open")

    @app.get("/raise/provider")
    async def raise_provider() -> None:
        raise ProviderError("LLM provider request failed.")

    @app.get("/raise/not-found")
    async def raise_not_found() -> None:
        raise NotFoundError("entity missing")

    @app.get("/raise/validation")
    async def raise_validation() -> None:
        raise ValidationError("bad input")

    return app


def test_service_error_without_code_uses_generic_code() -> None:
    client = TestClient(_build_app())
    response = client.get("/raise/service")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "service_unavailable"
    assert "generic service failure" in body["error"]["message"]


def test_service_error_with_circuit_open_code_is_preserved() -> None:
    client = TestClient(_build_app())
    response = client.get("/raise/circuit")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "circuit_open"


def test_provider_error_inherits_service_unavailable_code() -> None:
    client = TestClient(_build_app())
    response = client.get("/raise/provider")
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "service_unavailable"


def test_not_found_returns_404_with_code() -> None:
    client = TestClient(_build_app())
    response = client.get("/raise/not-found")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_validation_error_returns_400_with_code() -> None:
    client = TestClient(_build_app())
    response = client.get("/raise/validation")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_error"
