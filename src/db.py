"""Postgres usage logging via asyncpg.

Keeps a minimal append-only log of MCP tool calls: which tool ran, who
called it, how long it took, and whether it succeeded. Used for grant
reporting, capacity planning, and debugging — not for tracking residents.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import asyncpg

from src.auth import current_auth

_pool: asyncpg.Pool | None = None

T = TypeVar("T")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_logs (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    tool_name TEXT NOT NULL,
    client_id TEXT,
    duration_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL
);
"""


async def init_db(database_url: str) -> None:
    """Create the connection pool and ensure the usage_logs table exists."""
    global _pool
    _pool = await asyncpg.create_pool(database_url)
    async with _pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def close_db() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def log_usage(
    tool_name: str,
    client_id: str | None,
    duration_ms: int,
    success: bool,
) -> None:
    """Record one tool call. Silently skips when the DB is unavailable."""
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO usage_logs (tool_name, client_id, duration_ms, success)"
            " VALUES ($1, $2, $3, $4)",
            tool_name,
            client_id,
            duration_ms,
            success,
        )


def with_usage_logging(
    tool_name: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator: time an async tool call and record it in usage_logs."""

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            start = time.perf_counter()
            auth = current_auth.get()
            client_id = auth.get("sub") if auth else None
            try:
                result = await fn(*args, **kwargs)
            except Exception:
                await log_usage(tool_name, client_id, _ms_since(start), False)
                raise
            await log_usage(tool_name, client_id, _ms_since(start), True)
            return result

        return wrapper

    return decorator


def _ms_since(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
