"""Baltimore city adapter: wires city data sources into MCP tools."""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from src.adapters.baltimore.open_data import SocrataClient
from src.adapters.baltimore.sanitation import SanitationAdapter
from src.adapters.baltimore.services_311 import ThreeOneOneAdapter
from src.adapters.baltimore.transit import TransitAdapter
from src.adapters.base import CityAdapter
from src.cache import Cache
from src.config import Settings
from src.db import with_usage_logging


class BaltimoreAdapter(CityAdapter):
    """Reference implementation: Baltimore, MD."""

    name = "baltimore"

    def __init__(self, settings: Settings, cache: Cache | None = None) -> None:
        self.settings = settings
        self.socrata = SocrataClient(
            domain=settings.socrata_domain,
            app_token=settings.socrata_app_token,
            cache=cache,
            cache_ttl=settings.cache_ttl_seconds,
        )
        self.three_one_one = ThreeOneOneAdapter(
            socrata=self.socrata,
            dataset_id=settings.baltimore_311_dataset_id,
            sr_column=settings.baltimore_311_sr_column,
        )
        self.transit = TransitAdapter(feed_url=settings.mta_gtfs_rt_url)
        self.sanitation = SanitationAdapter()

    def register_tools(self, mcp: FastMCP) -> None:
        """Register Baltimore's MCP tools. Each call is usage-logged."""

        @mcp.tool()
        @with_usage_logging("query_open_data")
        async def query_open_data(
            dataset_id: str,
            where: str | None = None,
            select: str | None = None,
            order: str | None = None,
            limit: int = 50,
        ) -> list[dict[str, Any]]:
            """Query a Baltimore open-data dataset (Socrata SoQL).

            dataset_id is the xxxx-xxxx ID from data.baltimorecity.gov. Use
            `where` for filters, e.g. "zip='21217'". Use list_open_datasets
            to discover dataset IDs.
            """
            return await self.socrata.query(
                dataset_id, where=where, select=select, order=order, limit=limit
            )

        @mcp.tool()
        @with_usage_logging("list_open_datasets")
        async def list_open_datasets(
            search: str | None = None, limit: int = 20
        ) -> list[dict[str, Any]]:
            """Search Baltimore's open-data catalog. Returns id, name, description."""
            return await self.socrata.list_datasets(search=search, limit=limit)

        @mcp.tool()
        @with_usage_logging("get_311_requests")
        async def get_311_requests(
            status: str | None = None,
            service_code: str | None = None,
            limit: int = 20,
        ) -> list[dict[str, Any]]:
            """List Baltimore 311 service requests.

            status filters open/closed requests (e.g. status="open").
            Requires BALTIMORE_311_DATASET_ID to be configured.
            """
            return await self.three_one_one.get_311_requests(
                status=status, service_code=service_code, limit=limit
            )

        @mcp.tool()
        @with_usage_logging("get_311_request")
        async def get_311_request(request_id: str) -> dict[str, Any] | None:
            """Look up a single Baltimore 311 request by its service-request number."""
            return await self.three_one_one.get_311_request(request_id)

        @mcp.tool()
        @with_usage_logging("get_transit_arrivals")
        async def get_transit_arrivals(stop_id: str) -> list[dict[str, Any]]:
            """Real-time MTA arrivals at a stop (GTFS stop_id), sorted by time.

            Requires MTA_GTFS_RT_URL to be configured.
            """
            return await self.transit.get_transit_arrivals(stop_id)

        @mcp.tool()
        @with_usage_logging("get_trash_schedule")
        async def get_trash_schedule(address: str) -> dict[str, str]:
            """Trash/recycling collection schedule for a Baltimore address.

            Not yet implemented — Baltimore DPW has no public API for this.
            """
            return await self.sanitation.get_trash_schedule(address)

    async def health_check(self) -> dict[str, str]:
        """Check upstream dependencies. Never raises."""
        results: dict[str, str] = {}
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"https://{self.settings.socrata_domain}")
                results["socrata"] = "ok" if resp.status_code < 500 else f"http_{resp.status_code}"
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            results["socrata"] = f"error:{type(exc).__name__}"
        results["mta_gtfs_rt"] = (
            "configured" if self.settings.mta_gtfs_rt_url else "not_configured"
        )
        results["311_dataset"] = (
            "configured" if self.settings.baltimore_311_dataset_id else "not_configured"
        )
        return results
