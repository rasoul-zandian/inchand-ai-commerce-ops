#!/usr/bin/env python3
"""Build suggested_action calibration report from draft review feedback (offline only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.evals.suggested_action_calibration import (
    DEFAULT_CALIBRATION_REPORT_PATH,
    DEFAULT_CALIBRATION_SUMMARY_PATH,
    build_suggested_action_calibration_report,
)
from app.operator_console.draft_review_feedback import DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze suggested_action quality from draft review feedback "
            "(calibration recommendations only; no auto-mapping)."
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
        default=DEFAULT_CALIBRATION_SUMMARY_PATH,
        help="JSON summary (default: reports/suggested_action_calibration_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_CALIBRATION_REPORT_PATH,
        help="Markdown report (default: reports/suggested_action_calibration_report.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.feedback_path.is_file():
        print(
            f"suggested_action_calibration: feedback not found: {args.feedback_path} "
            "(writing empty summary)",
            file=sys.stderr,
        )

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"suggested_action_calibration: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_suggested_action_calibration_report(
        args.feedback_path,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("suggested_action_calibration: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_reviewed_actions={summary.total_reviewed_actions}")
    print(f"  action_accuracy_rate={summary.action_accuracy_rate:.1%}")
    print(f"  monitor_usage_rate={summary.monitor_usage_rate:.1%}")
    print(f"  fallback_overuse_count={summary.fallback_overuse_count}")
    if summary.suggested_mapping_adjustments:
        top = summary.suggested_mapping_adjustments[0]
        print(
            f"  top_adjustment={top.detected_intent}: "
            f"{top.current_common_action} -> {top.suggested_preferred_action}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
