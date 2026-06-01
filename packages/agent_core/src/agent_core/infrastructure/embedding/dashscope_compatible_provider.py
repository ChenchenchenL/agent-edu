from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ValidationError as PydanticValidationError

from agent_core.domain.errors import ProviderError
from agent_core.infrastructure.embedding.types import EmbeddingProvider


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
    ) -> None:
        self.provider_name = "dashscope_compatible"
        self.model_name = model_name
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._dimensions = dimensions

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": texts,
            "encoding_format": "float",
        }
        if self._dimensions is not None:
            payload["dimensions"] = self._dimensions
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
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
            raise ProviderError(
                f"Embedding provider request failed with status {exc.response.status_code}."
            ) from exc
        except (httpx.HTTPError, PydanticValidationError) as exc:
            raise ProviderError("Embedding provider request failed.") from exc

        vectors = [item.embedding for item in data.data]
        if len(vectors) != len(texts):
            raise ProviderError(
                f"Embedding provider returned {len(vectors)} vectors; expected {len(texts)}."
            )
        return vectors
