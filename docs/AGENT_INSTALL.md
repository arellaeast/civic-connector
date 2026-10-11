# Having an Agent Install This (For Cities)

You don't need to be technical to run the Civic Connector. You need two
things: a server (see below) and an AI agent (ChatGPT, Claude, or similar)
with a few details from you. The agent does the rest.

## The 30-second version

1. Get a small server (a $5–6/month VPS is plenty — options below).
2. Copy the prompt in the next section into your AI agent.
3. Answer its questions about your city.
4. It hands you back a working URL.

## Where to run it

Any server that runs Docker works. Minimum: 1 vCPU, 2 GB RAM, 25 GB disk.
Pick whichever is easiest for you:

| Option | Cost | Why pick it |
|---|---|---|
| **DigitalOcean** Basic droplet | ~$6/mo | Simplest control panel; easiest for non-technical staff |
| **Hetzner** CX22 | ~$5/mo | Cheapest reliable option |
| **Oracle Cloud** free tier | Free | 4 ARM cores / 24 GB RAM free — most generous, but signup and setup are clunkier |
| Your city's existing servers | — | If your IT team already runs infrastructure, deploy there — it's just Docker |

You do **not** need a domain name to start (the server works on an IP
address), but one makes the URL nicer for residents later.

## The copy-paste prompt

Give this to your AI agent, along with SSH access to the server:

> Install the Civic Connector on my server.
>
> Repository: https://github.com/arellaeast/civic-connector
>
> Steps:
> 1. Install Docker and Docker Compose if they aren't already installed.
> 2. Clone the repository to the server.
> 3. In the repo directory, run `python3 init_wizard.py` and answer its
>    questions for my city: **CITY NAME**, open-data portal **(URL if known)**.
> 4. Start everything: `docker compose pull && docker compose up -d`.
> 5. Verify it works: `curl http://localhost:8000/health` must return
>    `"status": "ok"`.
> 6. Open the firewall for port 8000 (or put it behind our reverse proxy).
> 7. Report back: the public URL, the MCP endpoint (`/mcp`), and the landing
>    page (`/`).
>
> Rules:
> - If anything needs a security decision (auth mode, API keys, firewall),
>   STOP and ask me. Never guess on security settings.
> - Never expose the Postgres or Redis ports to the internet — the app
>   container is the only thing that needs to be reachable.
> - Use SSH keys, not passwords, for server access.

## What the agent will ask you

- **Your city name** and open-data portal URL (if you have one).
- **Auth mode**: API key (recommended) — the wizard generates one for you.
- **311/transit feeds**: the wizard auto-discovers these when it can; if
  yours aren't found, your open-data team will know the URLs.

## Verify it worked

Open `http://YOUR-SERVER:8000/` in a browser. You should see the Civic
Connector landing page: what it does, its tools, and how to connect an
agent. `http://YOUR-SERVER:8000/health` should return `"status": "ok"`.

## After it's running

- **Updates**: `docker compose pull && docker compose up -d` — or enable
  zero-touch daily updates (see [RUNBOOK.md](RUNBOOK.md)).
- **Backups**: `./scripts/backup.sh` — put it on a weekly schedule.
- **Connecting agents**: the landing page at `/` has copy-paste instructions
  for Claude Desktop and other MCP clients.

Full operator details: [RUNBOOK.md](RUNBOOK.md). Adding another city:
[ADDING_A_CITY.md](ADDING_A_CITY.md).
