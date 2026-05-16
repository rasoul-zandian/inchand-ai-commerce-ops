#!/usr/bin/env bash
# Shared offline config preflight for manual smoke scripts (no secrets, no .env sourcing).

_smoke_run_config_preflight() {
  echo "running config preflight..."
  if ! PYTHONPATH=. python3.11 scripts/check_config.py; then
    echo "ERROR: config preflight failed; fix .env and rerun: make config-check" >&2
    return 1
  fi
  echo "config preflight passed"
}
