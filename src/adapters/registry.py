"""Adapter registry: maps a city name to its CityAdapter."""

from __future__ import annotations

from src.adapters.baltimore.adapter import BaltimoreAdapter
from src.adapters.base import CityAdapter
from src.adapters.ckan.adapter import CKANAdapter
from src.cache import Cache
from src.config import Settings


def get_adapter(name: str, settings: Settings, cache: Cache | None = None) -> CityAdapter:
    """Return the adapter for ``name``.

    To add a city, implement CityAdapter in src/adapters/<city>/ and add a
    branch here. See docs/ADDING_A_CITY.md.
    """
    if name == "baltimore":
        return BaltimoreAdapter(settings, cache=cache)
    if name == "ckan":
        return CKANAdapter(settings, cache=cache)
    raise ValueError(f"Unknown city adapter: {name!r}. See docs/ADDING_A_CITY.md to add one.")
