#!/usr/bin/env python3
"""Build slice-based draft quality analysis from operator review feedback (advisory only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.evals.draft_quality_slice_analysis import (
    DEFAULT_SLICE_REPORT_PATH,
    DEFAULT_SLICE_SUMMARY_PATH,
    build_draft_quality_slice_analysis_report,
)
from app.operator_console.draft_review_feedback import DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Slice-based draft quality analysis from draft review feedback "
            "(no prompt/mapping changes)."
        ),
    )
    parser.add_argument(
        "--feedback-path",
        type=Path,
        default=DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
        help="Draft review JSONL input (default: reports/draft_review_feedback.jsonl)",
    )
    parser.add_argument(
        "--enrichment-path",
        type=Path,
        default=None,
        help=(
            "Optional offline draft suggestions JSONL for route/entity/actionability "
            "slices (default: operator_draft_suggestions_path from settings)"
        ),
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_SLICE_SUMMARY_PATH,
        help="JSON summary (default: reports/draft_quality_slice_analysis_summary.json)",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_SLICE_REPORT_PATH,
        help="Markdown report (default: reports/draft_quality_slice_analysis_report.md)",
    )
    parser.add_argument(
        "--min-slice-reviews",
        type=int,
        default=3,
        help="Minimum reviews required per slice for weak/strong ranking (default: 3)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.feedback_path.is_file():
        print(
            f"draft_quality_slice_analysis: feedback not found: {args.feedback_path} "
            "(writing empty summary)",
            file=sys.stderr,
        )

    enrichment_path = args.enrichment_path
    if enrichment_path is None:
        enrichment_path = Path(get_settings().operator_draft_suggestions_path)

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"draft_quality_slice_analysis: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_draft_quality_slice_analysis_report(
        args.feedback_path,
        enrichment_path=enrichment_path,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
        min_slice_reviews=args.min_slice_reviews,
    )

    print("draft_quality_slice_analysis: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  total_reviews={summary.total_reviews}")
    print(f"  overall_usable_rate={summary.overall_usable_rate:.1%}")
    print(f"  weak_slices={len(summary.weakest_slices)}")
    if summary.weakest_slices:
        weakest = summary.weakest_slices[0]
        print(
            f"  weakest={weakest.slice_type}/{weakest.slice_key} usable={weakest.usable_rate:.1%}",
        )
    if summary.recommended_calibration_targets:
        print(f"  top_target={summary.recommended_calibration_targets[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
