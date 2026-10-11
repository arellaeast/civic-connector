"""MTA transit adapter: real-time arrivals from a GTFS-RT feed.

Set MTA_GTFS_RT_URL to the MTA Maryland GTFS-RT Trip Updates feed URL, from
MTA's developer resources / transit data portal. The feed parsing below is a
real implementation against the GTFS-RT protobuf spec — only the feed URL is
left to the operator because it is not a stable public constant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from google.transit import gtfs_realtime_pb2
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.adapters.baltimore.open_data import ConfigurationError

USER_AGENT = "civic-connector/0.1"


class TransitAdapter:
    """Real-time transit arrivals from a GTFS-RT Trip Updates feed."""

    def __init__(self, feed_url: str | None) -> None:
        self.feed_url = feed_url

    @retry(
        retry=retry_if_exception_type(httpx.TransportError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )
    async def _fetch_feed(self) -> bytes:
        if not self.feed_url:
            raise ConfigurationError(
                "MTA_GTFS_RT_URL is not set. Get the MTA Maryland GTFS-RT Trip "
                "Updates feed URL from MTA's developer resources and set "
                "MTA_GTFS_RT_URL."
            )
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(self.feed_url)
            resp.raise_for_status()
            return resp.content

    async def get_transit_arrivals(self, stop_id: str) -> list[dict[str, Any]]:
        """Upcoming arrivals at a stop, from the GTFS-RT Trip Updates feed.

        stop_id is the GTFS stop_id (find it in the agency's static GTFS
        stops.txt). Returns arrivals sorted by time; empty list if none.
        """
        raw = await self._fetch_feed()
        feed = gtfs_realtime_pb2.FeedMessage()
        feed.ParseFromString(raw)

        arrivals: list[dict[str, Any]] = []
        for entity in feed.entity:
            if not entity.HasField("trip_update"):
                continue
            trip_update = entity.trip_update
            for stop_time in trip_update.stop_time_update:
                if stop_time.stop_id != stop_id:
                    continue
                arrival_ts = stop_time.arrival.time if stop_time.HasField("arrival") else None
                arrivals.append(
                    {
                        "trip_id": trip_update.trip.trip_id,
                        "route_id": trip_update.trip.route_id,
                        "stop_id": stop_id,
                        "arrival_time": (
                            datetime.fromtimestamp(arrival_ts, tz=UTC).isoformat()
                            if arrival_ts
                            else None
                        ),
                    }
                )
        arrivals.sort(key=lambda a: a["arrival_time"] or "")
        return arrivals
