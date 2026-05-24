#!/usr/bin/env python3
"""Build offline draft review metrics summary + markdown report from local JSONL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.evals.draft_review_metrics import (
    DEFAULT_METRICS_REPORT_PATH,
    DEFAULT_METRICS_SUMMARY_PATH,
    build_draft_review_metrics_report,
)
from app.operator_console.draft_review_feedback import DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate draft review feedback into local calibration metrics "
            "(no auto-learning or prompt changes)."
        ),
    )
    parser.add_argument(
        "--feedback-path",
        type=Path,
        default=DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
        help="Draft review JSONL input (default: reports/draft_review_feedback.jsonl)",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_METRICS_SUMMARY_PATH,
        help="JSON summary output (default: reports/draft_review_metrics_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_METRICS_REPORT_PATH,
        help="Markdown report output (default: reports/draft_review_metrics_report.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.feedback_path.is_file():
        print(
            f"draft_review_metrics: feedback file not found: {args.feedback_path} "
            "(writing empty summary)",
            file=sys.stderr,
        )

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"draft_review_metrics: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_draft_review_metrics_report(
        args.feedback_path,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("draft_review_metrics: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_reviews={summary.total_reviews}")
    print(f"  usable_rate={summary.usable_rate:.1%}")
    if summary.most_common_failure_patterns:
        top = summary.most_common_failure_patterns[0]
        print(f"  top_failure_pattern={top[0]} ({top[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
