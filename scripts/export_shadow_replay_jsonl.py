#!/usr/bin/env python3
"""Export sanitized shadow replay JSONL from local ticket exports (offline reporting only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.shadow_replay_jsonl_export import (
    ShadowReplayExportConfig,
    configure_mock_workflow_runtime,
    export_shadow_replay_jsonl_file,
    format_export_summary,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export sanitized shadow replay JSONL for offline metrics dashboards. "
            "Local/gitignored only; no raw content."
        ),
    )
    parser.add_argument(
        "export_path",
        type=Path,
        help="Path to UTF-8 ticket export JSONL (e.g. redacted vendor tickets)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Path to write shadow replay JSONL (local artifact; do not commit)",
    )
    parser.add_argument(
        "--namespace",
        required=True,
        help="Pilot sandbox namespace (e.g. vendor_ticket_real_pilot_balanced)",
    )
    parser.add_argument(
        "--index-version",
        required=True,
        help="Pilot sandbox index version (e.g. pilot_balanced_v1)",
    )
    parser.add_argument(
        "--profile",
        default="semantic_pgvector",
        help="Sandbox retrieval profile (default: semantic_pgvector)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Top-k for sandbox retrieval when gate allows (default: 5)",
    )
    parser.add_argument(
        "--confirm-sandbox",
        action="store_true",
        help="Required: confirm local sandbox-only export (not production)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output file",
    )
    args = parser.parse_args(argv)

    if not args.confirm_sandbox:
        print(
            "export_shadow_replay_jsonl: --confirm-sandbox is required",
            file=sys.stderr,
        )
        return 1

    if not args.export_path.is_file():
        print(
            f"export_shadow_replay_jsonl: file not found: {args.export_path}",
            file=sys.stderr,
        )
        return 1

    if args.output.exists() and not args.overwrite:
        print(
            f"export_shadow_replay_jsonl: output exists: {args.output} (use --overwrite)",
            file=sys.stderr,
        )
        return 1

    configure_mock_workflow_runtime()

    export_config = ShadowReplayExportConfig(
        namespace=args.namespace,
        index_version=args.index_version,
        profile=args.profile,
        top_k=args.top_k,
        confirm_sandbox=True,
    )

    try:
        summary = export_shadow_replay_jsonl_file(
            args.export_path,
            args.output,
            export_config,
        )
    except ValueError as exc:
        print(f"export_shadow_replay_jsonl: {exc}", file=sys.stderr)
        return 1

    print(
        format_export_summary(
            summary,
            export_path=str(args.export_path),
            output_path=str(args.output),
        )
    )
    if summary.exported_rows == 0 and summary.valid_tickets > 0:
        print(
            "export_shadow_replay_jsonl: warning: no rows exported despite valid tickets",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
