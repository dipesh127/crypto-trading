from __future__ import annotations

import json
import time
from typing import Any

try:
    import redis.asyncio as redis
except Exception:  # pragma: no cover
    redis = None


class DashboardCache:
    def __init__(self, url: str, ttl: int = 5):
        self.ttl = ttl
        self.client = redis.from_url(url, decode_responses=True) if redis else None
        self._local: dict[str, tuple[float, Any]] = {}

    async def get(self, key: str):
        if self.client:
            value = await self.client.get(key)
            return json.loads(value) if value else None
        item = self._local.get(key)
        if not item or item[0] <= time.monotonic():
            self._local.pop(key, None)
            return None
        return item[1]

    async def set(self, key: str, value: Any):
        if self.client:
            await self.client.set(key, json.dumps(value), ex=self.ttl)
        else:
            self._local[key] = (time.monotonic() + self.ttl, value)

    async def invalidate(self, *keys: str):
        if self.client and keys:
            await self.client.delete(*keys)
        for key in keys:
            self._local.pop(key, None)
