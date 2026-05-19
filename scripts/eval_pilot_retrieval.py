#!/usr/bin/env python3
"""Evaluate sandbox pgvector pilot retrieval (evaluation only; no LangGraph activation)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.corpus_planning.pilot_retrieval_eval import (
    assert_safe_eval_report,
    build_default_pilot_retrieve_fn,
    build_pilot_pgvector_store,
    comparison_report_to_dict,
    load_pilot_retrieval_cases,
    report_to_dict,
    run_pilot_retrieval_comparison_eval,
    run_pilot_retrieval_eval,
    write_pilot_retrieval_comparison_report,
    write_pilot_retrieval_eval_report,
)

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"
_FORBIDDEN_OUTPUT = (
    "conversation_transcript",
    "OPENAI_API_KEY",
    "sk-",
    "BEGIN PRIVATE KEY",
)


def _assert_safe_stdout(text: str) -> None:
    lowered = text.lower()
    for token in _FORBIDDEN_OUTPUT:
        if token.lower() in lowered:
            raise RuntimeError(f"unsafe output token detected in summary: {token}")


def _print_single_report_summary(report: object, *, written: Path, prefix: str = "") -> list[str]:
    from app.corpus_planning.pilot_retrieval_eval import PilotRetrievalEvalReport

    if not isinstance(report, PilotRetrievalEvalReport):
        return []
    tag = f"{prefix} " if prefix else ""
    status = "passed" if report.pass_rate == 1.0 else "failed"
    lines = [
        f"{tag}pilot_retrieval_eval: {status}",
        f"  {tag}eval_mode={report.eval_mode}",
        f"  {tag}total_cases={report.total_cases}",
        f"  {tag}passed_cases={report.passed_cases}",
        f"  {tag}failed_cases={report.failed_cases}",
        f"  {tag}pass_rate={report.pass_rate:.4f}",
        f"  {tag}mean_top_score={report.mean_top_score:.4f}",
        f"  {tag}label_match_rate={report.label_match_rate:.4f}",
        f"  {tag}department_match_rate={report.department_match_rate:.4f}",
        f"  {tag}wrong_label_return_count={report.wrong_label_return_count}",
        f"  {tag}empty_result_count={report.empty_result_count}",
        f"  {tag}top_k={report.top_k}",
        f"  {tag}namespace={report.namespace}",
        f"  {tag}index_version={report.index_version}",
        f"  {tag}profile={report.profile}",
        f"  {tag}retrieval_activated=false",
        f"  {tag}output_path={written}",
    ]
    if report.failed_cases:
        for result in report.results:
            if result.passed:
                continue
            reasons = list(result.failure_reasons)
            lines.append(f"  {tag}case_id={result.case_id} failure_reasons={reasons}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pilot sandbox pgvector retrieval evaluation (local only).",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        required=True,
        help="Path to pilot retrieval eval cases JSON",
    )
    parser.add_argument(
        "--namespace",
        required=True,
        help="Pilot sandbox namespace (e.g. vendor_ticket_real_pilot)",
    )
    parser.add_argument(
        "--index-version",
        required=True,
        help="Pilot sandbox index version (e.g. pilot_v1)",
    )
    parser.add_argument(
        "--profile",
        default="semantic_pgvector",
        help="Retrieval profile gate (must be semantic_pgvector)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-k results per case",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/pilot_retrieval_eval_pilot_v1.json"),
        help="Output report path (gitignored)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output report",
    )
    parser.add_argument(
        "--compare-modes",
        action="store_true",
        help="Run vector_only vs metadata_filtered comparison on cases with metadata_filter",
    )
    args = parser.parse_args(argv)

    if args.output.exists() and not args.overwrite:
        print(
            f"eval_pilot_retrieval: output exists: {args.output} (use --overwrite)",
            file=sys.stderr,
        )
        return 1

    if args.top_k <= 0:
        print("eval_pilot_retrieval: --top-k must be positive", file=sys.stderr)
        return 1

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()
    dimensions = int(os.environ.get("PGVECTOR_DIMENSIONS", "1536"))

    try:
        cases = load_pilot_retrieval_cases(args.cases)
        store = build_pilot_pgvector_store(
            database_url,
            namespace=args.namespace,
            index_version=args.index_version,
            table_name=table_name,
            dimensions=dimensions,
        )
        if args.compare_modes:
            comparison = run_pilot_retrieval_comparison_eval(
                cases,
                namespace=args.namespace,
                index_version=args.index_version,
                profile=args.profile,
                top_k=args.top_k,
                store=store,
            )
            written = write_pilot_retrieval_comparison_report(
                comparison,
                output_path=args.output,
                profile=comparison.profile,
            )
            payload = comparison_report_to_dict(comparison, profile=comparison.profile)
            assert_safe_eval_report(payload)
            lines = [
                "pilot_retrieval_eval: compare-modes",
                f"  delta_pass_rate={comparison.delta_pass_rate:.4f}",
                f"  delta_wrong_label_return_count={comparison.delta_wrong_label_return_count}",
                f"  output_path={written}",
                "  retrieval_activated=false",
            ]
            lines.extend(
                _print_single_report_summary(
                    comparison.vector_only,
                    written=written,
                    prefix="vector_only",
                )
            )
            lines.extend(
                _print_single_report_summary(
                    comparison.metadata_filtered,
                    written=written,
                    prefix="metadata_filtered",
                )
            )
            exit_code = (
                0
                if comparison.metadata_filtered.pass_rate == 1.0
                and comparison.metadata_filtered.wrong_label_return_count == 0
                else 1
            )
        else:
            retrieve_fn = build_default_pilot_retrieve_fn(store)
            report = run_pilot_retrieval_eval(
                cases,
                namespace=args.namespace,
                index_version=args.index_version,
                profile=args.profile,
                top_k=args.top_k,
                retrieve_fn=retrieve_fn,
            )
            written = write_pilot_retrieval_eval_report(
                report,
                output_path=args.output,
                namespace=args.namespace,
                index_version=args.index_version,
                profile=report.profile,
            )
            payload = report_to_dict(
                report,
                namespace=args.namespace,
                index_version=args.index_version,
                profile=report.profile,
            )
            assert_safe_eval_report(payload)
            lines = _print_single_report_summary(report, written=written)
            exit_code = 0 if report.pass_rate == 1.0 else 1
    except ValueError as exc:
        print(f"eval_pilot_retrieval: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"eval_pilot_retrieval: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    output = "\n".join(lines)
    _assert_safe_stdout(output)
    print(output)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
