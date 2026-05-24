#!/usr/bin/env python3
"""Build node-level readiness report from agentic sandbox batch runs (analytics only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.agentic_batch_report import DEFAULT_BATCH_RUNS_JSONL
from app.agentic_sandbox.agentic_readiness_analysis import (
    DEFAULT_READINESS_REPORT_PATH,
    DEFAULT_READINESS_SUMMARY_PATH,
    build_agentic_readiness_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Node-level agentic sandbox readiness analysis from batch JSONL "
            "(no graph/draft behavior changes)."
        ),
    )
    parser.add_argument(
        "--batch-runs",
        type=Path,
        default=DEFAULT_BATCH_RUNS_JSONL,
        help="Batch runs JSONL input (default: reports/agentic_sandbox_batch_runs.jsonl)",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_READINESS_SUMMARY_PATH,
        help="JSON summary (default: reports/agentic_sandbox_readiness_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_READINESS_REPORT_PATH,
        help="Markdown report (default: reports/agentic_sandbox_readiness_report.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.batch_runs.is_file():
        print(
            f"agentic_readiness: batch runs not found: {args.batch_runs} (writing empty summary)",
            file=sys.stderr,
        )

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"agentic_readiness: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_agentic_readiness_report(
        args.batch_runs,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("agentic_readiness: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_runs={summary.total_runs}")
    print(f"  human_review_ready_rate={summary.human_review_ready_rate:.1%}")
    print(f"  safety_passed_rate={summary.safety_passed_rate:.1%}")
    ready = summary.readiness_buckets.get("ready_for_human_review", 0)
    print(f"  ready_for_human_review={ready}")
    if summary.inspection_targets:
        first = summary.inspection_targets[0]
        print(f"  top_inspection={first.room_id} ({first.bucket})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
