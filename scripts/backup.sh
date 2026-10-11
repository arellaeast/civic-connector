#!/usr/bin/env bash
# One-command Postgres backup for the Civic Connector.
# Usage: ./scripts/backup.sh
# Restore: cat backups/<file>.sql | docker compose exec -T db psql -U connector civic_connector
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups

STAMP=$(date +%Y%m%d-%H%M%S)
OUT="backups/civic_connector-${STAMP}.sql"

docker compose exec -T db pg_dump -U connector civic_connector > "$OUT"
echo "Backup written to $OUT"
echo "Keep a copy somewhere off this machine."
