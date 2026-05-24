#!/usr/bin/env python3
"""Build entity extraction miss investigation report (analytics only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
)
from app.agentic_sandbox.report_paths import DEFAULT_BATCH_RUNS_JSONL
from app.operator_console.console_loader import DEFAULT_REDACTED_TICKETS_PATH, DEFAULT_REPLAY_PATH
from app.workflows.entity_extraction_investigation import (
    DEFAULT_INVESTIGATION_REPORT_PATH,
    DEFAULT_INVESTIGATION_SUMMARY_PATH,
    build_entity_extraction_investigation_report,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Investigate agentic preview entity-extraction misses from operator "
            "feedback (no extractor or graph changes)."
        ),
    )
    parser.add_argument(
        "--feedback-jsonl",
        type=Path,
        default=DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
        help="Preview review feedback JSONL",
    )
    parser.add_argument(
        "--batch-runs",
        type=Path,
        default=DEFAULT_BATCH_RUNS_JSONL,
        help="Agentic sandbox batch runs JSONL",
    )
    parser.add_argument(
        "--replay-jsonl",
        type=Path,
        default=DEFAULT_REPLAY_PATH,
        help="AI assist shadow replay JSONL",
    )
    parser.add_argument(
        "--redacted-jsonl",
        type=Path,
        default=DEFAULT_REDACTED_TICKETS_PATH,
        help="Redacted ticket export JSONL for full first-turn reference",
    )
    parser.add_argument(
        "--room-id",
        type=str,
        default=None,
        help="Investigate one room (defaults to all entity-flagged reviews)",
    )
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=DEFAULT_INVESTIGATION_SUMMARY_PATH,
        help="JSON summary output path",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_INVESTIGATION_REPORT_PATH,
        help="Markdown report output path",
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
                f"entity_extraction_investigation: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 2

    summary = build_entity_extraction_investigation_report(
        feedback_path=args.feedback_jsonl,
        batch_runs_path=args.batch_runs,
        replay_path=args.replay_jsonl,
        redacted_path=args.redacted_jsonl,
        room_id=args.room_id,
        summary_output=args.summary_output,
        markdown_output=args.markdown_output,
    )

    print("entity_extraction_investigation: success")
    print(f"  summary={args.summary_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    print(f"  investigated_rooms={summary.investigated_room_count}")
    if summary.investigations:
        first = summary.investigations[0]
        print(f"  sample_room={first.room_id} cause={first.likely_root_cause}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
