# Civic Connector

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/arellaeast/civic-connector)

An open-source, citywide **MCP (Model Context Protocol) server for Baltimore**:
an AI-accessible layer over the city's public data and services, so any AI
assistant can answer residents' questions and help them navigate city services
in plain language.

Instead of digging through portals, a resident can ask *"Is my 311 request
fixed yet?"* or *"When's the next bus at my stop?"* — and any MCP-compatible
assistant can call this server's tools to find out.

## Architecture

```
                    +----------------------+
                    |    AI assistants     |
                    | (Claude, ChatGPT,    |
                    |  custom agents)      |
                    +----------+-----------+
                               |  MCP over Streamable HTTP
                               |  Bearer auth: API key or Supabase JWT
                    +----------v-----------+
                    |  civic-connector      |
                    |  FastMCP + city       |
                    |  adapters             |
                    +---+--------------+---+
                        |              |
              +---------v----+  +------v--------+
              |  Redis 7     |  | Postgres 17   |
              |  (API cache) |  | (usage logs)  |
              +---------+----+  +---------------+
                        |
        +---------------+------------------+
        |               |                  |
 +------v------+ +------v-------+ +--------v--------+
 | Open Balt.  | | MTA GTFS-RT  | | Baltimore 311   |
 | ArcGIS Hub  | | trip updates | | Feature Service |
 +-------------+ +--------------+ +-----------------+
```

Everything runs in Docker Compose: the app, Postgres (usage logs), and Redis
(upstream API cache). Upstream city APIs are the bottleneck, not this server —
responses are cached aggressively.

## Quickstart

**Option A — one click (no install):** click **Open in GitHub Codespaces**
above. It opens a ready-to-run environment in your browser.

**Option B — guided setup (recommended for cities):**

```bash
python3 init_wizard.py   # 2-minute walkthrough, auto-finds your 311 dataset
docker compose pull && docker compose up -d
```

**Option C — one command:** `./setup.sh` (runs the wizard, then starts
everything).

**Option D — manual:**

1. Copy the config: `cp .env.example .env`
2. (Optional) Fill in `MTA_GTFS_RT_URL`, `ARCGIS_311_SERVICE_URL`, and
   `AUTH_MODE` in `.env`. Every setting is documented in `.env.example`.
   The server runs with safe defaults until then.
3. Start everything: `docker compose up -d`

Then:

- MCP endpoint: `http://localhost:8000/mcp` (Streamable HTTP)
- Health: `http://localhost:8000/health`

Connect any MCP client (e.g. `mcp-remote`) to `http://localhost:8000/mcp`.
With the defaults, auth is disabled and the 311/transit tools will tell you
exactly which settings they need.

**Staying updated:** new releases are published as Docker images — update
with `docker compose pull && docker compose up -d`, or enable zero-touch
daily updates with `docker compose --profile auto-update up -d`. See
[docs/RUNBOOK.md](docs/RUNBOOK.md).

## MCP tools

| Tool | What it does |
|---|---|
| `query_open_data` | SQL queries against any Open Baltimore dataset (ArcGIS Hub) |
| `list_open_datasets` | Search the ArcGIS Hub catalog (find dataset item IDs) |
| `get_311_requests` | List 311 service requests, filterable by status |
| `get_311_request` | Look up one 311 request by service-request number |
| `get_transit_arrivals` | Real-time MTA arrivals at a GTFS stop |
| `get_trash_schedule` | Trash/recycling schedule (stub — no public DPW API exists yet) |

Every tool call is timed and recorded in Postgres (`usage_logs`) for grant
reporting and capacity planning.

## Configuration

All settings are environment variables — see `.env.example`, where each one
is documented. The important ones:

- `ARCGIS_311_SERVICE_URL` — the 311 Feature Service (has a working default
  for Baltimore's current-year requests; point it at another year's service
  if needed).
- `ARCGIS_HUB_OWNER` — owner of the Hub catalog (default `baltimore_city`).
- `MTA_GTFS_RT_URL` — required for transit; MTA's GTFS-RT Trip Updates feed.
- `AUTH_MODE` — `disabled` (dev), `apikey`, or `supabase`.
- `SOCRATA_DOMAIN` / `SOCRATA_APP_TOKEN` — only needed for Socrata-powered
  cities (see below).

No dataset IDs, feed URLs, or API endpoints are invented anywhere in this
repo: anything city-specific and unverified is env-configurable, with comments
saying where to find the real value.

## Other cities

Baltimore is the reference implementation, running on ArcGIS Hub. The ArcGIS
client, the GTFS-RT adapter, and the (separate) Socrata client are all
portable — most changes for a new city are config, not code. See
[docs/ADDING_A_CITY.md](docs/ADDING_A_CITY.md).

## Operations

**New here?** Start with [docs/AGENT_INSTALL.md](docs/AGENT_INSTALL.md) —
how to get this running on a server, including a copy-paste prompt you can
hand to an AI agent to install it for you.

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for deployment, key rotation, adding
datasets/tools, monitoring, backups, and scaling notes.

## License

MIT — see [LICENSE](LICENSE).
