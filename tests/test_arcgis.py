"""Tests for the ArcGIS client and the 311 adapter (mocked with respx; no network)."""

import httpx
import pytest
import respx

from src.adapters.baltimore.arcgis import SHARING_URL, ArcGISClient, ArcGISError
from src.adapters.baltimore.open_data import ConfigurationError
from src.adapters.baltimore.services_311 import ThreeOneOneAdapter

SERVICE_URL = "https://services1.arcgis.com/ABC/arcgis/rest/services/311_Test/FeatureServer"
QUERY_URL = f"{SERVICE_URL}/0/query"

FEATURES = {
    "features": [
        {"attributes": {"ServiceRequestNum": "26-0001", "SRType": "TRS-Parking Complaint", "SRStatus": "Open"}},
        {"attributes": {"ServiceRequestNum": "26-0002", "SRType": "FOR-Tree Maintenance", "SRStatus": "Closed"}},
    ]
}


def _client(**kwargs):
    return ArcGISClient(hub_owner="baltimore_city", **kwargs)


@pytest.mark.asyncio
@respx.mock
async def test_query_feature_service_returns_attributes():
    route = respx.get(QUERY_URL).mock(return_value=httpx.Response(200, json=FEATURES))
    client = _client()
    try:
        rows = await client.query_feature_service(SERVICE_URL, where="1=1", limit=10)
    finally:
        await client.aclose()
    assert rows == [f["attributes"] for f in FEATURES["features"]]
    params = route.calls[0].request.url.params
    assert params["where"] == "1=1"
    assert params["resultRecordCount"] == "10"
    assert params["returnGeometry"] == "false"
    assert params["f"] == "json"


@pytest.mark.asyncio
@respx.mock
async def test_query_feature_service_error_payload_raises():
    respx.get(QUERY_URL).mock(
        return_value=httpx.Response(
            200, json={"error": {"code": 400, "message": "Invalid where clause"}}
        )
    )
    client = _client()
    try:
        with pytest.raises(ArcGISError):
            await client.query_feature_service(SERVICE_URL, where="bogus")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_search_datasets_scopes_to_owner():
    route = respx.get(f"{SHARING_URL}/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": "abc123",
                        "title": "311 Customer Service Requests 2026",
                        "description": "All 311 requests",
                        "type": "Feature Service",
                        "url": SERVICE_URL,
                    }
                ]
            },
        )
    )
    client = _client()
    try:
        out = await client.search_datasets(search="311")
    finally:
        await client.aclose()
    assert out[0]["id"] == "abc123"
    assert out[0]["type"] == "Feature Service"
    assert "owner:baltimore_city" in route.calls[0].request.url.params["q"]


@pytest.mark.asyncio
@respx.mock
async def test_query_dataset_resolves_item_to_service():
    respx.get(f"{SHARING_URL}/content/items/abc123").mock(
        return_value=httpx.Response(
            200,
            json={"id": "abc123", "title": "311 requests", "type": "Feature Service", "url": SERVICE_URL},
        )
    )
    route = respx.get(QUERY_URL).mock(return_value=httpx.Response(200, json=FEATURES))
    client = _client()
    try:
        rows = await client.query_dataset("abc123", where="SRStatus='Open'")
    finally:
        await client.aclose()
    assert len(rows) == 2
    assert route.calls[0].request.url.params["where"] == "SRStatus='Open'"


@pytest.mark.asyncio
@respx.mock
async def test_query_dataset_rejects_non_service_item():
    respx.get(f"{SHARING_URL}/content/items/xyz999").mock(
        return_value=httpx.Response(
            200, json={"id": "xyz999", "title": "A PDF report", "type": "PDF", "url": None}
        )
    )
    client = _client()
    try:
        with pytest.raises(ConfigurationError):
            await client.query_dataset("xyz999")
    finally:
        await client.aclose()


def _311(**kwargs):
    return ThreeOneOneAdapter(arcgis=_client(), service_url=SERVICE_URL, **kwargs)


@pytest.mark.asyncio
@respx.mock
async def test_311_open_status_clause():
    route = respx.get(QUERY_URL).mock(return_value=httpx.Response(200, json={"features": []}))
    adapter = _311()
    try:
        await adapter.get_311_requests(status="open")
    finally:
        await adapter.arcgis.aclose()
    assert route.calls[0].request.url.params["where"] == "SRStatus NOT LIKE 'Closed%'"


@pytest.mark.asyncio
@respx.mock
async def test_311_closed_status_clause():
    route = respx.get(QUERY_URL).mock(return_value=httpx.Response(200, json={"features": []}))
    adapter = _311()
    try:
        await adapter.get_311_requests(status="closed")
    finally:
        await adapter.arcgis.aclose()
    assert route.calls[0].request.url.params["where"] == "SRStatus LIKE 'Closed%'"


@pytest.mark.asyncio
@respx.mock
async def test_311_service_code_matches_sr_type():
    route = respx.get(QUERY_URL).mock(return_value=httpx.Response(200, json={"features": []}))
    adapter = _311()
    try:
        await adapter.get_311_requests(service_code="tree")
    finally:
        await adapter.arcgis.aclose()
    assert route.calls[0].request.url.params["where"] == "UPPER(SRType) LIKE '%TREE%'"


@pytest.mark.asyncio
@respx.mock
async def test_311_single_request_lookup():
    route = respx.get(QUERY_URL).mock(
        return_value=httpx.Response(200, json={"features": [FEATURES["features"][0]]})
    )
    adapter = _311()
    try:
        row = await adapter.get_311_request("26-0001")
    finally:
        await adapter.arcgis.aclose()
    assert row["ServiceRequestNum"] == "26-0001"
    assert route.calls[0].request.url.params["where"] == "ServiceRequestNum='26-0001'"


@pytest.mark.asyncio
async def test_311_missing_service_url_raises():
    adapter = ThreeOneOneAdapter(arcgis=_client(), service_url=None)
    try:
        with pytest.raises(ConfigurationError):
            await adapter.get_311_requests()
    finally:
        await adapter.arcgis.aclose()
