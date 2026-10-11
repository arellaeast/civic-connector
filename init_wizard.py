#!/usr/bin/env python3
"""Interactive first-run setup wizard for the Civic Connector.

Walks you through the handful of settings a city needs:
  1. Open-data platform (ArcGIS Hub or Socrata)
  2. 311 feed (auto-discovered from the Hub catalog / Socrata catalog)
  3. Optional GTFS-RT transit feed URL
  4. Auth mode (generates an API key for you if you pick "apikey")

Writes a ready-to-use .env file. Nothing is uploaded anywhere.

Run:  python3 init_wizard.py
"""

from __future__ import annotations

import json
import secrets
import sys
import urllib.parse
import urllib.request

SOCRATA_CATALOG_URL = "https://api.us.socrata.com/api/catalog/v1"
ARCGIS_SEARCH_URL = "https://www.arcgis.com/sharing/rest/search"
HEADERS = {"User-Agent": "civic-connector-setup-wizard"}


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nSetup cancelled.")
        sys.exit(1)
    return val or (default or "")


def get_json(url: str) -> dict | None:
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.load(resp)
    except Exception:  # noqa: BLE001 - wizard must degrade to manual entry
        return None


def find_arcgis_311_services(owner: str) -> list[dict]:
    """Search the ArcGIS Hub catalog for 311 Feature Services by owner."""
    params = urllib.parse.urlencode(
        {"q": f"311 owner:{owner}", "f": "json", "num": 10}
    )
    data = get_json(f"{ARCGIS_SEARCH_URL}?{params}")
    if not data:
        return []
    out = []
    for item in data.get("results", []):
        if item.get("type") != "Feature Service":
            continue
        out.append(
            {
                "id": item.get("id", ""),
                "title": item.get("title", ""),
                "url": item.get("url", ""),
            }
        )
    return out


def find_socrata_311_datasets(domain: str) -> list[dict]:
    """Search the Socrata discovery catalog for likely 311 datasets."""
    params = urllib.parse.urlencode({"domains": domain, "q": "311", "limit": 10})
    data = get_json(f"{SOCRATA_CATALOG_URL}?{params}")
    if not data or data.get("error"):
        return []
    out = []
    for r in data.get("results", []):
        res = r.get("resource", {})
        if res.get("type") != "dataset":
            continue
        out.append(
            {
                "id": res.get("id", ""),
                "name": r.get("metadata", {}).get("name") or res.get("name", ""),
            }
        )
    return out


def main() -> None:
    print("=== Civic Connector setup ===\n")
    print("This takes about two minutes. Everything stays on your machine.\n")

    print("Open-data platform:")
    print("  1. ArcGIS Hub (Baltimore and many other cities)")
    print("  2. Socrata")
    platform = ask("Pick", "1")

    arcgis_owner = ""
    arcgis_311_url = ""
    socrata_domain = ""
    if platform == "2":
        socrata_domain = ask("Socrata open-data portal domain", "data.cityofnewyork.us")
        print(f"\nSearching the Socrata catalog for 311 datasets on {socrata_domain}...")
        candidates = find_socrata_311_datasets(socrata_domain)
        if candidates:
            print("Found these candidates (use the ID with the Socrata adapter):")
            for i, c in enumerate(candidates, 1):
                print(f"  {i}. {c['name']}  ({c['id']})")
        else:
            print("Couldn't reach the catalog (or no 311 datasets found).")
            print("Find the 311 dataset on the portal and note its xxxx-xxxx ID.")
    else:
        arcgis_owner = ask("ArcGIS Hub owner (the city's ArcGIS organization user)", "baltimore_city")
        print(f"\nSearching the ArcGIS Hub catalog for 311 services by '{arcgis_owner}'...")
        candidates = find_arcgis_311_services(arcgis_owner)
        if candidates:
            print("Found these candidates:")
            for i, c in enumerate(candidates, 1):
                print(f"  {i}. {c['title']}")
            print("   0. Skip / I'll paste a service URL myself")
            choice = ask("Pick a number", "1")
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                arcgis_311_url = candidates[int(choice) - 1]["url"]
                print(f"Using: {candidates[int(choice) - 1]['title']}")
            elif choice != "0":
                arcgis_311_url = choice  # user pasted a URL
        else:
            print("Couldn't reach the catalog (or no 311 services found).")
            arcgis_311_url = ask("311 Feature Service URL (Enter to use the default)")

    gtfs_url = ask("\nGTFS-RT Trip Updates feed URL (Enter to skip)")

    print("\nAuth mode:")
    print("  1. API key (recommended for cities)")
    print("  2. No auth (local testing only)")
    print("  3. Supabase JWT (you run Supabase Auth)")
    auth_choice = ask("Pick", "1")
    api_keys = ""
    jwks_url = ""
    if auth_choice == "3":
        jwks_url = ask("Supabase JWKS URL")
        auth_mode = "supabase"
    elif auth_choice == "2":
        auth_mode = "disabled"
    else:
        auth_mode = "apikey"
        api_keys = secrets.token_urlsafe(32)

    lines = [
        "# Generated by init_wizard.py — edit freely.",
        "",
        "MCP_HOST=0.0.0.0",
        "MCP_PORT=8000",
        "CITY_ADAPTER=baltimore",
        "LOG_LEVEL=INFO",
        "",
        "REDIS_URL=redis://cache:6379/0",
        "CACHE_TTL_SECONDS=300",
        "",
        "DATABASE_URL=postgresql://connector:connector@db:5432/civic_connector",
        "",
        f"ARCGIS_HUB_OWNER={arcgis_owner or 'baltimore_city'}",
        f"ARCGIS_311_SERVICE_URL={arcgis_311_url}",
        "",
        f"SOCRATA_DOMAIN={socrata_domain}",
        "SOCRATA_APP_TOKEN=",
        "",
        f"MTA_GTFS_RT_URL={gtfs_url}",
        "",
        f"AUTH_MODE={auth_mode}",
        f"API_KEYS={api_keys}",
        f"SUPABASE_JWKS_URL={jwks_url}",
        "",
    ]
    with open(".env", "w") as f:
        f.write("\n".join(lines) + "\n")

    print("\nWrote .env — you're configured.")
    if api_keys:
        print(f"\nYour API key (save this, it won't be shown again):\n  {api_keys}")
        print("Clients pass it as:  Authorization: Bearer <key>")
    print("\nNext:  docker compose pull && docker compose up -d")
    print("Then:  http://localhost:8000/health")


if __name__ == "__main__":
    main()
