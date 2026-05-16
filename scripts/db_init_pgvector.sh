#!/usr/bin/env bash
# Apply local pgvector schema migration (development only; no secrets printed).

set -euo pipefail

_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$_root"

_migration="${_root}/db/migrations/0001_create_rag_vector_records.sql"
if [[ ! -f "$_migration" ]]; then
  echo "pgvector init failed: migration not found at db/migrations/0001_create_rag_vector_records.sql" >&2
  exit 1
fi

# DATABASE_URL may contain credentials; never echo it.
_database_url="${DATABASE_URL:-postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai}"

echo "waiting for postgres readiness..."
_ready=0
for _ in $(seq 1 30); do
  if psql "$_database_url" -c "SELECT 1" >/dev/null 2>&1; then
    _ready=1
    break
  fi
  sleep 1
done

if [[ "$_ready" -ne 1 ]]; then
  echo "pgvector init failed: postgres not ready (is 'make pg-up' running?)" >&2
  exit 1
fi

echo "applying migration 0001_create_rag_vector_records.sql..."
if psql "$_database_url" -v ON_ERROR_STOP=1 -f "$_migration"; then
  echo "pgvector schema init: success"
  echo "verify with: psql \"\$DATABASE_URL\" -c \"SELECT COUNT(*) FROM rag_vector_records;\""
else
  echo "pgvector schema init: failed" >&2
  exit 1
fi
