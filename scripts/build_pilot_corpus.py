#!/usr/bin/env python3
"""Build governance-gated pilot corpus from manually approved room IDs (no embeddings)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.pilot_corpus_builder import (
    build_pilot_corpus,
    load_approved_room_ids,
)

_DEFAULT_CORPUS_DIR = Path("corpus/vendor_ticket_real_pilot")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build pilot corpus artifacts from approved room IDs only "
            "(no embeddings, indexing, or OpenAI)."
        ),
    )
    parser.add_argument(
        "export_path",
        type=Path,
        help="Normalized conversation-ticket JSONL export (local/private)",
    )
    parser.add_argument(
        "--approved-room-ids",
        type=Path,
        required=True,
        help="Text file with one approved room_id per line (# comments allowed)",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=_DEFAULT_CORPUS_DIR,
        help=f"Output corpus directory (default: {_DEFAULT_CORPUS_DIR})",
    )
    parser.add_argument(
        "--source-batch-id",
        required=True,
        help="Aggregate batch label (e.g. replay_166_v1)",
    )
    parser.add_argument(
        "--reviewer-signoff-id",
        required=True,
        help="Reviewer sign-off reference ID (e.g. SIGNOFF_001)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Rebuild an existing corpus directory (local dev/tests)",
    )
    parser.add_argument(
        "--created-at",
        default=None,
        help="Optional fixed UTC timestamp for deterministic builds (ISO-8601)",
    )
    args = parser.parse_args(argv)

    try:
        approved_ids = load_approved_room_ids(args.approved_room_ids)
        result = build_pilot_corpus(
            args.export_path,
            approved_room_ids=approved_ids,
            corpus_dir=args.corpus_dir,
            source_batch_id=args.source_batch_id,
            reviewer_signoff_id=args.reviewer_signoff_id,
            overwrite=args.overwrite,
            created_at=args.created_at,
        )
    except ValueError as exc:
        print(f"build_pilot_corpus: {exc}", file=sys.stderr)
        return 1

    print(f"build_pilot_corpus: wrote {result.corpus_dir}")
    print(f"  approved_record_count={result.approved_record_count}")
    print(f"  manifest={result.manifest_path}")
    print(f"  lockfile={result.lockfile_path}")
    print("  embedding_status=not_started indexing_status=not_started")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
