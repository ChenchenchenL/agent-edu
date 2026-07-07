"""Embedding provider circuit breaker tests.

Verifies that the DashScope-compatible embedding provider integrates with the
shared CircuitBreaker: failures are counted, the breaker opens after the
threshold, subsequent calls are rejected without hitting the network, and a
successful call resets the breaker.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from agent_core.domain.errors import ProviderError, ServiceError
from agent_core.infrastructure.embedding.dashscope_compatible_provider import (
    DashScopeCompatibleEmbeddingProvider,
)
from agent_core.infrastructure.llm.circuit_breaker import CircuitBreaker


class _FailingTransport(httpx.AsyncBaseTransport):
    def __init__(self, status_code: int = 500) -> None:
        self._status_code = status_code
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(
            status_code=self._status_code,
            json={"error": {"message": "simulated failure"}},
        )


class _OkTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.calls = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(
            status_code=200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2, 0.3]},
                    {"embedding": [0.4, 0.5, 0.6]},
                ]
            },
        )


def test_embedding_breaker_opens_after_threshold_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0, name="Embedding provider")
    transport = _FailingTransport()
    provider = DashScopeCompatibleEmbeddingProvider(
        api_key="test-key",
        base_url="http://embedding.test",
        model_name="test-model",
        timeout_seconds=5.0,
        circuit_breaker=breaker,
        transport=transport,
    )

    for _ in range(3):
        with pytest.raises(ProviderError):
            asyncio.run(provider.embed_texts(["hello"]))

    assert breaker.state == "open"
    assert transport.calls == 3

    # Next call must be rejected without hitting the transport.
    with pytest.raises(ServiceError, match="Embedding provider circuit breaker is open"):
        asyncio.run(provider.embed_texts(["hello"]))
    assert transport.calls == 3, "open breaker must not contact provider"


def test_embedding_breaker_success_resets_failure_count() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60.0, name="Embedding provider")
    failing = _FailingTransport()
    provider = DashScopeCompatibleEmbeddingProvider(
        api_key="test-key",
        base_url="http://embedding.test",
        model_name="test-model",
        timeout_seconds=5.0,
        circuit_breaker=breaker,
        transport=failing,
    )

    for _ in range(2):
        with pytest.raises(ProviderError):
            asyncio.run(provider.embed_texts(["hello"]))
    assert breaker.status["failure_count"] == 2

    # Swap to a successful transport on the same provider.
    provider._transport = _OkTransport()
    result = asyncio.run(provider.embed_texts(["a", "b"]))

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert breaker.state == "closed"
    assert breaker.status["failure_count"] == 0


def test_embedding_breaker_half_open_probe_after_cooldown() -> None:
    breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60.0, name="Embedding provider")
    transport = _FailingTransport()
    provider = DashScopeCompatibleEmbeddingProvider(
        api_key="test-key",
        base_url="http://embedding.test",
        model_name="test-model",
        timeout_seconds=5.0,
        circuit_breaker=breaker,
        transport=transport,
    )

    for _ in range(2):
        with pytest.raises(ProviderError):
            asyncio.run(provider.embed_texts(["hello"]))
    assert breaker.state == "open"

    # Force cooldown to elapse so the next call is allowed as a half-open probe.
    breaker._cooldown_seconds = 0.0
    with pytest.raises(ProviderError):
        asyncio.run(provider.embed_texts(["hello"]))
    assert transport.calls == 3, "half-open probe must contact provider"
    assert breaker.status["failure_count"] == 1, "failed probe resets failure count to 1"


def test_embedding_provider_without_breaker_does_not_raise_service_error() -> None:
    transport = _FailingTransport()
    provider = DashScopeCompatibleEmbeddingProvider(
        api_key="test-key",
        base_url="http://embedding.test",
        model_name="test-model",
        timeout_seconds=5.0,
        transport=transport,
    )

    # Without a breaker, repeated failures just keep raising ProviderError.
    for _ in range(10):
        with pytest.raises(ProviderError):
            asyncio.run(provider.embed_texts(["hello"]))
    assert transport.calls == 10
