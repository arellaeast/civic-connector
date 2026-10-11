"""Baltimore 311 adapter, built on the Socrata client.

The 311 service-request dataset ID is deliberately NOT hardcoded: set
BALTIMORE_311_DATASET_ID. Find it by browsing Open Baltimore
(https://data.baltimorecity.gov) for the "311 Service Requests" dataset —
open the dataset, click "API", and copy the xxxx-xxxx ID from the API URL.
While there, verify BALTIMORE_311_SR_COLUMN against the dataset's column
names (dataset page -> "View Data").
"""

from __future__ import annotations

from typing import Any

from src.adapters.baltimore.open_data import ConfigurationError, SocrataClient


class ThreeOneOneAdapter:
    """Query Baltimore 311 service requests via the Socrata dataset."""

    def __init__(
        self,
        socrata: SocrataClient,
        dataset_id: str | None,
        sr_column: str = "srnumber",
    ) -> None:
        self.socrata = socrata
        self.dataset_id = dataset_id
        self.sr_column = sr_column

    def _require_dataset(self) -> str:
        if not self.dataset_id:
            raise ConfigurationError(
                "BALTIMORE_311_DATASET_ID is not set. Find the 311 Service Requests "
                "dataset on Open Baltimore (https://data.baltimorecity.gov), open its "
                "API documentation, and set BALTIMORE_311_DATASET_ID to the dataset's "
                "ID (the xxxx-xxxx code). Also verify BALTIMORE_311_SR_COLUMN matches "
                "the dataset's service-request-number column."
            )
        return self.dataset_id

    async def get_311_requests(
        self,
        status: str | None = None,
        service_code: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List 311 service requests, optionally filtered.

        status: e.g. "open" or "closed" (matched case-insensitively against the
        dataset's status column). service_code: the 311 service code, if known.
        """
        dataset_id = self._require_dataset()
        clauses = []
        if status:
            clauses.append(f"upper(status)='{status.upper()}'")
        if service_code:
            clauses.append(f"service_code='{service_code}'")
        where = " AND ".join(clauses) if clauses else None
        return await self.socrata.query(dataset_id, where=where, limit=limit)

    async def get_311_request(self, request_id: str) -> dict[str, Any] | None:
        """Look up a single 311 request by its service-request number."""
        dataset_id = self._require_dataset()
        safe_id = request_id.replace("'", "''")  # SoQL string escaping
        rows = await self.socrata.query(
            dataset_id, where=f"{self.sr_column}='{safe_id}'", limit=1
        )
        return rows[0] if rows else None
