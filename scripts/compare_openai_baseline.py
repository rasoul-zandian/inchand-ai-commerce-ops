#!/usr/bin/env python3
"""Compare current OpenAI multi-turn run against frozen baseline (manual/nightly)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.evals.multi_turn_eval_runner import DEFAULT_SCENARIOS_PATH, load_eval_scenarios
from app.evals.openai_multi_turn_baseline import (
    DEFAULT_COMPARE_REPORT_MD,
    DEFAULT_COMPARE_SUMMARY_JSON,
    DEFAULT_OPENAI_BASELINE_DIR,
    compare_openai_baseline,
    load_baseline_manifest,
    write_baseline_reports,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run OpenAI multi-turn eval and compare against frozen baseline "
            "(comparison only; never updates baseline without --update-baseline)."
        ),
    )
    parser.add_argument(
        "--scenarios-path",
        type=Path,
        default=DEFAULT_SCENARIOS_PATH,
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_OPENAI_BASELINE_DIR,
    )
    parser.add_argument(
        "--provider",
        choices=("openai",),
        default="openai",
        help="Provider for current run (must be openai)",
    )
    parser.add_argument(
        "--enable-knowledge-hints",
        action="store_true",
        default=True,
        help="Enable knowledge hints (default: on)",
    )
    parser.add_argument(
        "--no-knowledge-hints",
        action="store_true",
        help="Disable knowledge hints",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required: confirm real OpenAI API usage",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite comparison report outputs",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_COMPARE_SUMMARY_JSON,
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=DEFAULT_COMPARE_REPORT_MD,
    )
    args = parser.parse_args(argv)

    if not args.confirm_real_openai:
        print("error: --confirm-real-openai is required", file=sys.stderr)
        return 2
    if not args.scenarios_path.is_file():
        print(f"error: scenarios file not found: {args.scenarios_path}", file=sys.stderr)
        return 2
    if not (args.baseline_dir / "manifest.json").is_file():
        print(f"error: frozen baseline manifest not found: {args.baseline_dir}", file=sys.stderr)
        print(
            "hint: run scripts/freeze_openai_multi_turn_baseline.py --update-baseline first",
            file=sys.stderr,
        )
        return 2

    hints = args.enable_knowledge_hints and not args.no_knowledge_hints
    scenarios = load_eval_scenarios(args.scenarios_path)
    manifest = load_baseline_manifest(args.baseline_dir)
    if manifest is None:
        print("error: could not load baseline manifest", file=sys.stderr)
        return 2

    summary = compare_openai_baseline(
        scenarios=scenarios,
        settings=get_settings(),
        enable_knowledge_hints=hints,
        baseline_dir=args.baseline_dir,
        scenarios_path=args.scenarios_path,
        provider=args.provider,
    )

    write_baseline_reports(
        compare_summary=summary,
        compare_summary_json=args.summary_json,
        compare_report_md=args.report_md,
        overwrite=args.overwrite,
    )

    print("openai_baseline_compare: complete")
    print(f"  status={summary.status}")
    print(f"  unchanged={summary.unchanged_count}")
    print(f"  acceptable={summary.acceptable_drift_count}")
    print(f"  review_required={summary.review_required_count}")
    print(f"  critical_regression={summary.critical_regression_count}")
    print(f"  baseline_frozen_at={manifest.frozen_at_utc}")
    print(f"  summary_json={args.summary_json}")
    print(f"  report_md={args.report_md}")
    return 0 if summary.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
