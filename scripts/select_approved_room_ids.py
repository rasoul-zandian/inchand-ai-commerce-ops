#!/usr/bin/env python3
"""Select candidate approved room IDs from replay report (local governance helper)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.corpus_planning.room_selection import (
    RoomSelectionCriteria,
    format_approved_room_ids_file,
    load_replay_rows_in_order,
    parse_label_balance_targets,
    select_approved_room_ids_from_rows,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select candidate approved room IDs from replay JSONL (no raw text).",
    )
    parser.add_argument("report_path", type=Path, help="Path to replay report JSONL")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Path to write approved room IDs file (local/private)",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output file")
    parser.add_argument("--limit", type=int, default=None, help="Maximum room IDs to select")
    parser.add_argument(
        "--include-label",
        action="append",
        default=[],
        help="Include only tickets with this ticket_label (repeatable)",
    )
    parser.add_argument(
        "--exclude-label",
        action="append",
        default=[],
        help="Exclude tickets with this ticket_label (repeatable)",
    )
    parser.add_argument(
        "--include-department",
        action="append",
        default=[],
        help="Include only tickets with this assigned_department (repeatable)",
    )
    parser.add_argument(
        "--exclude-department",
        action="append",
        default=[],
        help="Exclude tickets with this assigned_department (repeatable)",
    )
    parser.add_argument(
        "--exclude-qa-attention",
        action="store_true",
        help="Exclude rows flagged for QA attention",
    )
    parser.add_argument(
        "--balance-pilot",
        action="store_true",
        help="Balanced ~25-room pilot targets (support=10, complaint=7, fund=8)",
    )
    parser.add_argument(
        "--balance-label",
        action="append",
        default=[],
        metavar="LABEL=COUNT",
        help=(
            "Per-label quota for balanced selection "
            "(repeatable; overrides --balance-pilot defaults)"
        ),
    )
    args = parser.parse_args(argv)

    if not args.report_path.is_file():
        print(f"select_approved_room_ids: file not found: {args.report_path}", file=sys.stderr)
        return 1
    if args.output.exists() and not args.overwrite:
        print(f"select_approved_room_ids: output exists: {args.output}", file=sys.stderr)
        return 1
    if args.limit is not None and args.limit < 1:
        print("select_approved_room_ids: --limit must be >= 1", file=sys.stderr)
        return 1
    if args.balance_pilot and args.limit is not None:
        print(
            "select_approved_room_ids: --balance-pilot cannot be used with --limit",
            file=sys.stderr,
        )
        return 1
    if args.balance_label and args.limit is not None:
        print(
            "select_approved_room_ids: --balance-label cannot be used with --limit",
            file=sys.stderr,
        )
        return 1

    label_balance_targets: dict[str, int] | None = None
    if args.balance_pilot or args.balance_label:
        try:
            if args.balance_label:
                label_balance_targets = parse_label_balance_targets(args.balance_label)
            else:
                label_balance_targets = parse_label_balance_targets([])
        except ValueError as exc:
            print(f"select_approved_room_ids: {exc}", file=sys.stderr)
            return 1

    def _norm_list(values: list[str]) -> frozenset[str]:
        return frozenset(item.strip().lower() for item in values if item.strip())

    criteria = RoomSelectionCriteria(
        limit=args.limit,
        include_labels=_norm_list(args.include_label),
        exclude_labels=_norm_list(args.exclude_label),
        include_departments=_norm_list(args.include_department),
        exclude_departments=_norm_list(args.exclude_department),
        exclude_qa_attention=args.exclude_qa_attention,
        label_balance_targets=label_balance_targets,
    )

    try:
        rows = load_replay_rows_in_order(args.report_path)
        result = select_approved_room_ids_from_rows(rows, criteria=criteria)
        if not result.selected_room_ids:
            raise ValueError("selected room_id count is zero; relax filters or check replay report")

        content = format_approved_room_ids_file(
            result.selected_room_ids,
            criteria=criteria,
            source_report=str(args.report_path),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"select_approved_room_ids: {exc}", file=sys.stderr)
        return 1

    print(f"select_approved_room_ids: wrote {args.output}")
    print(f"  selected_count={len(result.selected_room_ids)}")
    print(f"  total_rows_scanned={result.total_rows_scanned}")
    print(f"  excluded_failed={result.excluded_failed}")
    print(f"  excluded_qa_attention={result.excluded_qa_attention}")
    if result.label_target_counts:
        for label in sorted(result.label_target_counts):
            selected = result.label_selected_counts.get(label, 0)
            target = result.label_target_counts[label]
            print(f"  label_{label}={selected}/{target}")
        shortfalls = result.label_shortfalls
        if shortfalls:
            joined = ", ".join(f"{label}={count}" for label, count in sorted(shortfalls.items()))
            print(f"  label_shortfall={joined}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
