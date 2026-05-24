#!/usr/bin/env python3
"""Build operator-assisted mode pilot readiness report (governance only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.graduation_criteria import DEFAULT_GRADUATION_SUMMARY_PATH
from app.agentic_sandbox.report_paths import (
    DEFAULT_COVERAGE_SUMMARY_PATH,
    DEFAULT_READINESS_SUMMARY_PATH,
)
from app.operator_console.agentic_assisted_review_metrics import (
    DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
)
from app.operator_console.assisted_mode_pilot_readiness import (
    DEFAULT_ACTION_MISMATCH_SUMMARY_PATH,
    DEFAULT_CONSISTENCY_SUMMARY_PATH,
    DEFAULT_DRAFT_METRICS_SUMMARY_PATH,
    DEFAULT_DRAFT_QUALITY_SLICE_SUMMARY_PATH,
    DEFAULT_PILOT_READINESS_REPORT_PATH,
    DEFAULT_PILOT_READINESS_SUMMARY_PATH,
    build_assisted_mode_pilot_readiness_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate operator-assisted agentic mode pilot readiness from "
            "existing aggregate reports (no runtime behavior changes)."
        ),
    )
    parser.add_argument(
        "--graduation-summary",
        type=Path,
        default=DEFAULT_GRADUATION_SUMMARY_PATH,
        help="Agentic sandbox graduation summary JSON",
    )
    parser.add_argument(
        "--readiness-summary",
        type=Path,
        default=DEFAULT_READINESS_SUMMARY_PATH,
        help="Agentic sandbox readiness summary JSON",
    )
    parser.add_argument(
        "--knowledge-summary",
        type=Path,
        default=DEFAULT_COVERAGE_SUMMARY_PATH,
        help="Knowledge hint coverage summary JSON",
    )
    parser.add_argument(
        "--assisted-metrics",
        type=Path,
        default=DEFAULT_OPERATOR_ASSISTED_REVIEW_METRICS_SUMMARY_PATH,
        help="Operator-assisted review metrics summary JSON",
    )
    parser.add_argument(
        "--draft-metrics",
        type=Path,
        default=DEFAULT_DRAFT_METRICS_SUMMARY_PATH,
        help="Optional draft review metrics summary JSON",
    )
    parser.add_argument(
        "--consistency-summary",
        type=Path,
        default=DEFAULT_CONSISTENCY_SUMMARY_PATH,
        help="Optional console/graph consistency summary JSON",
    )
    parser.add_argument(
        "--draft-quality-slice",
        type=Path,
        default=DEFAULT_DRAFT_QUALITY_SLICE_SUMMARY_PATH,
        help="Optional draft quality slice analysis summary JSON",
    )
    parser.add_argument(
        "--action-mismatch",
        type=Path,
        default=DEFAULT_ACTION_MISMATCH_SUMMARY_PATH,
        help="Optional action mismatch analysis summary JSON",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_PILOT_READINESS_SUMMARY_PATH,
        help="JSON summary output",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_PILOT_READINESS_REPORT_PATH,
        help="Markdown report output",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"assisted_mode_pilot_readiness: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_assisted_mode_pilot_readiness_report(
        graduation_path=args.graduation_summary,
        readiness_path=args.readiness_summary,
        knowledge_path=args.knowledge_summary,
        assisted_metrics_path=args.assisted_metrics,
        draft_metrics_path=args.draft_metrics,
        consistency_path=args.consistency_summary,
        draft_quality_slice_path=args.draft_quality_slice,
        action_mismatch_path=args.action_mismatch,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("assisted_mode_pilot_readiness: success")
    print(f"  overall_status={summary.overall_status}")
    print(f"  blocking_issues={len(summary.blocking_issues)}")
    print(f"  advisory_issues={len(summary.advisory_issues)}")
    print(f"  json={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
