"""Async Redis cache helper with JSON serialization."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import TypeVar

import redis.asyncio as redis

T = TypeVar("T")


class Cache:
    """Thin wrapper around redis.asyncio with JSON helpers."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        self._client = redis.from_url(self._url, decode_responses=True)
        await self._client.ping()

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _require(self) -> redis.Redis:
        if self._client is None:
            raise RuntimeError("Cache is not connected")
        return self._client

    async def get_json(self, key: str) -> object | None:
        raw = await self._require().get(key)
        return json.loads(raw) if raw is not None else None

    async def set_json(self, key: str, value: object, ttl: int) -> None:
        await self._require().set(key, json.dumps(value), ex=ttl)

    async def cached(self, key: str, ttl: int, fn: Callable[[], Awaitable[T]]) -> T:
        """Return the cached value for key, or compute it with fn and store it."""
        hit = await self.get_json(key)
        if hit is not None:
            return hit  # type: ignore[no-any-return]
        value = await fn()
        await self.set_json(key, value, ttl)
        return value
