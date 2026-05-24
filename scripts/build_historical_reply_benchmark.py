#!/usr/bin/env python3
"""Build historical reply benchmark JSONL from redacted vendor ticket exports (offline)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evals.historical_reply_benchmark import (
    BenchmarkCaseMode,
    build_benchmark_from_jsonl,
)

_DEFAULT_INPUT = Path("data/private/vendor_tickets_400.redacted.jsonl")
_DEFAULT_JSONL = Path("reports/historical_reply_benchmark_v1.jsonl")
_DEFAULT_SUMMARY = Path("reports/historical_reply_benchmark_summary.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build offline benchmark cases from redacted vendor ticket JSONL. "
            "Modes: all_adjacent_pairs (default) or first_vendor_turn (one case per room)."
        ),
    )
    parser.add_argument(
        "input_path",
        type=Path,
        nargs="?",
        default=_DEFAULT_INPUT,
        help=(
            "Redacted vendor ticket JSONL (default: data/private/vendor_tickets_400.redacted.jsonl)"
        ),
    )
    parser.add_argument(
        "--output-jsonl",
        "--output",
        dest="output_jsonl",
        type=Path,
        default=_DEFAULT_JSONL,
        help="Output benchmark JSONL path (default: reports/historical_reply_benchmark_v1.jsonl)",
    )
    parser.add_argument(
        "--output-summary",
        "--summary-output",
        dest="output_summary",
        type=Path,
        default=_DEFAULT_SUMMARY,
        help="Output summary JSON path (default: reports/historical_reply_benchmark_summary.json)",
    )
    parser.add_argument(
        "--case-mode",
        choices=[mode.value for mode in BenchmarkCaseMode],
        default=BenchmarkCaseMode.ALL_ADJACENT_PAIRS.value,
        help="Benchmark expansion mode (default: all_adjacent_pairs)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing output files",
    )
    args = parser.parse_args(argv)

    if not args.input_path.is_file():
        print(f"error: input file not found: {args.input_path}", file=sys.stderr)
        return 2

    for path in (args.output_jsonl, args.output_summary):
        if path.exists() and not args.overwrite:
            print(
                f"error: output exists (use --overwrite): {path}",
                file=sys.stderr,
            )
            return 2

    stats = build_benchmark_from_jsonl(
        args.input_path,
        output_jsonl_path=args.output_jsonl,
        output_summary_path=args.output_summary,
        case_mode=args.case_mode,
    )
    print(json.dumps(stats.to_json_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
