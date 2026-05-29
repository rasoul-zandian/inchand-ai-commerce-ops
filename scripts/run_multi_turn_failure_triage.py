#!/usr/bin/env python3
"""Triage multi-turn eval failures — classify, cluster, prioritize (analysis only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.evals.multi_turn_eval_runner import DEFAULT_RESULTS_JSONL, DEFAULT_SCENARIOS_PATH
from app.evals.multi_turn_failure_triage import (
    DEFAULT_TRIAGE_CLUSTERS_JSON,
    DEFAULT_TRIAGE_REPORT_MD,
    DEFAULT_TRIAGE_SUMMARY_JSON,
    load_eval_results_jsonl,
    run_failure_triage,
    write_failure_triage_reports,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze multi_turn_eval_results.jsonl — classify failures, cluster patterns, "
            "and produce prioritized triage reports (no prompt or rule changes)."
        ),
    )
    parser.add_argument(
        "--results-jsonl",
        type=Path,
        default=DEFAULT_RESULTS_JSONL,
        help="Input eval results JSONL (default: reports/multi_turn_eval_results.jsonl)",
    )
    parser.add_argument(
        "--scenarios-path",
        type=Path,
        default=DEFAULT_SCENARIOS_PATH,
        help="Optional scenarios JSON for conversation summaries",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        default=DEFAULT_TRIAGE_SUMMARY_JSON,
    )
    parser.add_argument(
        "--report-md",
        type=Path,
        default=DEFAULT_TRIAGE_REPORT_MD,
    )
    parser.add_argument(
        "--clusters-json",
        type=Path,
        default=DEFAULT_TRIAGE_CLUSTERS_JSON,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing triage outputs",
    )
    args = parser.parse_args(argv)

    if not args.results_jsonl.is_file():
        print(f"error: results file not found: {args.results_jsonl}", file=sys.stderr)
        print(
            "hint: run scripts/run_multi_turn_eval_suite.py first",
            file=sys.stderr,
        )
        return 2

    rows = load_eval_results_jsonl(args.results_jsonl)
    scenarios_by_id: dict[str, object] = {}
    if args.scenarios_path.is_file():
        from app.evals.multi_turn_eval_runner import load_eval_scenarios

        for scenario in load_eval_scenarios(args.scenarios_path):
            scenarios_by_id[scenario.scenario_id] = scenario

    summary = run_failure_triage(
        rows,
        scenarios_by_id=scenarios_by_id,
        source_path=str(args.results_jsonl.resolve()),
    )

    write_failure_triage_reports(
        summary,
        summary_json=args.summary_json,
        report_md=args.report_md,
        clusters_json=args.clusters_json,
        overwrite=args.overwrite,
    )

    print("multi_turn_failure_triage: complete")
    print(f"  failed_scenarios={summary.failed_scenarios}/{summary.total_scenarios}")
    print(f"  real_failures={summary.real_failure_count}")
    print(f"  acceptable_variance={summary.acceptable_variance_count}")
    print(f"  clusters={len(summary.clusters)}")
    print(f"  reflection_miss_rate={summary.reflection_metrics.reflection_miss_rate:.1%}")
    print(f"  summary_json={args.summary_json.resolve()}")
    print(f"  report_md={args.report_md.resolve()}")
    print(f"  clusters_json={args.clusters_json.resolve()}")
    if summary.clusters:
        top = summary.clusters[0]
        print(
            f"  top_cluster: {top.cluster_id} ({top.occurrence_count}×) {top.failure_type.value}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
