#!/usr/bin/env python3
"""Build knowledge hint coverage diagnostics from agentic sandbox batch runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.agentic_batch_report import DEFAULT_BATCH_RUNS_JSONL
from app.agentic_sandbox.knowledge_hint_coverage_analysis import (
    DEFAULT_COVERAGE_REPORT_PATH,
    DEFAULT_COVERAGE_SUMMARY_PATH,
    build_knowledge_hint_coverage_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Knowledge hint coverage diagnostics for agentic sandbox batch runs "
            "(no retrieval behavior changes)."
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
        default=DEFAULT_COVERAGE_SUMMARY_PATH,
        help="JSON summary (default: reports/agentic_knowledge_hint_coverage_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_COVERAGE_REPORT_PATH,
        help="Markdown report (default: reports/agentic_knowledge_hint_coverage_report.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.batch_runs.is_file():
        print(
            f"knowledge_hint_coverage: batch runs not found: {args.batch_runs} "
            "(writing empty summary)",
            file=sys.stderr,
        )

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"knowledge_hint_coverage: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_knowledge_hint_coverage_report(
        args.batch_runs,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("knowledge_hint_coverage: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_runs={summary.total_runs}")
    print(f"  policy_relevant_runs={summary.policy_relevant_runs}")
    print(f"  coverage_rate={summary.coverage_rate:.1%}")
    print(f"  zero_hint_policy_runs={len(summary.zero_hint_policy_runs)}")
    if summary.recommended_inspection_targets:
        first = summary.recommended_inspection_targets[0]
        print(f"  top_inspection={first.room_id} ({first.reason_hint})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
