"""Rate limit key security tests.

Verifies that the rate limiter never retains or emits raw learner / operator
credentials. All identifiers exposed via alert details must be hashed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_core.api.rate_limit import RateLimitMiddleware


class _RecordingAlertDispatcher:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def dispatch(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _build_app(per_minute: int, dispatcher: _RecordingAlertDispatcher) -> FastAPI:
    app = FastAPI()

    @app.post("/api/v1/target")
    async def target() -> dict[str, str]:
        return {"ok": "true"}

    app.add_middleware(RateLimitMiddleware, per_minute=per_minute, alert_dispatcher=dispatcher)
    return app


def test_rate_limit_does_not_leak_raw_learner_key() -> None:
    dispatcher = _RecordingAlertDispatcher()
    app = _build_app(per_minute=1, dispatcher=dispatcher)
    client = TestClient(app)

    raw_key = "super-secret-learner-access-key-12345"
    for _ in range(2):
        client.post("/api/v1/target", headers={"X-Learner-Key": raw_key})

    assert len(dispatcher.events) >= 1
    event = dispatcher.events[0]
    assert event["alert_name"] == "rate_limit_exceeded"

    details = event["details"]
    assert raw_key not in str(details), "raw learner key must not appear in alert details"
    assert raw_key not in event["message"], "raw learner key must not appear in alert message"
    assert "key_hash" in details
    assert details["scope"] == "learner"
    # Hash must be a hex prefix, not the raw value.
    assert all(c in "0123456789abcdef" for c in details["key_hash"].split(":", 1)[-1])


def test_rate_limit_does_not_leak_raw_operator_key() -> None:
    dispatcher = _RecordingAlertDispatcher()
    app = _build_app(per_minute=1, dispatcher=dispatcher)
    client = TestClient(app)

    raw_key = "super-secret-operator-api-key-67890"
    for _ in range(2):
        client.post("/api/v1/target", headers={"X-Operator-Key": raw_key})

    assert len(dispatcher.events) >= 1
    event = dispatcher.events[0]
    details = event["details"]
    assert raw_key not in str(details)
    assert raw_key not in event["message"]
    assert details["scope"] == "operator"


def test_rate_limit_returns_retry_after_header() -> None:
    dispatcher = _RecordingAlertDispatcher()
    app = _build_app(per_minute=1, dispatcher=dispatcher)
    client = TestClient(app)

    client.post("/api/v1/target", headers={"X-Learner-Key": "k1"})
    response = client.post("/api/v1/target", headers={"X-Learner-Key": "k1"})

    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "60"
    body = response.json()
    assert body["error"]["code"] == "rate_limit_exceeded"
    assert body["error"]["retry_after_seconds"] == 60


def test_rate_limit_scopes_are_independent() -> None:
    dispatcher = _RecordingAlertDispatcher()
    app = _build_app(per_minute=1, dispatcher=dispatcher)
    client = TestClient(app)

    # Two different learner keys must not share a bucket.
    client.post("/api/v1/target", headers={"X-Learner-Key": "learner-A"})
    ok = client.post("/api/v1/target", headers={"X-Learner-Key": "learner-B"})
    assert ok.status_code == 200

    # Learner and operator with same raw string must still be separate buckets.
    client.post("/api/v1/target", headers={"X-Learner-Key": "shared"})
    ok = client.post("/api/v1/target", headers={"X-Operator-Key": "shared"})
    assert ok.status_code == 200


def test_rate_limit_falls_back_to_ip_when_no_credential() -> None:
    dispatcher = _RecordingAlertDispatcher()
    app = _build_app(per_minute=1, dispatcher=dispatcher)
    client = TestClient(app)

    client.post("/api/v1/target")
    response = client.post("/api/v1/target")
    assert response.status_code == 429
    assert dispatcher.events[0]["details"]["scope"] == "ip"
