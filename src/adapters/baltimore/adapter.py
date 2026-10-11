"""Baltimore city adapter: wires city data sources into MCP tools.

Open Baltimore (data.baltimorecity.gov) runs on ArcGIS Hub, so the open-data
catalog and 311 tools use the ArcGIS client. The Socrata client
(src/adapters/baltimore/open_data.py) stays in the codebase as the portable
client for Socrata-powered cities — see docs/ADDING_A_CITY.md.
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from src.adapters.baltimore.arcgis import ArcGISClient
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
        self.arcgis = ArcGISClient(
            hub_owner=settings.arcgis_hub_owner,
            cache=cache,
            cache_ttl=settings.cache_ttl_seconds,
        )
        self.three_one_one = ThreeOneOneAdapter(
            arcgis=self.arcgis,
            service_url=settings.arcgis_311_service_url,
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
            """Query a Baltimore open-data dataset (ArcGIS Hub catalog).

            dataset_id is the ArcGIS item ID from data.baltimorecity.gov
            (use list_open_datasets to discover them). Use `where` for
            filters, e.g. "CouncilDistrict='9'". Use `select` for a
            comma-separated field list.
            """
            return await self.arcgis.query_dataset(
                dataset_id,
                where=where,
                out_fields=select,
                order=order,
                limit=limit,
            )

        @mcp.tool()
        @with_usage_logging("list_open_datasets")
        async def list_open_datasets(
            search: str | None = None, limit: int = 20
        ) -> list[dict[str, Any]]:
            """Search Baltimore's open-data catalog (ArcGIS Hub). Returns id,
            title, description, type, and URL for each dataset."""
            return await self.arcgis.search_datasets(search=search, limit=limit)

        @mcp.tool()
        @with_usage_logging("get_311_requests")
        async def get_311_requests(
            status: str | None = None,
            service_code: str | None = None,
            limit: int = 20,
        ) -> list[dict[str, Any]]:
            """List Baltimore 311 service requests.

            status filters requests: "open", "closed", or a status fragment.
            service_code matches against the request type, e.g. "tree".
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
                if self.settings.arcgis_311_service_url:
                    resp = await client.get(
                        f"{self.settings.arcgis_311_service_url}?f=json"
                    )
                    results["arcgis_311"] = (
                        "ok" if resp.status_code == 200 else f"http_{resp.status_code}"
                    )
                else:
                    results["arcgis_311"] = "not_configured"
        except Exception as exc:  # noqa: BLE001 - health checks must not raise
            results["arcgis_311"] = f"error:{type(exc).__name__}"
        results["mta_gtfs_rt"] = (
            "configured" if self.settings.mta_gtfs_rt_url else "not_configured"
        )
        return results
