#!/usr/bin/env python3
"""Build aggregate metrics from agentic sandbox preview operator reviews (analytics only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
)
from app.agentic_sandbox.preview_review_metrics import build_agentic_preview_review_metrics_report
from app.agentic_sandbox.report_paths import (
    DEFAULT_BATCH_RUNS_JSONL,
    DEFAULT_PREVIEW_REVIEW_METRICS_REPORT_PATH,
    DEFAULT_PREVIEW_REVIEW_METRICS_SUMMARY_PATH,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate operator agentic sandbox preview review feedback into "
            "JSON + markdown metrics (no graph or behavior changes)."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
        help=(
            "Preview review feedback JSONL (default: reports/agentic_preview_review_feedback.jsonl)"
        ),
    )
    parser.add_argument(
        "--batch-runs",
        type=Path,
        default=DEFAULT_BATCH_RUNS_JSONL,
        help="Optional batch runs JSONL for intent/action breakdown join",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_PREVIEW_REVIEW_METRICS_SUMMARY_PATH,
        help="JSON summary (default: reports/agentic_preview_review_metrics_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_PREVIEW_REVIEW_METRICS_REPORT_PATH,
        help="Markdown report (default: reports/agentic_preview_review_metrics_report.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.input.is_file():
        print(
            f"preview_review_metrics: input not found: {args.input} (writing empty summary)",
            file=sys.stderr,
        )

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"preview_review_metrics: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_agentic_preview_review_metrics_report(
        args.input,
        batch_runs_path=args.batch_runs,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("preview_review_metrics: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_reviews={summary.total_reviews}")
    print(f"  preview_usefulness_rate={summary.preview_usefulness_rate:.1%}")
    if summary.weakest_graph_dimensions:
        print(f"  weakest_dimension={summary.weakest_graph_dimensions[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
