#!/usr/bin/env bash
# One-command setup for the Civic Connector.
# Usage: ./setup.sh
set -euo pipefail

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required but not installed."
  echo "Get it here: https://docs.docker.com/get-docker/"
  exit 1
fi

if [ ! -f .env ]; then
  if [ -t 0 ] && command -v python3 >/dev/null 2>&1; then
    python3 init_wizard.py
  else
    cp .env.example .env
    echo "Created .env from .env.example (non-interactive)."
  fi
fi

# Prefer the published image; fall back to a local build.
docker compose pull 2>/dev/null || echo "Published image not found; building locally..."
docker compose up -d

echo ""
echo "Civic Connector is up."
echo "  MCP endpoint: http://localhost:8000/mcp"
echo "  Health check: http://localhost:8000/health"
echo ""
echo "Point any MCP client (e.g. mcp-remote) at the MCP endpoint."
