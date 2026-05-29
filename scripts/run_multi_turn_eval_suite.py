#!/usr/bin/env python3
"""Run multi-turn operational evaluation suite (synthetic scenarios; sandbox only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.config import get_settings
from app.evals.multi_turn_eval_runner import (
    DEFAULT_GOLDEN_DIR,
    DEFAULT_REPORT_MD,
    DEFAULT_RESULTS_JSONL,
    DEFAULT_SCENARIOS_PATH,
    DEFAULT_SUMMARY_JSON,
    load_eval_scenarios,
    run_multi_turn_eval_suite,
    write_multi_turn_eval_reports,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run curated multi-turn evaluation scenarios against the agentic sandbox graph "
            "(no send/mutate; synthetic data only)."
        ),
    )
    parser.add_argument(
        "--scenarios-path",
        type=Path,
        default=DEFAULT_SCENARIOS_PATH,
        help="Path to multi_turn_scenarios.json",
    )
    parser.add_argument(
        "--provider",
        choices=("mock", "openai"),
        default="mock",
        help="LLM provider for draft generation",
    )
    parser.add_argument(
        "--enable-knowledge-hints",
        action="store_true",
        help="Enable knowledge hints in sandbox graph runs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max scenarios to run",
    )
    parser.add_argument(
        "--scenario-id",
        default=None,
        help="Run a single scenario by id",
    )
    parser.add_argument(
        "--category",
        default=None,
        help="Filter scenarios by category",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after first failing scenario",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing report outputs",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_SUMMARY_JSON,
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=DEFAULT_REPORT_MD,
    )
    parser.add_argument(
        "--results-jsonl",
        type=Path,
        default=DEFAULT_RESULTS_JSONL,
    )
    parser.add_argument(
        "--golden-dir",
        type=Path,
        default=DEFAULT_GOLDEN_DIR,
        help="Directory for golden draft fingerprints",
    )
    parser.add_argument(
        "--check-golden",
        action="store_true",
        help="Compare draft fingerprints against golden_outputs/",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Write draft fingerprints to golden_outputs/ after each run",
    )
    parser.add_argument(
        "--confirm-real-openai",
        action="store_true",
        help="Required when --provider openai",
    )
    args = parser.parse_args(argv)

    if args.provider == "openai" and not args.confirm_real_openai:
        print("error: --provider openai requires --confirm-real-openai", file=sys.stderr)
        return 2

    if not args.scenarios_path.is_file():
        print(f"error: scenarios file not found: {args.scenarios_path}", file=sys.stderr)
        return 2

    scenarios = load_eval_scenarios(
        args.scenarios_path,
        scenario_id=args.scenario_id,
        category=args.category,
        limit=args.limit,
    )
    if not scenarios:
        print("error: no scenarios matched filters", file=sys.stderr)
        return 2

    summary = run_multi_turn_eval_suite(
        scenarios,
        settings=get_settings(),
        provider=args.provider,
        enable_knowledge_hints=args.enable_knowledge_hints,
        scenarios_path=args.scenarios_path,
        golden_dir=args.golden_dir,
        check_golden=args.check_golden,
        update_golden=args.update_golden,
        fail_fast=args.fail_fast,
    )

    write_multi_turn_eval_reports(
        summary,
        scenarios,
        summary_json=args.summary_json,
        report_md=args.report_md,
        results_jsonl=args.results_jsonl,
        overwrite=args.overwrite,
    )

    print("multi_turn_eval_suite: complete")
    print(f"  status={summary.status}")
    print(f"  passed={summary.passed_count}/{summary.total_scenarios}")
    print(f"  pass_rate={summary.pass_rate:.1%}")
    print(f"  summary_json={args.summary_json.resolve()}")
    print(f"  report_md={args.report_md.resolve()}")
    print(f"  results_jsonl={args.results_jsonl.resolve()}")
    print(f"  reflection_rewrite_count={summary.reflection_rewrite_count}")
    print(f"  reflection_saved_bad_draft_count={summary.reflection_saved_bad_draft_count}")
    return 0 if summary.status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
