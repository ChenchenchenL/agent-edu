from __future__ import annotations

from typing import Protocol


class DimensionMismatchError(ValueError):
    pass


class EmbeddingProvider(Protocol):
    provider_name: str
    model_name: str

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...
