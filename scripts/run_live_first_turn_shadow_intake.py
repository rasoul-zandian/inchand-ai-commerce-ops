#!/usr/bin/env python3
"""Run live first-turn shadow intake (read-only agentic graph; no send/execute)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.live_shadow.live_first_turn_shadow_intake import (
    DEFAULT_LIVE_SHADOW_RUNS_JSONL,
    DEFAULT_LIVE_SHADOW_SUMMARY_JSON,
    run_live_first_turn_shadow_intake,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Observe live seller tickets, run agentic sandbox in shadow, "
            "and persist safe evaluation artifacts only."
        ),
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Live feed JSONL (default: LIVE_FEED_SOURCE_PATH)",
    )
    parser.add_argument(
        "--runs-jsonl",
        type=Path,
        default=DEFAULT_LIVE_SHADOW_RUNS_JSONL,
        help="Append-only shadow run rows",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_LIVE_SHADOW_SUMMARY_JSON,
        help="Aggregate summary JSON for this intake run",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "openai"),
        default="mock",
        help="LLM provider for generate_draft node",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model override",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=25,
        help="Max eligible tickets to process per run",
    )
    parser.add_argument(
        "--since-hours",
        type=float,
        default=None,
        help="Only consider tickets updated within the last N hours",
    )
    parser.add_argument(
        "--enable-knowledge-hints",
        action="store_true",
        help="Enable knowledge hints in shadow graph runs",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Skip tickets already present in runs JSONL (room_id + signature)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Filter and summarize only; do not run graph or write runs JSONL",
    )
    parser.add_argument(
        "--poll-once",
        action="store_true",
        help="Single intake pass (default behavior; reserved for future polling loops)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite summary JSON; replace runs JSONL instead of appending",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required when --provider openai",
    )
    args = parser.parse_args(argv)

    if args.provider == "openai" and not args.confirm_real_openai:
        print("error: --provider openai requires --confirm-real-openai", file=sys.stderr)
        return 2

    _ = args.poll_once  # reserved

    settings = get_settings()
    source = args.source or Path(settings.live_feed_source_path)
    if not source.is_file():
        print(f"live_shadow_intake: source not found: {source}", file=sys.stderr)
        return 2

    try:
        summary = run_live_first_turn_shadow_intake(
            source_path=source,
            runs_jsonl=args.runs_jsonl,
            summary_json=args.summary_json,
            settings=settings,
            provider=args.provider,
            model=args.model,
            generate_fn=None,
            limit=args.limit,
            since_hours=args.since_hours,
            enable_knowledge_hints=args.enable_knowledge_hints,
            dedupe=args.dedupe,
            dry_run=args.dry_run,
            overwrite=args.overwrite,
        )
    except FileExistsError as exc:
        print(f"live_shadow_intake: {exc}", file=sys.stderr)
        return 2

    print("live_shadow_intake: success")
    print(f"  dry_run={summary.dry_run}")
    print(f"  total_live_seen={summary.total_live_seen}")
    print(f"  eligible_first_turn={summary.eligible_first_turn}")
    print(f"  processed_count={summary.processed_count}")
    print(f"  graph_success_rate={summary.graph_success_rate}")
    print(f"  safety_pass_rate={summary.safety_pass_rate}")
    print(f"  execution_allowed_true_count={summary.execution_allowed_true_count}")
    print(f"  customer_send_allowed_true_count={summary.customer_send_allowed_true_count}")
    print(f"  runs_jsonl={args.runs_jsonl.resolve()}")
    print(f"  summary_json={args.summary_json.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
