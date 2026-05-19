#!/usr/bin/env python3
"""Build offline shadow retrieval metrics dashboard from sanitized replay JSONL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.shadow_retrieval_metrics_dashboard import (
    build_shadow_retrieval_dashboard,
)

_DEFAULT_MD = Path("reports/shadow_retrieval_metrics_dashboard.md")
_DEFAULT_JSON = Path("reports/shadow_retrieval_metrics_dashboard.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate shadow retrieval metrics from sanitized replay JSONL "
            "(local/gitignored; no raw content)."
        ),
    )
    parser.add_argument(
        "input_path",
        type=Path,
        help="Replay or shadow replay JSONL with sanitized retrieval_* fields",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=_DEFAULT_MD,
        help="Markdown dashboard output path",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=_DEFAULT_JSON,
        help="JSON metrics summary output path",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Skip writing JSON summary",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files",
    )
    args = parser.parse_args(argv)

    if not args.input_path.is_file():
        print(
            f"shadow_retrieval_metrics_dashboard: file not found: {args.input_path}",
            file=sys.stderr,
        )
        return 1

    for path in (args.output, None if args.no_json else args.json_output):
        if path is not None and path.exists() and not args.overwrite:
            print(
                f"shadow_retrieval_metrics_dashboard: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 1

    try:
        metrics = build_shadow_retrieval_dashboard(
            args.input_path,
            markdown_output=args.output,
            json_output=None if args.no_json else args.json_output,
        )
    except ValueError as exc:
        print(f"shadow_retrieval_metrics_dashboard: {exc}", file=sys.stderr)
        return 1

    print("shadow_retrieval_metrics_dashboard: success")
    print(f"  markdown={args.output.resolve()}")
    if not args.no_json and args.json_output is not None:
        print(f"  json={args.json_output.resolve()}")
    print(f"  total_rows={metrics.total_rows}")
    print(f"  shadow_node_executed_count={metrics.shadow_node_executed_count}")
    print(f"  retrieval_activated_true_count={metrics.retrieval_activated_true_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
