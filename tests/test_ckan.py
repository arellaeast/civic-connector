"""Tests for the CKAN client and generic adapter (mocked with respx; no network)."""

import httpx
import pytest
import respx

from src.adapters.ckan.adapter import CKANAdapter
from src.adapters.ckan.client import CKANClient, CKANError, ConfigurationError
from src.adapters.registry import get_adapter
from src.config import Settings

BASE = "https://data.gov.lr/api/3/action"


def _ok(result):
    return {"success": True, "result": result}


@pytest.mark.asyncio
@respx.mock
async def test_search_datasets_builds_package_search_params():
    route = respx.get(f"{BASE}/package_search").mock(
        return_value=httpx.Response(200, json=_ok({"count": 1, "results": []}))
    )
    client = CKANClient(api_base_url=BASE)
    try:
        out = await client.search_datasets(query="census", limit=10)
    finally:
        await client.aclose()
    assert out == []
    params = route.calls[0].request.url.params
    assert params["q"] == "census"
    assert params["rows"] == "10"


@pytest.mark.asyncio
@respx.mock
async def test_search_datasets_summarizes_packages_and_resources():
    package = {
        "id": "pkg-1",
        "title": "Census 2024",
        "notes": "Population data",
        "resources": [
            {
                "id": "res-1",
                "name": "census.csv",
                "format": "CSV",
                "datastore_active": True,
                "url": "https://example.com/census.csv",
            },
            {"id": "res-2", "name": "docs.pdf", "format": "PDF"},
        ],
    }
    respx.get(f"{BASE}/package_search").mock(
        return_value=httpx.Response(200, json=_ok({"count": 1, "results": [package]}))
    )
    client = CKANClient(api_base_url=BASE)
    try:
        out = await client.search_datasets()
    finally:
        await client.aclose()
    assert out == [
        {
            "id": "pkg-1",
            "title": "Census 2024",
            "description": "Population data",
            "resources": [
                {
                    "id": "res-1",
                    "name": "census.csv",
                    "format": "CSV",
                    "datastore_active": True,
                    "url": "https://example.com/census.csv",
                },
                {
                    "id": "res-2",
                    "name": "docs.pdf",
                    "format": "PDF",
                    "datastore_active": False,
                    "url": None,
                },
            ],
        }
    ]


@pytest.mark.asyncio
@respx.mock
async def test_query_resource_builds_datastore_search_params():
    route = respx.get(f"{BASE}/datastore_search").mock(
        return_value=httpx.Response(
            200, json=_ok({"total": 2, "records": [{"a": 1}, {"a": 2}]})
        )
    )
    client = CKANClient(api_base_url=BASE)
    try:
        out = await client.query_resource(
            "res-1", q="monrovia", filters={"year": "2024"}, fields="a", limit=25, offset=5
        )
    finally:
        await client.aclose()
    assert out == {"total": 2, "records": [{"a": 1}, {"a": 2}]}
    params = route.calls[0].request.url.params
    assert params["resource_id"] == "res-1"
    assert params["q"] == "monrovia"
    assert params["filters"] == '{"year": "2024"}'
    assert params["fields"] == "a"
    assert params["limit"] == "25"
    assert params["offset"] == "5"


@pytest.mark.asyncio
@respx.mock
async def test_query_resource_clamps_limit():
    route = respx.get(f"{BASE}/datastore_search").mock(
        return_value=httpx.Response(200, json=_ok({"total": 0, "records": []}))
    )
    client = CKANClient(api_base_url=BASE)
    try:
        await client.query_resource("res-1", limit=999999)
    finally:
        await client.aclose()
    assert route.calls[0].request.url.params["limit"] == "1000"


@pytest.mark.asyncio
@respx.mock
async def test_success_false_raises_ckan_error():
    respx.get(f"{BASE}/datastore_search").mock(
        return_value=httpx.Response(
            200,
            json={"success": False, "error": {"message": "Resource not found"}},
        )
    )
    client = CKANClient(api_base_url=BASE)
    try:
        with pytest.raises(CKANError, match="Resource not found"):
            await client.query_resource("nope")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_http_error_raises_ckan_error_with_status():
    respx.get(f"{BASE}/package_search").mock(
        return_value=httpx.Response(404, text="not here")
    )
    client = CKANClient(api_base_url=BASE)
    try:
        with pytest.raises(CKANError) as exc_info:
            await client.search_datasets()
    finally:
        await client.aclose()
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@respx.mock
async def test_api_key_sent_as_authorization_header():
    route = respx.get(f"{BASE}/package_search").mock(
        return_value=httpx.Response(200, json=_ok({"count": 0, "results": []}))
    )
    client = CKANClient(api_base_url=BASE, api_key="secret")
    try:
        await client.search_datasets()
    finally:
        await client.aclose()
    assert route.calls[0].request.headers["Authorization"] == "secret"


def test_registry_returns_ckan_adapter():
    settings = Settings(ckan_api_base_url=BASE)
    adapter = get_adapter("ckan", settings)
    assert isinstance(adapter, CKANAdapter)
    assert adapter.name == "ckan"


def test_ckan_adapter_requires_api_base_url():
    settings = Settings(ckan_api_base_url=None)
    with pytest.raises(ConfigurationError, match="CKAN_API_BASE_URL"):
        CKANAdapter(settings)


def test_registry_still_rejects_unknown():
    with pytest.raises(ValueError, match="Unknown city adapter"):
        get_adapter("atlantis", Settings())
