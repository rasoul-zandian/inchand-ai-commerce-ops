#!/usr/bin/env python3
"""Build agentic sandbox graduation readiness report (governance only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.graduation_criteria import (
    DEFAULT_CONSISTENCY_SUMMARY_PATH,
    DEFAULT_DRAFT_METRICS_SUMMARY_PATH,
    DEFAULT_GRADUATION_REPORT_PATH,
    DEFAULT_GRADUATION_SUMMARY_PATH,
    build_agentic_sandbox_graduation_report,
)
from app.agentic_sandbox.report_paths import (
    DEFAULT_COVERAGE_SUMMARY_PATH,
    DEFAULT_PREVIEW_REVIEW_METRICS_SUMMARY_PATH,
    DEFAULT_READINESS_SUMMARY_PATH,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate agentic sandbox graduation criteria from existing aggregate "
            "reports (no workflow or graph behavior changes)."
        ),
    )
    parser.add_argument(
        "--readiness-summary",
        type=Path,
        default=DEFAULT_READINESS_SUMMARY_PATH,
        help="Readiness summary JSON",
    )
    parser.add_argument(
        "--knowledge-summary",
        type=Path,
        default=DEFAULT_COVERAGE_SUMMARY_PATH,
        help="Knowledge hint coverage summary JSON",
    )
    parser.add_argument(
        "--preview-metrics",
        type=Path,
        default=DEFAULT_PREVIEW_REVIEW_METRICS_SUMMARY_PATH,
        help="Agentic preview review metrics summary JSON",
    )
    parser.add_argument(
        "--consistency-summary",
        type=Path,
        default=DEFAULT_CONSISTENCY_SUMMARY_PATH,
        help="Console vs graph consistency batch summary JSON",
    )
    parser.add_argument(
        "--draft-metrics",
        type=Path,
        default=DEFAULT_DRAFT_METRICS_SUMMARY_PATH,
        help="Offline draft review metrics summary JSON (advisory)",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_GRADUATION_SUMMARY_PATH,
        help="Graduation JSON summary output",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_GRADUATION_REPORT_PATH,
        help="Graduation markdown report output",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    for path in (args.summary_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(f"refusing to overwrite existing file: {path}", file=sys.stderr)
            return 1

    summary = build_agentic_sandbox_graduation_report(
        readiness_path=args.readiness_summary,
        knowledge_path=args.knowledge_summary,
        preview_metrics_path=args.preview_metrics,
        consistency_path=args.consistency_summary,
        draft_metrics_path=args.draft_metrics,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )
    print("agentic_sandbox_graduation: success")
    print(f"  overall_status={summary.overall_status}")
    print(f"  blocking_issues={len(summary.blocking_issues)}")
    print(f"  advisory_issues={len(summary.advisory_issues)}")
    print(f"  json={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
