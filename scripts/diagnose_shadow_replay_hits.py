#!/usr/bin/env python3
"""Diagnose shadow replay zero-hit exports (local/gitignored reports; no raw content)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.shadow_replay_hit_diagnosis import (
    run_shadow_replay_hit_diagnosis,
    write_shadow_replay_hit_diagnosis_report,
)

_DEFAULT_SHADOW = Path("reports/shadow_replay_balanced_v1.jsonl")
_DEFAULT_TICKET_EXPORT = Path("data/private/vendor_tickets_400.redacted.jsonl")
_DEFAULT_JSON = Path("reports/shadow_replay_hit_diagnosis.json")
_DEFAULT_MD = Path("reports/shadow_replay_hit_diagnosis.md")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose shadow replay retrieval_result_count=0 (aggregate-safe; "
            "optional pgvector index checks)."
        ),
    )
    parser.add_argument(
        "shadow_replay_path",
        type=Path,
        nargs="?",
        default=_DEFAULT_SHADOW,
        help="Shadow replay JSONL from export_shadow_replay_jsonl.py",
    )
    parser.add_argument(
        "--ticket-export",
        type=Path,
        default=_DEFAULT_TICKET_EXPORT,
        help="Optional ticket export JSONL for query-build diagnosis",
    )
    parser.add_argument(
        "--namespace",
        default="vendor_ticket_real_pilot_balanced",
        help="Pilot sandbox namespace for pgvector checks",
    )
    parser.add_argument(
        "--index-version",
        default="pilot_balanced_v1",
        help="Pilot sandbox index version for pgvector checks",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL (defaults to PGVECTOR_DATABASE_URL)",
    )
    parser.add_argument(
        "--skip-pgvector",
        action="store_true",
        help="Skip pgvector index checks",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=_DEFAULT_JSON,
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=_DEFAULT_MD,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing report files",
    )
    args = parser.parse_args(argv)

    if not args.shadow_replay_path.is_file():
        print(
            f"diagnose_shadow_replay_hits: file not found: {args.shadow_replay_path}",
            file=sys.stderr,
        )
        return 1

    for path in (args.json_output, args.markdown_output):
        if path.exists() and not args.overwrite:
            print(
                f"diagnose_shadow_replay_hits: output exists: {path} (use --overwrite)",
                file=sys.stderr,
            )
            return 1

    ticket_path = args.ticket_export if args.ticket_export.is_file() else None
    db_url = args.database_url
    if args.skip_pgvector:
        db_url = ""

    diagnosis = run_shadow_replay_hit_diagnosis(
        args.shadow_replay_path,
        namespace=args.namespace,
        index_version=args.index_version,
        database_url=db_url,
        ticket_export_path=ticket_path,
    )
    write_shadow_replay_hit_diagnosis_report(
        diagnosis,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
    )

    r = diagnosis.replay_summary
    print("diagnose_shadow_replay_hits: complete")
    print(f"  shadow_replay={args.shadow_replay_path.resolve()}")
    print(f"  total_rows={r.total_rows}")
    print(f"  result_count_distribution={r.retrieval_result_count_distribution}")
    if diagnosis.index_diagnosis and diagnosis.index_diagnosis.pgvector_available:
        print(f"  index_row_count={diagnosis.index_diagnosis.index_row_count}")
        print(
            "  export_filter_patterns_all_zero_hits="
            f"{diagnosis.index_diagnosis.export_filter_patterns_all_zero_hits}"
        )
    if diagnosis.query_diagnosis:
        q = diagnosis.query_diagnosis
        print(f"  query_empty_count={q.query_empty_count}")
        print(f"  query_nonempty_count={q.query_nonempty_count}")
    print(f"  json={args.json_output.resolve()}")
    print(f"  markdown={args.markdown_output.resolve()}")
    if diagnosis.findings:
        print("  primary_finding:", diagnosis.findings[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
