"""Baltimore 311 adapter, built on the ArcGIS client.

Open Baltimore (data.baltimorecity.gov) runs on ArcGIS Hub. The 311 service
requests live in a Feature Service (default: the current year's
"311 Customer Service Requests"). Set ARCGIS_311_SERVICE_URL to point at a
different year's service if needed — find them via list_open_datasets or the
Hub search at https://bmore-open-data-baltimore.hub.arcgis.com.

Verified field names on the 311 service (do not invent others):
  ServiceRequestNum, SRType, SRStatus, CreatedDate, CloseDate, StatusDate,
  Agency, Address, Neighborhood, CouncilDistrict, Outcome
"""

from __future__ import annotations

from typing import Any

from src.adapters.baltimore.arcgis import ArcGISClient
from src.adapters.baltimore.open_data import ConfigurationError


class ThreeOneOneAdapter:
    """Query Baltimore 311 service requests via the ArcGIS Feature Service."""

    def __init__(self, arcgis: ArcGISClient, service_url: str | None) -> None:
        self.arcgis = arcgis
        self.service_url = service_url

    def _require_service(self) -> str:
        if not self.service_url:
            raise ConfigurationError(
                "ARCGIS_311_SERVICE_URL is not set. It should be the Feature "
                "Service URL for Baltimore's 311 requests, e.g. "
                "https://services1.arcgis.com/.../arcgis/rest/services/"
                "311_Customer_Service_Requests_current/FeatureServer. "
                "Use list_open_datasets to find it on the Hub catalog."
            )
        return self.service_url

    @staticmethod
    def _status_clause(status: str) -> str:
        """Map a plain-English status to an ArcGIS SQL filter on SRStatus.

        Observed SRStatus values include Open, New, Pending, Hold, Closed
        (each with " (Duplicate)" variants). "open" matches everything not
        closed; "closed" matches the Closed* variants.
        """
        s = status.strip().upper()
        if s == "OPEN":
            return "SRStatus NOT LIKE 'Closed%'"
        if s == "CLOSED":
            return "SRStatus LIKE 'Closed%'"
        safe = s.replace("'", "''")
        return f"UPPER(SRStatus) LIKE '%{safe}%'"

    async def get_311_requests(
        self,
        status: str | None = None,
        service_code: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List 311 service requests, optionally filtered.

        status: "open", "closed", or a status fragment (matched
        case-insensitively against SRStatus). service_code: matched
        case-insensitively against the SRType field, e.g. "tree".
        """
        service_url = self._require_service()
        clauses = []
        if status:
            clauses.append(self._status_clause(status))
        if service_code:
            safe = service_code.replace("'", "''")
            clauses.append(f"UPPER(SRType) LIKE '%{safe.upper()}%'")
        where = " AND ".join(clauses) if clauses else None
        return await self.arcgis.query_feature_service(
            service_url, where=where, order="CreatedDate DESC", limit=limit
        )

    async def get_311_request(self, request_id: str) -> dict[str, Any] | None:
        """Look up a single 311 request by its service-request number."""
        service_url = self._require_service()
        safe_id = request_id.replace("'", "''")  # ArcGIS SQL string escaping
        rows = await self.arcgis.query_feature_service(
            service_url, where=f"ServiceRequestNum='{safe_id}'", limit=1
        )
        return rows[0] if rows else None
