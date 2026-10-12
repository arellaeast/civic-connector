"""Generic CKAN city adapter.

Any city whose open-data portal runs on CKAN (Liberia's data.gov.lr,
Sierra Leone's opendatasl.gov.sl, data.gov.au, open.canada.ca, ...) works
with zero code changes::

    CITY_ADAPTER=ckan
    CKAN_API_BASE_URL=https://data.gov.lr/api/3/action

Exposes the portal catalog and DataStore queries as MCP tools.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from src.adapters.base import CityAdapter
from src.adapters.ckan.client import CKANClient, ConfigurationError
from src.cache import Cache
from src.config import Settings
from src.db import with_usage_logging


class CKANAdapter(CityAdapter):
    """Reference generic adapter for any CKAN-powered open-data portal."""

    name = "ckan"

    def __init__(self, settings: Settings, cache: Cache | None = None) -> None:
        if not settings.ckan_api_base_url:
            raise ConfigurationError(
                "CKAN_API_BASE_URL is not set. Point it at the portal's Action "
                "API root, e.g. https://data.gov.lr/api/3/action"
            )
        self.settings = settings
        self.ckan = CKANClient(
            api_base_url=settings.ckan_api_base_url,
            cache=cache,
            cache_ttl=settings.cache_ttl_seconds,
        )

    def register_tools(self, mcp: FastMCP) -> None:
        """Register the CKAN catalog/query tools. Each call is usage-logged."""

        @mcp.tool()
        @with_usage_logging("query_open_data")
        async def query_open_data(
            resource_id: str,
            q: str | None = None,
            filters: dict[str, Any] | None = None,
            fields: str | None = None,
            limit: int = 50,
            offset: int = 0,
        ) -> dict[str, Any]:
            """Query rows from a CKAN open-data resource.

            resource_id is the resource ID from list_open_datasets (only
            resources with datastore_active=true are queryable). Use `q`
            for full-text search, `filters` for exact field matches
            (e.g. {"year": "2024"}), and `fields` for a comma-separated
            field list.
            """
            return await self.ckan.query_resource(
                resource_id, q=q, filters=filters, fields=fields,
                limit=limit, offset=offset,
            )

        @mcp.tool()
        @with_usage_logging("list_open_datasets")
        async def list_open_datasets(
            search: str | None = None, limit: int = 20
        ) -> list[dict[str, Any]]:
            """Search the CKAN open-data catalog. Returns id, title,
            description, and each resource's id, name, format, and
            datastore_active flag for every dataset."""
            return await self.ckan.search_datasets(query=search, limit=limit)

    async def health_check(self) -> dict[str, str]:
        """Check the CKAN portal. Never raises."""
        results: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{self.ckan.api_base_url}/status_show",
                    headers={"User-Agent": "civic-connector/0.1"},
                )
                results["ckan"] = (
                    "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
                )
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            results["ckan"] = f"error:{type(exc).__name__}"
        return results
