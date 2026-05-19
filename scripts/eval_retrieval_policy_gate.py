#!/usr/bin/env python3
"""Evaluate retrieval policy gate against synthetic calibration cases (no retrieval execution)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.retrieval_policy_gate_calibration import (
    load_policy_gate_calibration_cases,
    run_policy_gate_calibration,
    write_policy_gate_calibration_report,
)

_DEFAULT_CASES = Path("evals/retrieval_policy_gate/policy_gate_calibration_cases.json")
_DEFAULT_JSON = Path("reports/retrieval_policy_gate_calibration.json")
_DEFAULT_MD = Path("reports/retrieval_policy_gate_calibration.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run synthetic retrieval policy gate calibration (local/gitignored reports; "
            "no pgvector/OpenAI)."
        ),
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=_DEFAULT_CASES,
        help="Path to calibration cases JSON",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=_DEFAULT_JSON,
        help="JSON report output path",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=_DEFAULT_MD,
        help="Markdown report output path",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing report files",
    )
    args = parser.parse_args(argv)

    if not args.cases.is_file():
        print(f"eval_retrieval_policy_gate: cases file not found: {args.cases}", file=sys.stderr)
        return 1

    for path in (args.json_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"eval_retrieval_policy_gate: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 1

    suite = load_policy_gate_calibration_cases(args.cases)
    report = run_policy_gate_calibration(suite, source_path=str(args.cases))
    write_policy_gate_calibration_report(
        report,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )

    status = "passed" if report.pass_rate == 1.0 else "failed"
    print(f"eval_retrieval_policy_gate: {status}")
    print(f"  total_cases={report.total_cases}")
    print(f"  passed_cases={report.passed_cases}")
    print(f"  failed_cases={report.failed_cases}")
    print(f"  pass_rate={report.pass_rate:.4f}")
    print(f"  json={args.json_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    return 0 if report.pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
