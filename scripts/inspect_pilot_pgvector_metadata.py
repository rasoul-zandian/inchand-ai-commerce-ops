#!/usr/bin/env python3
"""Inspect pilot sandbox pgvector metadata (local diagnostics; no retrieval activation)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.corpus_planning.pilot_pgvector_metadata_inventory import (
    assert_safe_inventory_report,
    inventory_to_dict,
    run_pilot_metadata_inventory,
    write_pilot_metadata_inventory_report,
)

_DEFAULT_DATABASE_URL = "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pilot pgvector metadata inventory for sandbox diagnostics.",
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
        help="Profile gate (must be semantic_pgvector)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/pilot_pgvector_metadata_inventory_pilot_v1.json"),
        help="Output inventory path (gitignored)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output file",
    )
    args = parser.parse_args(argv)

    if args.output.exists() and not args.overwrite:
        print(
            f"inspect_pilot_pgvector_metadata: output exists: {args.output} (use --overwrite)",
            file=sys.stderr,
        )
        return 1

    database_url = os.environ.get("PGVECTOR_DATABASE_URL", _DEFAULT_DATABASE_URL).strip()
    table_name = os.environ.get("PGVECTOR_TABLE", "rag_vector_records").strip()

    try:
        inventory = run_pilot_metadata_inventory(
            database_url,
            namespace=args.namespace,
            index_version=args.index_version,
            profile=args.profile,
            table_name=table_name,
        )
        written = write_pilot_metadata_inventory_report(
            inventory,
            output_path=args.output,
        )
    except ValueError as exc:
        print(f"inspect_pilot_pgvector_metadata: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"inspect_pilot_pgvector_metadata: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    payload = inventory_to_dict(inventory)
    assert_safe_inventory_report(payload)

    lines = [
        "pilot_pgvector_metadata_inventory: success",
        f"  row_count={inventory.row_count}",
        f"  namespace={inventory.namespace}",
        f"  index_version={inventory.index_version}",
        f"  profile={inventory.profile}",
        f"  ticket_label_counts={inventory.ticket_label_counts}",
        f"  department_counts={inventory.department_counts}",
        f"  route_label_counts={inventory.route_label_counts}",
        f"  missing_field_counts={inventory.missing_field_counts}",
        f"  explicit_department_present_count={inventory.explicit_department_present_count}",
        f"  metadata_keys_present={list(inventory.metadata_keys_present)}",
        "  retrieval_activated=false",
        f"  output_path={written}",
    ]
    print("\n".join(lines))
    return 0 if inventory.row_count > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
