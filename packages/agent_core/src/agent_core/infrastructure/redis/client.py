from __future__ import annotations

from redis.asyncio import from_url


class RedisHealthClient:
    def __init__(self, url: str) -> None:
        self._client = from_url(url, decode_responses=True)

    async def ping(self) -> bool:
        return bool(await self._client.ping())
