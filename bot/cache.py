from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis


class RedisCache:
    def __init__(self, url: str) -> None:
        self._url = url
        self.client: redis.Redis | None = None

    async def connect(self) -> None:
        self.client = redis.from_url(self._url, decode_responses=True)
        await self.client.ping()

    async def close(self) -> None:
        if self.client:
            await self.client.close()

    def require_client(self) -> redis.Redis:
        if self.client is None:
            raise RuntimeError("Redis client is not initialized")
        return self.client

    async def set_json(self, key: str, value: Any, ex: int | None = None) -> None:
        payload = json.dumps(value)
        await self.require_client().set(key, payload, ex=ex)

    async def get_json(self, key: str) -> Any | None:
        raw = await self.require_client().get(key)
        if raw is None:
            return None
        return json.loads(raw)
