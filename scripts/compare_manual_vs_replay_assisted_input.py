#!/usr/bin/env python3
"""Compare manual sandbox vs historical replay assisted graph inputs (diagnostics)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.operator_console.agentic_assisted_mode import build_agentic_assisted_package
from app.operator_console.assisted_input_consistency import (
    build_assisted_input_snapshot_from_historical,
    build_assisted_input_snapshot_from_manual,
    build_manual_ticket_for_comparison,
    compare_assisted_input_snapshots,
    comparison_to_dict,
    package_graph_summary,
    snapshot_to_dict,
)
from app.operator_console.console_loader import (
    DEFAULT_REDACTED_TICKETS_PATH,
    DEFAULT_REPLAY_PATH,
    load_operator_tickets,
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_markdown(
    path: Path,
    *,
    room_id: str,
    comparison: dict[str, object],
    payload: dict[str, object],
) -> None:
    lines = [
        f"# Manual vs replay assisted input — `{room_id}`",
        "",
        f"**All input fields match:** {comparison.get('all_match')}",
        "",
    ]
    explainable = comparison.get("explainable_differences") or []
    if explainable:
        lines.append("## Explainable differences")
        lines.extend(f"- {item}" for item in explainable)
        lines.append("")
    lines.append("## Field comparison")
    lines.append("| field | historical | manual | match |")
    lines.append("| --- | --- | --- | --- |")
    for row in comparison.get("fields") or []:
        if not isinstance(row, dict):
            continue
        lines.append(
            f"| {row.get('field_name')} | {row.get('historical_value')} | "
            f"{row.get('manual_value')} | {row.get('match')} |",
        )
    lines.extend(
        [
            "",
            "## Historical graph summary",
            "```json",
            json.dumps(payload.get("historical_graph_summary"), indent=2, ensure_ascii=False),
            "```",
            "",
            "## Manual graph summary",
            "```json",
            json.dumps(payload.get("manual_graph_summary"), indent=2, ensure_ascii=False),
            "```",
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare manual sandbox vs replay assisted inputs.",
    )
    parser.add_argument("--room-id", required=True, help="Historical replay room_id")
    parser.add_argument(
        "--manual-text",
        required=True,
        help="Seller message to simulate in manual chat",
    )
    parser.add_argument(
        "--ticket-label",
        default=None,
        help="Optional ticket_label for manual path (omit for auto/unset)",
    )
    parser.add_argument("--replay-jsonl", type=Path, default=DEFAULT_REPLAY_PATH)
    parser.add_argument("--redacted-jsonl", type=Path, default=DEFAULT_REDACTED_TICKETS_PATH)
    parser.add_argument("--provider", choices=("mock", "openai"), default=None)
    parser.add_argument("--enable-knowledge-hints", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    out_json = Path(f"reports/manual_vs_replay_assisted_input_{args.room_id}.json")
    out_md = Path(f"reports/manual_vs_replay_assisted_input_{args.room_id}.md")
    if not args.overwrite and out_json.is_file():
        print(f"Output exists (use --overwrite): {out_json}", file=sys.stderr)
        return 1

    tickets = load_operator_tickets(args.replay_jsonl, redacted_tickets_path=args.redacted_jsonl)
    historical = next((ticket for ticket in tickets if ticket.room_id == args.room_id), None)
    if historical is None:
        print(f"room_id not found in replay: {args.room_id}", file=sys.stderr)
        return 1

    settings = get_settings()
    updates: dict[str, object] = {}
    if args.provider:
        updates["operator_agentic_assisted_provider"] = args.provider
        updates["operator_agentic_sandbox_provider"] = args.provider
    if args.enable_knowledge_hints:
        updates["operator_agentic_assisted_knowledge_hints_enabled"] = True
        updates["operator_agentic_sandbox_knowledge_hints_enabled"] = True
        updates["knowledge_hints_enabled"] = True
    cfg = settings.model_copy(update=updates) if updates else settings

    manual_ticket, manual_snapshot = build_manual_ticket_for_comparison(
        args.manual_text,
        room_id=args.room_id,
        ticket_label=args.ticket_label,
        shop_id=historical.shop_id,
    )

    hist_package = build_agentic_assisted_package(
        historical,
        settings=cfg,
        conversation_snapshot=None,
        source_mode="historical_replay",
    )
    manual_package = build_agentic_assisted_package(
        manual_ticket,
        settings=cfg,
        conversation_snapshot=manual_snapshot,
        source_mode="manual_sandbox_chat",
    )

    hist_snapshot = build_assisted_input_snapshot_from_historical(
        historical,
        settings=cfg,
        graph_result=hist_package.graph,
    )
    manual_snapshot_row = build_assisted_input_snapshot_from_manual(
        manual_ticket,
        conversation_snapshot=manual_snapshot,
        settings=cfg,
        graph_result=manual_package.graph,
    )
    comparison = compare_assisted_input_snapshots(hist_snapshot, manual_snapshot_row)

    payload: dict[str, object] = {
        "room_id": args.room_id,
        "settings": {
            "provider": cfg.operator_agentic_assisted_provider,
            "knowledge_hints_enabled": cfg.operator_agentic_assisted_knowledge_hints_enabled,
            "multi_turn_context_enabled": cfg.multi_turn_context_enabled,
        },
        "historical_input": snapshot_to_dict(hist_snapshot),
        "manual_input": snapshot_to_dict(manual_snapshot_row),
        "comparison": comparison_to_dict(comparison),
        "historical_graph_summary": package_graph_summary(hist_package),
        "manual_graph_summary": package_graph_summary(manual_package),
    }
    _write_json(out_json, payload)
    _write_markdown(out_md, room_id=args.room_id, comparison=payload["comparison"], payload=payload)
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
