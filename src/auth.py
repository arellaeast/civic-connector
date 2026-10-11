"""Bearer-token authentication for the MCP HTTP layer.

Modes (AUTH_MODE):
- ``disabled``: no auth; every request is anonymous (local-dev default).
- ``apikey``:   ``Authorization: Bearer <key>`` checked against API_KEYS
  with a constant-time comparison.
- ``supabase``: Supabase JWTs validated against the project's JWKS
  (SUPABASE_JWKS_URL). The JWKS document is cached for one hour.
"""

from __future__ import annotations

import hmac
import time
from contextvars import ContextVar
from typing import Any

import httpx
from jose import JWTError, jwk, jwt

from src.config import Settings

# Claims for the request currently being handled; set by the auth middleware
# in src/server.py so tools (and usage logging) can identify the caller.
current_auth: ContextVar[dict[str, Any] | None] = ContextVar("current_auth", default=None)


class AuthError(Exception):
    """The bearer token is missing or invalid (HTTP 401)."""


class AuthConfigurationError(Exception):
    """Auth is misconfigured (HTTP 500)."""


_JWKS_TTL_SECONDS = 3600
_jwks_cache: dict[str, Any] = {}
_jwks_fetched_at: float = 0.0


async def _get_jwks(jwks_url: str) -> dict[str, Any]:
    """Fetch the JWKS document, cached in memory for one hour."""
    global _jwks_fetched_at
    now = time.time()
    if "keys" not in _jwks_cache or now - _jwks_fetched_at > _JWKS_TTL_SECONDS:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(jwks_url)
            resp.raise_for_status()
            _jwks_cache.clear()
            _jwks_cache.update(resp.json())
            _jwks_fetched_at = now
    return _jwks_cache


def _verify_supabase_token(token: str, jwks: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a JWT against a JWKS document. Returns claims or None."""
    try:
        header = jwt.get_unverified_header(token)
    except JWTError:
        return None
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key_data is None:
        return None
    try:
        key = jwk.construct(key_data)
        # Audience is not verified: deployments accept tokens issued for any
        # audience of the Supabase project. Set verify_aud per your policy.
        return jwt.decode(token, key, algorithms=["RS256"], options={"verify_aud": False})
    except JWTError:
        return None


async def verify_bearer(token: str | None, settings: Settings) -> dict[str, Any]:
    """Validate a bearer token according to AUTH_MODE.

    Returns a claims dict on success; raises AuthError (401) or
    AuthConfigurationError (500) otherwise.
    """
    mode = settings.auth_mode
    if mode == "disabled":
        return {"sub": "anonymous", "mode": "disabled"}
    if not token:
        raise AuthError("Missing bearer token")
    if mode == "apikey":
        for candidate in settings.api_key_list:
            if hmac.compare_digest(token, candidate):
                return {"sub": "api-key", "mode": "apikey"}
        raise AuthError("Invalid API key")
    if mode == "supabase":
        if not settings.supabase_jwks_url:
            raise AuthConfigurationError("SUPABASE_JWKS_URL must be set when AUTH_MODE=supabase")
        jwks = await _get_jwks(settings.supabase_jwks_url)
        claims = _verify_supabase_token(token, jwks)
        if claims is None:
            raise AuthError("Invalid JWT")
        claims["mode"] = "supabase"
        return claims
    raise AuthConfigurationError(f"Unknown AUTH_MODE: {mode!r}")
