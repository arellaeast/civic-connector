"""Application configuration via environment variables."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting maps to an env var of the same name (case-insensitive).

    See .env.example for documentation of each setting.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # MCP server
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8000
    city_adapter: str = "baltimore"
    log_level: str = "INFO"

    # Redis cache
    redis_url: str = "redis://cache:6379/0"
    cache_ttl_seconds: int = 300

    # Postgres usage logs
    database_url: str = "postgresql://connector:connector@db:5432/civic_connector"

    # Baltimore open data + 311 (ArcGIS Hub — Open Baltimore runs on it)
    arcgis_hub_owner: str = "baltimore_city"
    arcgis_311_service_url: str | None = (
        "https://services1.arcgis.com/UWYHeuuJISiGmgXx/arcgis/rest/services/"
        "311_Customer_Service_Requests_current/FeatureServer"
    )

    # Socrata (portable client for Socrata-powered cities; see docs/ADDING_A_CITY.md)
    socrata_domain: str | None = None
    socrata_app_token: str | None = None

    # CKAN (generic adapter for CKAN-powered portals; see docs/ADDING_A_CITY.md)
    # Full URL of the portal's Action API root, e.g.
    # https://data.gov.lr/api/3/action  (Liberia)
    # https://opendatasl.gov.sl/api/3/action  (Sierra Leone)
    ckan_api_base_url: str | None = None

    # MTA transit (GTFS-RT)
    mta_gtfs_rt_url: str | None = None

    # Auth
    auth_mode: Literal["disabled", "apikey", "supabase"] = "disabled"
    api_keys: str = ""
    supabase_jwks_url: str | None = None

    @property
    def api_key_list(self) -> list[str]:
        """Configured static API keys as a list."""
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]
