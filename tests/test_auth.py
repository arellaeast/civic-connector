"""Tests for bearer-token auth (no network except mocked JWKS)."""

import base64

import httpx
import pytest
import respx
from jose import jwt

import src.auth
from src.auth import AuthConfigurationError, AuthError, verify_bearer
from src.config import Settings

JWKS_URL = "https://example.supabase.co/auth/v1/.well-known/jwks.json"


def make_settings(**kwargs) -> Settings:
    base: dict = {"auth_mode": "disabled"}
    base.update(kwargs)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    src.auth._jwks_cache.clear()
    src.auth._jwks_fetched_at = 0.0
    yield
    src.auth._jwks_cache.clear()


@pytest.mark.asyncio
async def test_disabled_mode_passes_without_token():
    claims = await verify_bearer(None, make_settings(auth_mode="disabled"))
    assert claims["mode"] == "disabled"


@pytest.mark.asyncio
async def test_apikey_accepts_configured_key():
    s = make_settings(auth_mode="apikey", api_keys="secret1, secret2")
    claims = await verify_bearer("secret2", s)
    assert claims["mode"] == "apikey"


@pytest.mark.asyncio
async def test_apikey_rejects_wrong_key():
    s = make_settings(auth_mode="apikey", api_keys="secret1")
    with pytest.raises(AuthError):
        await verify_bearer("wrong", s)


@pytest.mark.asyncio
async def test_apikey_rejects_missing_token():
    s = make_settings(auth_mode="apikey", api_keys="secret1")
    with pytest.raises(AuthError):
        await verify_bearer(None, s)


@pytest.mark.asyncio
async def test_apikey_with_no_keys_configured_rejects_everything():
    s = make_settings(auth_mode="apikey", api_keys="")
    with pytest.raises(AuthError):
        await verify_bearer("anything", s)


@pytest.mark.asyncio
async def test_supabase_requires_jwks_url():
    s = make_settings(auth_mode="supabase", supabase_jwks_url=None)
    with pytest.raises(AuthConfigurationError):
        await verify_bearer("whatever", s)


def _rsa_jwks_and_token():
    """Generate an RSA key, a JWKS doc, and a token signed by the key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = (
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
    )
    numbers = key.public_key().public_numbers()

    def b64url_int(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "test-key",
                "use": "sig",
                "alg": "RS256",
                "n": b64url_int(numbers.n, 256),
                "e": b64url_int(numbers.e, 3),
            }
        ]
    }
    token = jwt.encode({"sub": "user-123"}, private_pem, algorithm="RS256", headers={"kid": "test-key"})
    return jwks, token


@pytest.mark.asyncio
@respx.mock
async def test_supabase_accepts_valid_token():
    jwks, token = _rsa_jwks_and_token()
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks))
    s = make_settings(auth_mode="supabase", supabase_jwks_url=JWKS_URL)
    claims = await verify_bearer(token, s)
    assert claims["sub"] == "user-123"
    assert claims["mode"] == "supabase"


@pytest.mark.asyncio
@respx.mock
async def test_supabase_rejects_malformed_token():
    jwks, _ = _rsa_jwks_and_token()
    respx.get(JWKS_URL).mock(return_value=httpx.Response(200, json=jwks))
    s = make_settings(auth_mode="supabase", supabase_jwks_url=JWKS_URL)
    with pytest.raises(AuthError):
        await verify_bearer("not-a-jwt", s)
