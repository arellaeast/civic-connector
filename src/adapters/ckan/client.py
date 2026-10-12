"""CKAN Action API client — fully implemented.

Portable client for cities whose open-data portal runs on CKAN: only the
API base URL changes (see docs/ADDING_A_CITY.md).

Real API patterns used (verified live against data.gov.au, open.canada.ca,
and demo.ckan.org on 2026-10-12; no invented endpoints):
- Dataset catalog: GET {base}/api/3/action/package_search?q=...&rows=...
- Dataset detail:  GET {base}/api/3/action/package_show?id=...
- Tabular query:   GET {base}/api/3/action/datastore_search?resource_id=...
                        &q=...&limit=...&offset=...

Only resources uploaded to the CKAN DataStore (``datastore_active: true``)
are queryable via datastore_search. list_datasets() surfaces each
resource's datastore flag so callers can pick a queryable one.
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

USER_AGENT = "civic-connector/0.1"


class CKANError(Exception):
    """The CKAN API returned an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ConfigurationError(Exception):
    """A required setting (portal URL, ...) is missing."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, CKANError) and (
        exc.status_code is None or exc.status_code >= 500 or exc.status_code == 429
    )


def _retry_decorator() -> Any:
    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )


def _summarize_resource(resource: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": resource.get("id"),
        "name": resource.get("name"),
        "format": resource.get("format"),
        "datastore_active": bool(resource.get("datastore_active")),
        "url": resource.get("url"),
    }


def _summarize_package(package: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": package.get("id"),
        "title": package.get("title"),
        "description": package.get("notes"),
        "resources": [_summarize_resource(r) for r in package.get("resources", [])],
    }


class CKANClient:
    """Async client for a CKAN open-data portal with Redis caching."""

    def __init__(
        self,
        api_base_url: str,
        api_key: str | None = None,
        cache: Cache | None = None,
        cache_ttl: int = 300,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """api_base_url is the Action API root, e.g.
        ``https://data.gov.lr/api/3/action`` (no trailing slash)."""
        self.api_base_url = api_base_url.rstrip("/")
        self.api_key = api_key
        self.cache = cache
        self.cache_ttl = cache_ttl
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"User-Agent": USER_AGENT}
            if self.api_key:
                headers["Authorization"] = self.api_key
            self._client = httpx.AsyncClient(
                base_url=self.api_base_url, headers=headers, timeout=30
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @_retry_decorator()
    async def _action(self, action: str, params: dict[str, Any]) -> Any:
        """Call a CKAN Action API action; return its ``result`` payload."""
        client = await self._get_client()
        url = f"{self.api_base_url}/{action}"
        try:
            resp = await client.get(url, params=params)
        except httpx.TransportError:
            log.warning("CKAN transport error for %s", url)
            raise
        if resp.status_code != 200:
            raise CKANError(
                f"CKAN error {resp.status_code} for {url}: {resp.text[:200]}",
                status_code=resp.status_code,
            )
        try:
            data = resp.json()
        except ValueError:
            raise CKANError(
                f"CKAN returned non-JSON for {url}: {resp.text[:200]}",
                status_code=resp.status_code,
            ) from None
        if not isinstance(data, dict) or not data.get("success"):
            message = ""
            if isinstance(data, dict):
                err = data.get("error") or {}
                message = err.get("message", "") if isinstance(err, dict) else str(err)
            raise CKANError(
                f"CKAN action {action} failed: {message or resp.text[:200]}".strip(),
                status_code=resp.status_code,
            )
        return data["result"]

    @staticmethod
    def _cache_key(action: str, params: dict[str, Any]) -> str:
        raw = action + "?" + json.dumps(params, sort_keys=True, default=str)
        return "ckan:" + hashlib.sha256(raw.encode()).hexdigest()

    async def _cached(self, action: str, params: dict[str, Any], fetch: Any) -> Any:
        if self.cache is None:
            return await fetch()
        return await self.cache.cached(self._cache_key(action, params), self.cache_ttl, fetch)

    async def search_datasets(
        self, query: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search the portal catalog. Returns id, title, description, and
        each resource's id/name/format/datastore_active flag."""
        params: dict[str, Any] = {"rows": max(1, min(limit, 100))}
        if query:
            params["q"] = query

        async def fetch() -> list[dict[str, Any]]:
            result = await self._action("package_search", params)
            return [_summarize_package(p) for p in result.get("results", [])]

        return await self._cached("package_search", params, fetch)

    async def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        """Fetch one dataset (package) by id or slug, with its resources."""
        params: dict[str, Any] = {"id": dataset_id}

        async def fetch() -> dict[str, Any]:
            result = await self._action("package_show", params)
            return _summarize_package(result)

        return await self._cached("package_show", params, fetch)

    async def query_resource(
        self,
        resource_id: str,
        q: str | None = None,
        filters: dict[str, Any] | None = None,
        fields: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query rows from a DataStore resource. Returns ``{"total": N,
        "records": [...]}``.

        Only works for resources with ``datastore_active: true`` (see
        search_datasets). ``q`` is a full-text search; ``filters`` is a
        field->value mapping; ``fields`` is a comma-separated field list.
        """
        params: dict[str, Any] = {
            "resource_id": resource_id,
            "limit": max(1, min(limit, 1000)),
            "offset": max(0, offset),
        }
        if q:
            params["q"] = q
        if filters:
            params["filters"] = json.dumps(filters)
        if fields:
            params["fields"] = fields

        async def fetch() -> dict[str, Any]:
            result = await self._action("datastore_search", params)
            return {
                "total": result.get("total"),
                "records": result.get("records", []),
            }

        return await self._cached("datastore_search", params, fetch)
