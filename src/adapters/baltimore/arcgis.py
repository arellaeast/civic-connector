"""ArcGIS REST client — Hub catalog search + Feature Service queries.

Used for Open Baltimore (data.baltimorecity.gov), which runs on ArcGIS Hub,
not Socrata. Portable to any city on ArcGIS Hub/Enterprise: only the hub
owner changes.

Real API patterns used (no invented endpoints):
- Hub/portal search: GET https://www.arcgis.com/sharing/rest/search?q=...&f=json
- Item metadata:     GET https://www.arcgis.com/sharing/rest/content/items/{id}?f=json
- Feature queries:   GET {service_url}/{layer}/query?where=...&outFields=...&f=json
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

from src.adapters.baltimore.open_data import ConfigurationError
from src.cache import Cache

log = logging.getLogger(__name__)

SHARING_URL = "https://www.arcgis.com/sharing/rest"
USER_AGENT = "civic-connector/0.1"


class ArcGISError(Exception):
    """The ArcGIS API returned an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, ArcGISError) and (
        exc.status_code is None or exc.status_code >= 500 or exc.status_code == 429
    )


def _retry_decorator() -> Any:
    return retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )


class ArcGISClient:
    """Async client for ArcGIS Hub catalog search and Feature Service queries."""

    def __init__(
        self,
        hub_owner: str | None = None,
        cache: Cache | None = None,
        cache_ttl: int = 300,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.hub_owner = hub_owner
        self.cache = cache
        self.cache_ttl = cache_ttl
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, timeout=30
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    @_retry_decorator()
    async def _get(self, url: str, params: dict[str, Any]) -> Any:
        client = await self._get_client()
        params = {**params, "f": "json"}
        try:
            resp = await client.get(url, params=params)
        except httpx.TransportError:
            log.warning("ArcGIS transport error for %s", url)
            raise
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, dict) and data.get("error"):
                raise ArcGISError(
                    f"ArcGIS error for {url}: {data['error']}",
                    status_code=resp.status_code,
                )
            return data
        raise ArcGISError(
            f"ArcGIS error {resp.status_code} for {url}: {resp.text[:200]}",
            status_code=resp.status_code,
        )

    @staticmethod
    def _cache_key(url: str, params: dict[str, Any]) -> str:
        raw = url + "?" + json.dumps(params, sort_keys=True, default=str)
        return "arcgis:" + hashlib.sha256(raw.encode()).hexdigest()

    async def _cached(self, url: str, params: dict[str, Any], fetch: Any) -> Any:
        if self.cache is None:
            return await fetch()
        return await self.cache.cached(self._cache_key(url, params), self.cache_ttl, fetch)

    async def search_datasets(
        self, search: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Search the Hub catalog for datasets owned by the configured hub owner.

        Returns id, title, description, type, and item URL for each result.
        """
        q = search or ""
        if self.hub_owner:
            q = f"{q} owner:{self.hub_owner}".strip()
        params: dict[str, Any] = {"q": q or "*", "num": max(1, min(limit, 100))}
        url = f"{SHARING_URL}/search"

        async def fetch() -> list[dict[str, Any]]:
            data = await self._get(url, params)
            out = []
            for item in data.get("results", []):
                out.append(
                    {
                        "id": item.get("id"),
                        "title": item.get("title"),
                        "description": item.get("description"),
                        "type": item.get("type"),
                        "url": item.get("url"),
                    }
                )
            return out

        return await self._cached(url, params, fetch)

    async def get_item(self, item_id: str) -> dict[str, Any]:
        """Fetch an ArcGIS item's metadata (title, type, service URL, ...)."""
        url = f"{SHARING_URL}/content/items/{item_id}"

        async def fetch() -> dict[str, Any]:
            return await self._get(url, {})

        return await self._cached(url, {}, fetch)

    async def query_feature_service(
        self,
        service_url: str,
        layer_id: int = 0,
        where: str | None = None,
        out_fields: str | None = None,
        order: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query a Feature Service layer. Returns row dicts (attributes only).

        ``where`` is an ArcGIS SQL filter, e.g. ``"SRStatus='Open'"``.
        ``out_fields`` is a comma-separated field list (default: all fields).
        """
        url = f"{service_url.rstrip('/')}/{layer_id}/query"
        params: dict[str, Any] = {
            "where": where or "1=1",
            "outFields": out_fields or "*",
            "returnGeometry": "false",
            "resultRecordCount": max(1, min(limit, 1000)),
        }
        if order:
            params["orderByFields"] = order

        async def fetch() -> list[dict[str, Any]]:
            data = await self._get(url, params)
            features = data.get("features", [])
            if not isinstance(features, list):
                raise ArcGISError(f"Unexpected ArcGIS response for {url}")
            return [f.get("attributes", {}) for f in features]

        return await self._cached(url, params, fetch)

    async def query_dataset(
        self,
        item_id: str,
        where: str | None = None,
        out_fields: str | None = None,
        order: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query a Hub catalog dataset by its item ID.

        Resolves the item to its Feature Service URL, then queries layer 0.
        Raises ConfigurationError if the item is not a queryable service.
        """
        item = await self.get_item(item_id)
        service_url = item.get("url")
        item_type = (item.get("type") or "")
        if not service_url or "Feature Service" not in item_type:
            raise ConfigurationError(
                f"Dataset {item_id} ('{item.get('title')}') is a {item_type or 'unknown type'}, "
                "not a queryable Feature Service. Pick a 'Feature Service' item from "
                "list_open_datasets."
            )
        return await self.query_feature_service(
            service_url, where=where, out_fields=out_fields, order=order, limit=limit
        )
