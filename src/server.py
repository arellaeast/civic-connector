"""MCP server entrypoint: Streamable HTTP served by uvicorn.

Run locally:  docker compose up
              (or: uvicorn src.server:app --reload)

The MCP endpoint lives at /mcp (Streamable HTTP). /health is unauthenticated
for load balancers and container healthchecks; everything else requires a
bearer token when AUTH_MODE is not "disabled".
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from src.adapters.registry import get_adapter
from src.auth import AuthConfigurationError, AuthError, current_auth, verify_bearer
from src.cache import Cache
from src.config import Settings
from src.db import close_db, init_db

settings = Settings()
logging.basicConfig(level=settings.log_level.upper())
log = logging.getLogger(__name__)

mcp = FastMCP("civic-connector")
cache = Cache(settings.redis_url)
adapter = get_adapter(settings.city_adapter, settings, cache=cache)
adapter.register_tools(mcp)

# Build the Streamable HTTP app. This lazily creates the session manager,
# exposed afterwards as mcp.session_manager (public API documented for
# exactly this "mount in a larger app" use case).
mcp_http_app = mcp.streamable_http_app()


class AuthMiddleware(BaseHTTPMiddleware):
    """Enforce bearer auth on every route except /health."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == "/health":
            return await call_next(request)
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else None
        try:
            claims = await verify_bearer(token, settings)
        except AuthError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=401)
        except AuthConfigurationError as exc:
            log.error("Auth misconfigured: %s", exc)
            return JSONResponse({"detail": "Server auth misconfigured"}, status_code=500)
        current_auth.set(claims)
        return await call_next(request)


async def health(request: Request) -> JSONResponse:
    return JSONResponse(
        {"status": "ok", "city": adapter.name, "upstreams": await adapter.health_check()}
    )


@asynccontextmanager
async def lifespan(app: Starlette):  # type: ignore[no-untyped-def]
    """Connect Redis + Postgres, then run the MCP session manager.

    Note: the mounted MCP app's own lifespan does not propagate through
    Mount in this Starlette version, so the session manager is run here
    explicitly (once).
    """
    await cache.connect()
    try:
        await init_db(settings.database_url)
    # Usage logging is best-effort: the server must start even without Postgres.
    except Exception as exc:  # noqa: BLE001
        log.warning("Postgres unavailable; usage logging disabled: %s", exc)
    async with mcp.session_manager.run():
        yield
    await close_db()
    await cache.disconnect()


app = Starlette(
    routes=[
        Route("/health", health),
        Mount("/", app=mcp_http_app),
    ],
    lifespan=lifespan,
    middleware=[Middleware(AuthMiddleware)],
)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
