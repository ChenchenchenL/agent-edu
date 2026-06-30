"""Tests for F1 (rate limit), F3 (circuit breaker), F4 (LLM call guard), F5 (alert dispatcher)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_core.application.services.llm_guard import LLMCallGuard
from agent_core.domain.errors import ServiceError
from agent_core.infrastructure.llm.circuit_breaker import CircuitBreaker
from agent_core.infrastructure.observability.alerts import AlertDispatcher


class TestLLMCallGuard:
    def test_disabled_guard_always_allows(self) -> None:
        guard = LLMCallGuard(enabled=False, max_calls_per_hour=1)
        for _ in range(10):
            guard.check()

    def test_enabled_guard_blocks_after_limit(self) -> None:
        guard = LLMCallGuard(enabled=True, max_calls_per_hour=3)
        guard.check()
        guard.check()
        guard.check()
        with pytest.raises(ServiceError, match="LLM call budget exhausted"):
            guard.check()

    def test_current_usage_reflects_calls(self) -> None:
        guard = LLMCallGuard(enabled=True, max_calls_per_hour=100)
        guard.check()
        guard.check()
        usage = guard.current_usage
        assert usage["calls_in_window"] == 2
        assert usage["limit_per_hour"] == 100
        assert usage["enabled"] is True


class TestRateLimitMiddleware:
    def test_rate_limit_disabled_by_default(self, app_client_factory) -> None:
        client = app_client_factory()
        for _ in range(10):
            resp = client.post("/api/v1/sessions", json={"title": "test", "subject": "test"})
            assert resp.status_code == 200

    def test_rate_limit_blocks_writes_when_enabled(self, app_client_factory) -> None:
        client = app_client_factory(
            env_overrides={
                "AGENT_EDU_RATE_LIMIT_ENABLED": "1",
                "AGENT_EDU_RATE_LIMIT_PER_MINUTE": "2",
            }
        )
        resp1 = client.post("/api/v1/sessions", json={"title": "s1", "subject": "s1"})
        assert resp1.status_code == 200
        resp2 = client.post("/api/v1/sessions", json={"title": "s2", "subject": "s2"})
        assert resp2.status_code == 200
        resp3 = client.post("/api/v1/sessions", json={"title": "s3", "subject": "s3"})
        assert resp3.status_code == 429
        assert resp3.json()["error"]["code"] == "rate_limit_exceeded"

    def test_rate_limit_does_not_block_reads(self, app_client_factory) -> None:
        client = app_client_factory(
            env_overrides={
                "AGENT_EDU_RATE_LIMIT_ENABLED": "1",
                "AGENT_EDU_RATE_LIMIT_PER_MINUTE": "1",
            }
        )
        for _ in range(5):
            resp = client.get("/api/v1/sessions")
            assert resp.status_code == 200

    def test_rate_limit_does_not_block_health(self, app_client_factory) -> None:
        client = app_client_factory(
            env_overrides={
                "AGENT_EDU_RATE_LIMIT_ENABLED": "1",
                "AGENT_EDU_RATE_LIMIT_PER_MINUTE": "1",
            }
        )
        client.post("/api/v1/sessions", json={"title": "s1", "subject": "s1"})
        resp = client.get("/healthz")
        assert resp.status_code == 200


class TestLLMCallGuardIntegration:
    def test_llm_guard_blocks_after_limit(self, app_client_factory) -> None:
        client = app_client_factory(
            env_overrides={
                "AGENT_EDU_LLM_CALL_LIMIT_ENABLED": "1",
                "AGENT_EDU_LLM_CALL_LIMIT_PER_HOUR": "2",
            }
        )
        session = client.post("/api/v1/sessions", json={"title": "test", "subject": "test"})
        session_id = session.json()["id"]

        first = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "hello", "mode": "chat"},
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/sessions/{session_id}/messages",
            json={"content": "hello again", "mode": "chat"},
        )
        assert second.status_code == 200

        status = client.get("/guardrails/status")
        assert status.status_code == 200
        usage = status.json()["llm_call_guard"]
        assert usage["calls_in_window"] == 2
        assert usage["limit_per_hour"] == 2

        from agent_core.api.dependencies import get_llm_call_guard
        guard = get_llm_call_guard()
        assert guard is not None
        with pytest.raises(ServiceError, match="budget"):
            guard.check()

    def test_guardrails_status_endpoint(self, app_client_factory) -> None:
        client = app_client_factory(
            env_overrides={
                "AGENT_EDU_LLM_CALL_LIMIT_ENABLED": "1",
                "AGENT_EDU_LLM_CALL_LIMIT_PER_HOUR": "100",
            }
        )
        resp = client.get("/guardrails/status")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["llm_call_guard"]["enabled"] is True
        assert payload["llm_call_guard"]["limit_per_hour"] == 100

    def test_guardrails_status_disabled(self, app_client_factory) -> None:
        client = app_client_factory()
        resp = client.get("/guardrails/status")
        assert resp.status_code == 200
        assert resp.json()["llm_call_guard"]["enabled"] is False


class TestCircuitBreaker:
    def test_closed_state_allows_calls(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
        assert cb.state == "closed"
        cb.allow_call()

    def test_opens_after_threshold_failures(self) -> None:
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "closed"
        cb.record_failure()
        assert cb.state == "open"
        with pytest.raises(ServiceError, match="circuit breaker is open"):
            cb.allow_call()

    def test_success_resets_to_closed(self) -> None:
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0)
        cb.record_failure()
        cb.record_success()
        assert cb.state == "closed"
        assert cb.status["failure_count"] == 0

    def test_half_open_after_cooldown(self) -> None:
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.0)
        cb.record_failure()
        assert cb.state == "half_open"
        cb.allow_call()

    def test_status_reports_state(self) -> None:
        cb = CircuitBreaker(failure_threshold=5, cooldown_seconds=30.0)
        status = cb.status
        assert status["state"] == "closed"
        assert status["failure_threshold"] == 5
        assert status["cooldown_seconds"] == 30.0


class TestAlertDispatcher:
    def test_writes_to_log_file(self, tmp_path: Path) -> None:
        log_file = tmp_path / "alerts.log"
        dispatcher = AlertDispatcher(alert_log_path=str(log_file))
        dispatcher.dispatch(
            alert_name="test_alert",
            severity="warning",
            message="Test message",
            details={"key": "value"},
        )
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["alert_name"] == "test_alert"
        assert entry["severity"] == "warning"
        assert entry["message"] == "Test message"
        assert entry["details"]["key"] == "value"

    def test_multiple_alerts_append(self, tmp_path: Path) -> None:
        log_file = tmp_path / "alerts.log"
        dispatcher = AlertDispatcher(alert_log_path=str(log_file))
        dispatcher.dispatch(alert_name="a1", severity="info", message="first")
        dispatcher.dispatch(alert_name="a2", severity="warning", message="second")
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_no_log_path_falls_back_to_logger(self) -> None:
        dispatcher = AlertDispatcher()
        dispatcher.dispatch(alert_name="test", severity="info", message="no file")


class TestCircuitBreakerIntegration:
    def test_circuit_breaker_status_in_guardrails_endpoint(self, app_client_factory) -> None:
        client = app_client_factory(
            env_overrides={
                "AGENT_EDU_LLM_CIRCUIT_BREAKER_ENABLED": "1",
                "AGENT_EDU_LLM_CIRCUIT_BREAKER_FAILURE_THRESHOLD": "3",
            }
        )
        resp = client.get("/guardrails/status")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["circuit_breaker"]["state"] == "closed"
        assert payload["circuit_breaker"]["failure_threshold"] == 3

    def test_circuit_breaker_disabled_in_endpoint(self, app_client_factory) -> None:
        client = app_client_factory()
        resp = client.get("/guardrails/status")
        assert resp.status_code == 200
        assert resp.json()["circuit_breaker"]["enabled"] is False


class TestAlertDispatcherIntegration:
    def test_alert_log_written_on_rate_limit(self, app_client_factory, tmp_path: Path) -> None:
        log_file = tmp_path / "alerts.log"
        client = app_client_factory(
            env_overrides={
                "AGENT_EDU_RATE_LIMIT_ENABLED": "1",
                "AGENT_EDU_RATE_LIMIT_PER_MINUTE": "1",
                "AGENT_EDU_ALERT_LOG_PATH": str(log_file),
            }
        )
        client.post("/api/v1/sessions", json={"title": "s1", "subject": "s1"})
        client.post("/api/v1/sessions", json={"title": "s2", "subject": "s2"})
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert any("rate_limit_exceeded" in line for line in lines)
