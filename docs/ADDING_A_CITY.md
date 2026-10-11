# Adding a city

The connector is built so Baltimore is just the first adapter. A new city is
a new package under `src/adapters/<city>/` plus one line in the registry.

## Steps

1. Copy `src/adapters/baltimore/` to `src/adapters/<city>/` as a starting
   point (or start from `src/adapters/base.py`).
2. Implement `CityAdapter`:
   - `name = "<city>"`
   - `register_tools(mcp)` — register the city's MCP tools with `@mcp.tool()`.
   - `health_check()` — report upstream statuses (optional, recommended).
3. Register it in `src/adapters/registry.py`:

   ```python
   if name == "<city>":
       return MyCityAdapter(settings, cache=cache)
   ```
4. Add the city's settings to `src/config.py` and document them in
   `.env.example`.
5. Set `CITY_ADAPTER=<city>` and `docker compose up`.

## What's portable vs. what's city-specific

**Portable (reuse as-is):**
- `SocrataClient` (`open_data.py`) — any city on a Socrata portal only needs
  a different `SOCRATA_DOMAIN`. Dozens of US cities run Socrata.
- `TransitAdapter` (`transit.py`) — GTFS-RT is a national standard. Any
  agency's Trip Updates feed URL works; only the config value changes.
- Auth, caching, usage logging, Docker Compose — city-independent.

**City-specific (you'll write or configure):**
- 311 dataset ID and column names (every city's 311 export differs).
- Sanitation schedules (no standard API exists; see the stub's docstring).
- Any bespoke city APIs (permits portals, parking, etc.).

## Ground rules

- Never hardcode a dataset ID, feed URL, or column name you haven't verified
  against the city's actual data portal. Gate them behind env vars with
  comments saying where to find the real value.
- A tool that can't work yet must raise a clear configuration error, never
  return invented data. See `sanitation.py` for the pattern.
