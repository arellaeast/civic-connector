# Runbook

Operating guide for the Civic Connector MCP server.

## The easy path (for cities)

Designed so a city's IT staff can run this with minimal effort:

1. **Configure (2 minutes):** run `python3 init_wizard.py`. It asks for
   your Socrata portal, auto-finds the 311 dataset, and generates an API
   key. (Or run `./setup.sh`, which launches the wizard automatically.)
2. **Start:** `docker compose pull && docker compose up -d` — pulls the
   published image, no building from source.
3. **Stay updated, zero-touch (optional):**
   `docker compose --profile auto-update up -d` — Watchtower checks for
   new releases daily and restarts the app. Your `.env` config and
   database are never touched by updates.
4. **Backups:** `./scripts/backup.sh` — one command, timestamped SQL dump.
   Put it on a weekly cron.

Updates are safe by design: config lives in `.env`, data lives in the
`pgdata` volume, and database migrations run automatically on startup.

## Deploy (manual)

```bash
cp .env.example .env   # then fill in dataset IDs, feed URLs, auth
docker compose up -d --build
```

The MCP endpoint is `http://<host>:8000/mcp` (Streamable HTTP).
Health check: `GET /health` (unauthenticated) returns upstream statuses.

## Configuration

All settings are environment variables; see `.env.example` for the full list
with comments. The two values you must supply for a working deployment:

- `BALTIMORE_311_DATASET_ID` — the xxxx-xxxx ID of the 311 Service Requests
  dataset on Open Baltimore (https://data.baltimorecity.gov). Open the
  dataset, click "API", copy the ID.
- `MTA_GTFS_RT_URL` — MTA Maryland GTFS-RT Trip Updates feed URL, from MTA's
  developer resources.

Without them, the 311 and transit tools raise a clear configuration error
instead of returning invented data.

## Auth

`AUTH_MODE=disabled` (default) is for local development only.

- `apikey`: set `API_KEYS` to a comma-separated list. Rotate by replacing
  the list and restarting the app container (`docker compose restart app`).
  Old keys stop working immediately.
- `supabase`: set `SUPABASE_JWKS_URL` to your project's JWKS URL. Clients
  pass their Supabase JWT as the bearer token; the server validates it
  against the cached JWKS (refreshed hourly).

## Adding a dataset or tool

1. Find the dataset on Open Baltimore and note its ID and column names.
2. If it's Socrata, no new code is needed: the generic `query_open_data`
   tool already covers it. Document the dataset ID and useful `where`
   clauses in the README or your own docs.
3. For a new source type, add an adapter module under
   `src/adapters/baltimore/`, wire it into `BaltimoreAdapter`, and register
   the tool in `register_tools()`.

## Monitoring

- `GET /health` — app status plus upstream dependency checks (Socrata
  reachability, which optional integrations are configured).
- Logs: `docker compose logs -f app`. Tool calls, cache behavior, and auth
  failures are logged; set `LOG_LEVEL=DEBUG` for more detail.
- Usage: the `usage_logs` table in Postgres records tool name, caller,
  duration, and success for every MCP tool call. Query it for grant
  reporting or capacity planning.

## Backups

- Postgres volume `pgdata` holds usage logs. Back it up with
  `docker compose exec db pg_dump -U connector civic_connector > backup.sql`.
- Redis is a pure cache (maxmemory 256mb, LRU eviction) — no backup needed.

## Scaling notes

- The app is stateless except for the MCP session manager (stateful HTTP
  sessions by default). For multi-worker/multi-instance deployments, set
  `stateless_http=True` on the FastMCP server in `src/server.py` and put a
  load balancer in front.
- Upstream APIs (Socrata, MTA) are the real bottleneck, not this server.
  Raise `CACHE_TTL_SECONDS` if you hit their rate limits.
