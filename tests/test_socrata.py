"""Tests for the Socrata client (mocked with respx; no network)."""

import httpx
import pytest
import respx

from src.adapters.baltimore.open_data import SocrataClient, SocrataError

DOMAIN = "data.baltimorecity.gov"
DATASET = "abcd-1234"
RESOURCE_URL = f"https://{DOMAIN}/resource/{DATASET}.json"


@pytest.mark.asyncio
@respx.mock
async def test_query_builds_soda_url_and_params():
    route = respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=[{"a": 1}]))
    client = SocrataClient(domain=DOMAIN)
    try:
        rows = await client.query(DATASET, where="zip='21217'", limit=10)
    finally:
        await client.aclose()
    assert rows == [{"a": 1}]
    request = route.calls[0].request
    assert request.url.params["$where"] == "zip='21217'"
    assert request.url.params["$limit"] == "10"


@pytest.mark.asyncio
@respx.mock
async def test_query_sends_app_token_header():
    route = respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=[]))
    client = SocrataClient(domain=DOMAIN, app_token="secret-token")
    try:
        await client.query(DATASET)
    finally:
        await client.aclose()
    assert route.calls[0].request.headers["X-App-Token"] == "secret-token"


@pytest.mark.asyncio
@respx.mock
async def test_query_omits_app_token_header_when_unset():
    route = respx.get(RESOURCE_URL).mock(return_value=httpx.Response(200, json=[]))
    client = SocrataClient(domain=DOMAIN)
    try:
        await client.query(DATASET)
    finally:
        await client.aclose()
    assert "X-App-Token" not in route.calls[0].request.headers


@pytest.mark.asyncio
@respx.mock
async def test_query_404_raises_socrata_error():
    respx.get(f"https://{DOMAIN}/resource/nope-0000.json").mock(
        return_value=httpx.Response(404, json={"message": "Dataset not found"})
    )
    client = SocrataClient(domain=DOMAIN)
    try:
        with pytest.raises(SocrataError):
            await client.query("nope-0000")
    finally:
        await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_list_datasets_parses_catalog():
    route = respx.get("https://api.us.socrata.com/api/catalog/v1").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "resource": {
                            "id": "abcd-1234",
                            "name": "311 Service Requests",
                            "description": "All 311 requests",
                        }
                    }
                ]
            },
        )
    )
    client = SocrataClient(domain=DOMAIN)
    try:
        out = await client.list_datasets(search="311")
    finally:
        await client.aclose()
    assert out == [
        {"id": "abcd-1234", "name": "311 Service Requests", "description": "All 311 requests"}
    ]
    request = route.calls[0].request
    assert request.url.params["domains"] == DOMAIN
    assert request.url.params["search"] == "311"
