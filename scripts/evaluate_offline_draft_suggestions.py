#!/usr/bin/env python3
"""Evaluate offline draft suggestions against historical gold human replies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evals.offline_draft_evaluation import run_offline_draft_evaluation

_DEFAULT_DRAFTS = Path("reports/offline_draft_suggestions_v1.jsonl")
_DEFAULT_BENCHMARK = Path("reports/historical_reply_benchmark_v1.jsonl")
_DEFAULT_JSON = Path("reports/offline_draft_evaluation_v1.json")
_DEFAULT_MD = Path("reports/offline_draft_evaluation_v1.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Offline draft vs gold evaluation (Step 172): deterministic lexical overlap "
            "and safety counts. Reads gitignored reports/ only; no API calls."
        ),
    )
    parser.add_argument(
        "--draft-suggestions",
        "--drafts",
        dest="draft_suggestions",
        type=Path,
        default=_DEFAULT_DRAFTS,
        help="Draft suggestions JSONL (default: reports/offline_draft_suggestions_v1.jsonl)",
    )
    parser.add_argument(
        "--benchmark",
        type=Path,
        default=_DEFAULT_BENCHMARK,
        help="Historical benchmark JSONL with gold replies (local eval only)",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=_DEFAULT_JSON,
        help="Evaluation summary JSON (default: reports/offline_draft_evaluation_v1.json)",
    )
    parser.add_argument(
        "--output-markdown",
        "--markdown-output",
        dest="output_markdown",
        type=Path,
        default=_DEFAULT_MD,
        help="Evaluation markdown report (default: reports/offline_draft_evaluation_v1.md)",
    )
    parser.add_argument(
        "--low-overlap-threshold",
        type=float,
        default=None,
        help="Jaccard overlap below this counts as low_overlap (default: 0.15)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Allow overwriting existing output files",
    )
    args = parser.parse_args(argv)

    for path in (args.output_json, args.output_markdown):
        if path.exists() and not args.overwrite:
            print(f"error: output exists (use --overwrite): {path}", file=sys.stderr)
            return 2

    if not args.draft_suggestions.is_file():
        print(f"error: draft suggestions not found: {args.draft_suggestions}", file=sys.stderr)
        return 2
    if not args.benchmark.is_file():
        print(f"error: benchmark not found: {args.benchmark}", file=sys.stderr)
        return 2

    kwargs: dict[str, object] = {}
    if args.low_overlap_threshold is not None:
        kwargs["low_overlap_threshold"] = args.low_overlap_threshold

    summary = run_offline_draft_evaluation(
        args.draft_suggestions,
        args.benchmark,
        output_json_path=args.output_json,
        output_markdown_path=args.output_markdown,
        **kwargs,
    )
    print(json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
