from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ValidationError as PydanticValidationError

from agent_core.domain.errors import ProviderError
from agent_core.infrastructure.embedding.types import EmbeddingProvider
from agent_core.infrastructure.llm.circuit_breaker import CircuitBreaker


class _EmbeddingDatum(BaseModel):
    embedding: list[float]


class _EmbeddingResponse(BaseModel):
    data: list[_EmbeddingDatum]


class DashScopeCompatibleEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        timeout_seconds: float,
        dimensions: int | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.provider_name = "dashscope_compatible"
        self.model_name = model_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._dimensions = dimensions
        self._circuit_breaker = circuit_breaker
        self._transport = transport

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        if self._circuit_breaker is not None:
            self._circuit_breaker.allow_call()

        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": texts,
            "encoding_format": "float",
        }
        if self._dimensions is not None:
            payload["dimensions"] = self._dimensions
        try:
            client_kwargs: dict[str, Any] = {
                "base_url": self._base_url,
                "timeout": self._timeout_seconds,
            }
            if self._transport is not None:
                client_kwargs["transport"] = self._transport
            async with httpx.AsyncClient(**client_kwargs) as client:
                response = await client.post(
                    "/embeddings",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
            response.raise_for_status()
            data = _EmbeddingResponse.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise ProviderError(
                f"Embedding provider request failed with status {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, PydanticValidationError) as exc:
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise ProviderError("Embedding provider request failed.") from exc

        vectors = [item.embedding for item in data.data]
        if len(vectors) != len(texts):
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise ProviderError(
                f"Embedding provider returned {len(vectors)} vectors; expected {len(texts)}."
            )

        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()
        return vectors
