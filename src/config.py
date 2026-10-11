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

    # Baltimore open data (Socrata)
    socrata_domain: str = "data.baltimorecity.gov"
    socrata_app_token: str | None = None

    # Baltimore 311 (Socrata dataset)
    baltimore_311_dataset_id: str | None = None
    baltimore_311_sr_column: str = "srnumber"

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
