#!/usr/bin/env bash
# Optional manual smoke: POST /run-vendor-ticket against local FastAPI.
# Prerequisites: server running; OPENAI_API_KEY set in the environment (e.g. after sourcing .env).
# No API keys are stored in this file.

set -euo pipefail

_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$_root"

# shellcheck source=scripts/_smoke_config_preflight.sh
source "${_root}/scripts/_smoke_config_preflight.sh"
_smoke_run_config_preflight

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: OPENAI_API_KEY is not set. Export it or run: set -a && source .env && set +a" >&2
  exit 1
fi

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

curl -sS -X POST "${BASE_URL}/run-vendor-ticket" \
  -H "Content-Type: application/json" \
  -d '{"user_input":"سلام، وضعیت تسویه من با فاکتور هم‌خوان نیست. لطفاً بررسی کنید.","ticket_id":"t-openai-smoke-001"}' \
  | python3.11 -m json.tool
