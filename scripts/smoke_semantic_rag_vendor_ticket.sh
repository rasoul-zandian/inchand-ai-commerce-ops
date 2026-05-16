#!/usr/bin/env bash
# Optional manual smoke: POST /run-vendor-ticket with RAG_STRATEGY=semantic (mock embeddings).
# Prerequisites: FastAPI server running; RAG_STRATEGY=semantic in the environment (e.g. after sourcing .env).
# No API keys are stored in this file.

set -euo pipefail

_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$_root"

# shellcheck source=scripts/_smoke_config_preflight.sh
source "${_root}/scripts/_smoke_config_preflight.sh"
_smoke_run_config_preflight

_rag="${RAG_STRATEGY:-}"
_rag_trimmed="${_rag#"${_rag%%[![:space:]]*}"}"
_rag_trimmed="${_rag_trimmed%"${_rag_trimmed##*[![:space:]]}"}"
_rag_lower=$(printf '%s' "$_rag_trimmed" | tr '[:upper:]' '[:lower:]')

if [[ "$_rag_lower" != "semantic" ]]; then
  echo "ERROR: RAG_STRATEGY must be 'semantic' for this smoke test (got: '${RAG_STRATEGY:-empty}')." >&2
  echo "Export it or run: set -a && source .env && set +a" >&2
  exit 1
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

curl -s -X POST "${BASE_URL}/run-vendor-ticket" \
  -H "Content-Type: application/json" \
  -d '{"user_input":"سلام، تسویه من با فاکتور فروش هم‌خوان نیست و نیاز به بررسی مالی دارم.","ticket_id":"t-semantic-rag-smoke-001"}' \
  | python3.11 -m json.tool
