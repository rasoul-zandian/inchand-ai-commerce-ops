#!/usr/bin/env python3
"""Build deep action mismatch analysis from draft review feedback (advisory only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.evals.action_mismatch_analysis import (
    DEFAULT_ANALYSIS_REPORT_PATH,
    DEFAULT_ANALYSIS_SUMMARY_PATH,
    build_action_mismatch_analysis_report,
)
from app.operator_console.draft_review_feedback import DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Deep-dive action mismatch analysis from draft review feedback (no taxonomy changes)."
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
        default=DEFAULT_ANALYSIS_SUMMARY_PATH,
        help="JSON summary (default: reports/action_mismatch_analysis_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_ANALYSIS_REPORT_PATH,
        help="Markdown report (default: reports/action_mismatch_analysis_report.md)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.feedback_path.is_file():
        print(
            f"action_mismatch_analysis: feedback not found: {args.feedback_path} "
            "(writing empty summary)",
            file=sys.stderr,
        )

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"action_mismatch_analysis: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_action_mismatch_analysis_report(
        args.feedback_path,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("action_mismatch_analysis: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_reviews={summary.total_reviews}")
    print(f"  total_action_mismatches={summary.total_action_mismatches}")
    print(f"  action_accuracy_rate={summary.action_accuracy_rate:.1%}")
    if summary.confusion_pairs:
        top = summary.confusion_pairs[0]
        print(
            f"  top_confusion={top.predicted_action} -> "
            f"{top.reviewer_expected_action or '?'} ({top.count})",
        )
    focus = summary.recommended_next_calibration_focus
    if len(focus) > 120:
        focus = focus[:120] + "…"
    print(f"  focus={focus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
