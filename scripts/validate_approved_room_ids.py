#!/usr/bin/env python3
"""Validate approved room IDs against redacted export (counts only)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.room_selection import validate_approved_room_ids_against_export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate approved room IDs exist in redacted JSONL (no raw text).",
    )
    parser.add_argument("export_path", type=Path, help="Redacted conversation-ticket JSONL")
    parser.add_argument(
        "--approved-room-ids",
        type=Path,
        required=True,
        help="Approved room IDs text file",
    )
    args = parser.parse_args(argv)

    if not args.export_path.is_file():
        print(f"validate_approved_room_ids: export not found: {args.export_path}", file=sys.stderr)
        return 1
    if not args.approved_room_ids.is_file():
        print(
            f"validate_approved_room_ids: approved list not found: {args.approved_room_ids}",
            file=sys.stderr,
        )
        return 1

    try:
        result = validate_approved_room_ids_against_export(
            args.export_path,
            args.approved_room_ids,
        )
    except ValueError as exc:
        print(f"validate_approved_room_ids: {exc}", file=sys.stderr)
        return 1

    print(f"validate_approved_room_ids: export={args.export_path}")
    print(f"  approved_count={result.approved_count}")
    print(f"  found_count={result.found_count}")
    print(f"  duplicate_approved_ids={result.duplicate_approved_ids}")
    if result.missing_room_ids:
        print(f"  missing_count={len(result.missing_room_ids)}")
        for room_id in result.missing_room_ids[:10]:
            print(f"    missing: {room_id}")
        if len(result.missing_room_ids) > 10:
            print(f"    ... and {len(result.missing_room_ids) - 10} more")
        return 1

    print("  result: passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
