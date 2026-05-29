#!/usr/bin/env python3
"""Freeze OpenAI multi-turn behavioral baseline (manual/nightly; not CI)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.evals.multi_turn_eval_runner import DEFAULT_SCENARIOS_PATH, load_eval_scenarios
from app.evals.openai_multi_turn_baseline import (
    DEFAULT_FREEZE_REPORT_MD,
    DEFAULT_FREEZE_SUMMARY_JSON,
    DEFAULT_OPENAI_BASELINE_DIR,
    freeze_openai_baseline,
    write_baseline_reports,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run OpenAI multi-turn eval suite and freeze behavioral fingerprints "
            "(requires --update-baseline; not for CI)."
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
        "--update-baseline",
        action="store_true",
        help="Required: allow writing/updating frozen baseline files",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required: confirm real OpenAI API usage",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite freeze report outputs",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_FREEZE_SUMMARY_JSON,
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=DEFAULT_FREEZE_REPORT_MD,
    )
    args = parser.parse_args(argv)

    if not args.confirm_real_openai:
        print("error: --confirm-real-openai is required", file=sys.stderr)
        return 2
    if not args.update_baseline:
        print("error: --update-baseline is required to write baseline files", file=sys.stderr)
        return 2
    if not args.scenarios_path.is_file():
        print(f"error: scenarios file not found: {args.scenarios_path}", file=sys.stderr)
        return 2

    hints = args.enable_knowledge_hints and not args.no_knowledge_hints
    scenarios = load_eval_scenarios(args.scenarios_path)
    try:
        summary = freeze_openai_baseline(
            scenarios=scenarios,
            settings=get_settings(),
            enable_knowledge_hints=hints,
            baseline_dir=args.baseline_dir,
            update_baseline=True,
            scenarios_path=args.scenarios_path,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    write_baseline_reports(
        freeze_summary=summary,
        freeze_summary_json=args.summary_json,
        freeze_report_md=args.report_md,
        overwrite=args.overwrite,
    )

    print("openai_baseline_freeze: complete")
    print(f"  status={summary.status}")
    print(f"  eval_pass_rate={summary.eval_summary.pass_rate:.1%}")
    print(f"  triage_real_failures={summary.triage_real_failures}")
    print(f"  scenarios_written={summary.scenario_files_written}")
    print(f"  baseline_dir={args.baseline_dir}")
    print(f"  summary_json={args.summary_json}")
    print(f"  report_md={args.report_md}")
    return 0 if summary.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
