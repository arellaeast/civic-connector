"""MCP server entrypoint: Streamable HTTP served by uvicorn.

Run locally:  docker compose up
              (or: uvicorn src.server:app --reload)

The MCP endpoint lives at /mcp (Streamable HTTP). / and /health are
unauthenticated (landing page and load-balancer health check); everything
else requires a bearer token when AUTH_MODE is not "disabled".
"""

from __future__ import annotations

import html
import logging
from contextlib import asynccontextmanager

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
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
    """Enforce bearer auth on every route except / and /health."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path in ("/", "/health"):
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


async def index(request: Request) -> HTMLResponse:
    """Human-readable landing page: what this is, its tools, how to connect."""
    tools = await mcp.list_tools()
    rows = "\n".join(
        "        <tr><td><code>{}</code></td><td>{}</td></tr>".format(
            html.escape(t.name), html.escape(t.description or "")
        )
        for t in tools
    )
    host = html.escape(request.headers.get("host", "localhost:8000"))
    scheme = html.escape(request.url.scheme)
    mcp_url = f"{scheme}://{host}/mcp"
    auth_note = (
        "No authentication is required by this server."
        if settings.auth_mode == "disabled"
        else "This server requires a bearer token (API key). "
        "Ask the city administrator for one."
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Civic Connector</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; max-width: 720px;
         margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; line-height: 1.5; }}
  h1 {{ font-size: 1.8rem; margin-bottom: 0.2rem; }}
  .tagline {{ color: #555; margin-top: 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
  td, th {{ border: 1px solid #ddd; padding: 0.5rem 0.75rem; text-align: left;
            vertical-align: top; }}
  th {{ background: #f5f5f5; }}
  code {{ background: #f0f0f0; padding: 0.1rem 0.35rem; border-radius: 4px;
          font-size: 0.9em; }}
  pre {{ background: #1e1e1e; color: #e8e8e8; padding: 1rem; border-radius: 8px;
         overflow-x: auto; font-size: 0.85em; }}
  pre .c {{ color: #7a7a7a; }}
  .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 1rem 1.25rem;
           margin: 1rem 0; }}
</style>
</head>
<body>
  <h1>Civic Connector</h1>
  <p class="tagline">An AI-accessible layer over city data and services.</p>
  <p>Any AI assistant that speaks the
  <a href="https://modelcontextprotocol.io">Model Context Protocol (MCP)</a>
  can call this server's tools to answer residents' questions &mdash; 311
  requests, transit arrivals, open data &mdash; in plain language.</p>

  <h2>Available tools</h2>
  <table>
    <tr><th>Tool</th><th>What it does</th></tr>
{rows}
  </table>

  <h2>Connect your agent</h2>
  <div class="card">
    <p><strong>Endpoint:</strong> <code>{mcp_url}</code>
    (Streamable HTTP)</p>
    <p>{auth_note}</p>
    <p><strong>Claude Desktop</strong> &mdash; add to your config file:</p>
<pre><span class="c">// ~/Library/Application Support/Claude/claude_desktop_config.json
// (Windows: %APPDATA%\\Claude\\claude_desktop_config.json)</span>
{{
  "mcpServers": {{
    "civic-connector": {{
      "command": "npx",
      "args": ["-y", "mcp-remote", "{mcp_url}",
               "--header", "Authorization: Bearer YOUR-API-KEY"]
    }}
  }}
}}</pre>
    <p><strong>Any other MCP client</strong> &mdash; point it at
    <code>{mcp_url}</code> using Streamable HTTP transport, with
    <code>Authorization: Bearer YOUR-API-KEY</code> if auth is enabled.</p>
  </div>

  <p><a href="/health">Server health</a> &middot;
  <a href="https://github.com/arellaeast/civic-connector">Source code</a></p>
</body>
</html>"""
    return HTMLResponse(page)


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
        Route("/", index),
        Route("/health", health),
        Mount("/", app=mcp_http_app),
    ],
    lifespan=lifespan,
    middleware=[Middleware(AuthMiddleware)],
)


if __name__ == "__main__":
    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)
