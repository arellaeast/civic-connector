"""Socrata open-data client — fully implemented.

Used for Open Baltimore (data.baltimorecity.gov). Portable to any city whose
open-data portal runs on Socrata: only the domain changes.

Real API patterns used (no invented endpoints):
- SODA dataset queries: GET https://{domain}/resource/{id}.json?$where=...
- Dataset catalog:      GET https://api.us.socrata.com/api/catalog/v1?domains=...
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.cache import Cache

log = logging.getLogger(__name__)

CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
USER_AGENT = "civic-connector/0.1"


class SocrataError(Exception):
    """The Socrata API returned an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfigurationError(Exception):
    """A required setting (dataset ID, feed URL, ...) is missing."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, SocrataError) and (exc.status_code is None or exc.status_code >= 500 or exc.status_code == 429)


def _retry_decorator() -> Any:
    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )


class SocrataClient:
    """Async client for a Socrata open-data portal with Redis caching."""

    def __init__(
        self,
        domain: str,
        app_token: str | None = None,
        cache: Cache | None = None,
        cache_ttl: int = 300,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.domain = domain
        self.base_url = f"https://{domain}"
        self.app_token = app_token
        self.cache = cache
        self.cache_ttl = cache_ttl
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": USER_AGENT}
            if self.app_token:
                headers["X-App-Token"] = self.app_token
            self._client = httpx.AsyncClient(
                base_url=self.base_url, headers=headers, timeout=30
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @_retry_decorator()
    async def _get(self, url: str, params: dict[str, Any]) -> Any:
        client = await self._get_client()
        try:
            resp = await client.get(url, params=params)
        except httpx.TransportError:
            log.warning("Socrata transport error for %s", url)
            raise
        if resp.status_code == 200:
            return resp.json()
        raise SocrataError(
            f"Socrata error {resp.status_code} for {url}: {resp.text[:200]}",
            status_code=resp.status_code,
        )

    @staticmethod
    def _cache_key(url: str, params: dict[str, Any]) -> str:
        raw = url + "?" + json.dumps(params, sort_keys=True, default=str)
        return "socrata:" + hashlib.sha256(raw.encode()).hexdigest()

    async def query(
        self,
        dataset_id: str,
        where: str | None = None,
        select: str | None = None,
        order: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Run a SoQL query against a dataset. Returns rows as dicts.

        dataset_id is the xxxx-xxxx ID from the portal. ``where`` takes a SoQL
        filter, e.g. ``"zip='21217'"``. See https://dev.socrata.com/docs/queries/
        """
        params: dict[str, Any] = {"$limit": max(1, min(limit, 50000))}
        if where:
            params["$where"] = where
        if select:
            params["$select"] = select
        if order:
            params["$order"] = order
        url = f"{self.base_url}/resource/{dataset_id}.json"

        async def fetch() -> list[dict[str, Any]]:
            data = await self._get(url, params)
            if not isinstance(data, list):
                raise SocrataError(f"Unexpected Socrata response for dataset {dataset_id}")
            return data

        if self.cache is None:
            return await fetch()
        return await self.cache.cached(self._cache_key(url, params), self.cache_ttl, fetch)

    async def list_datasets(
        self, search: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search the Socrata catalog for datasets on this portal's domain."""
        params: dict[str, Any] = {"domains": self.domain, "limit": max(1, min(limit, 100))}
        if search:
            params["search"] = search

        async def fetch() -> list[dict[str, Any]]:
            data = await self._get(CATALOG_URL, params)
            out = []
            for item in data.get("results", []):
                resource = item.get("resource", {})
                out.append(
                    {
                        "id": resource.get("id"),
                        "name": resource.get("name"),
                        "description": resource.get("description"),
                    }
                )
            return out

        if self.cache is None:
            return await fetch()
        return await self.cache.cached(self._cache_key(CATALOG_URL, params), self.cache_ttl, fetch)
