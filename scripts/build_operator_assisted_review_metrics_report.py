#!/usr/bin/env python3
"""Build aggregate metrics for operator-assisted agentic mode reviews (analytics only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
)
from app.agentic_sandbox.report_paths import DEFAULT_BATCH_RUNS_JSONL
from app.operator_console.agentic_assisted_review_metrics import (
    DEFAULT_OPERATOR_ASSISTED_REVIEW_FEEDBACK_PATH,
    DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_REPORT_PATH,
    DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
    build_operator_assisted_review_metrics_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate operator-assisted mode review feedback into JSON + markdown "
            "metrics (analytics only; no graph or send changes)."
        ),
    )
    parser.add_argument(
        "--preview-input",
        type=Path,
        default=DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
        help="Sandbox preview review JSONL (reports/agentic_preview_review_feedback.jsonl)",
    )
    parser.add_argument(
        "--assisted-input",
        type=Path,
        default=DEFAULT_OPERATOR_ASSISTED_REVIEW_FEEDBACK_PATH,
        help=(
            "Optional assisted-mode extension JSONL "
            "(default: reports/operator_assisted_review_feedback.jsonl)"
        ),
    )
    parser.add_argument(
        "--no-assisted-input",
        action="store_true",
        help="Ignore assisted extension JSONL even if present",
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
        default=DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
        help="JSON summary (default: reports/operator_assisted_review_metrics_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_REPORT_PATH,
        help="Markdown report (default: reports/operator_assisted_review_metrics_report.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.preview_input.is_file():
        print(
            f"operator_assisted_review_metrics: preview input not found: {args.preview_input} "
            "(writing empty summary)",
            file=sys.stderr,
        )

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"operator_assisted_review_metrics: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    assisted_path = None if args.no_assisted_input else args.assisted_input
    summary = build_operator_assisted_review_metrics_report(
        args.preview_input,
        assisted_extension_path=assisted_path,
        batch_runs_path=args.batch_runs,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("operator_assisted_review_metrics: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_reviews={summary.total_reviews}")
    print(f"  assisted_mode_usefulness_rate={summary.assisted_mode_usefulness_rate:.1%}")
    print(f"  overall_assisted_quality_rate={summary.overall_assisted_quality_rate:.1%}")
    if summary.weakest_dimensions:
        print(f"  weakest_dimension={summary.weakest_dimensions[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
