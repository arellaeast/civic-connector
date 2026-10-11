"""Test fixtures.

Clears proxy environment variables: httpx reads them by default and some
environments set no_proxy entries (e.g. "[::1]") that httpx cannot parse,
which breaks client construction. Tests use respx mocks and need no proxy.
"""

import pytest

_PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "NO_PROXY",
    "no_proxy",
)


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch):
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
