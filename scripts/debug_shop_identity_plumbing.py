#!/usr/bin/env python3
"""Trace shop-identity plumbing from live rooms to reflection context (safe output only)."""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_graph import initial_state_from_ticket
from app.live_feed.ticket_feed_adapter import normalize_live_ticket
from app.live_shadow.live_first_turn_shadow_intake import operator_ticket_from_live_ticket
from app.live_shadow.live_rooms_adapter import (
    extract_shop_identity_from_room,
    normalize_room_to_live_ticket,
)
from app.operator_console.assisted_ticket_input_builder import (
    build_assisted_graph_input_from_operator_ticket,
)

DEFAULT_RAW_ROOMS_PATH = Path("data/private/live_rooms_raw.json")
DEFAULT_SUMMARY_PATH = Path("reports/shop_identity_debug_summary.json")
DEFAULT_REPORT_PATH = Path("reports/shop_identity_debug_report.md")


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= 4:
        return "****"
    return f"****{text[-4:]}"


def _load_rooms(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("rooms"), list):
        return [item for item in payload["rooms"] if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _pick_room(rooms: list[dict[str, Any]], room_id: str | None) -> dict[str, Any]:
    if not rooms:
        raise ValueError("no rooms found in raw source")
    if not room_id:
        return rooms[0]
    target = room_id.strip()
    for room in rooms:
        raw = room.get("id", room.get("room_id"))
        if raw is not None and str(raw).strip() == target:
            return room
    raise ValueError(f"room_id not found: {room_id}")


def _build_summary(
    *,
    room: dict[str, Any],
    manual_shop_id: str | None,
    text: str,
) -> dict[str, Any]:
    raw_identity = extract_shop_identity_from_room(room)
    normalized = normalize_room_to_live_ticket(room)
    ticket = normalize_live_ticket(normalized)
    operator_ticket = operator_ticket_from_live_ticket(ticket)
    if manual_shop_id and manual_shop_id.strip():
        operator_ticket = replace(
            operator_ticket,
            shop_id=manual_shop_id.strip(),
            shop_identity_available=True,
        )
    bundle = build_assisted_graph_input_from_operator_ticket(
        operator_ticket,
        conversation_snapshot=ticket.snapshot,
        source_mode="live_api_feed",
    )
    graph_state = initial_state_from_ticket(
        operator_ticket,
        conversation_snapshot=ticket.snapshot,
    )
    runtime_identity = bool(
        graph_state.get("shop_identity_available")
        or graph_state.get("shop_id")
        or graph_state.get("seller_id")
        or graph_state.get("shop_name")
    )
    draft_requests_shop_id = "شناسه فروشگاه" in text
    rewrite_expected = runtime_identity and draft_requests_shop_id
    return {
        "room_id": str(normalized.get("room_id") or ""),
        "raw_room": {
            "shop_id_present": raw_identity["shop_id_present"],
            "shop_id_source": raw_identity["shop_id_source"],
            "seller_id_present": raw_identity["seller_id_present"],
            "seller_id_source": raw_identity["seller_id_source"],
            "shop_name_present": raw_identity["shop_name_present"],
            "shop_name_source": raw_identity["shop_name_source"],
        },
        "normalized_ticket": {
            "shop_id_present": bool(normalized.get("shop_id")),
            "seller_id_present": bool(normalized.get("seller_id")),
            "shop_name_present": bool(normalized.get("shop_name")),
            "shop_identity_available": bool(normalized.get("shop_identity_available")),
        },
        "operator_ticket": {
            "shop_id_present": bool(operator_ticket.shop_id),
            "seller_id_present": bool(operator_ticket.seller_id),
            "shop_name_present": bool(operator_ticket.shop_name),
            "shop_identity_available": bool(operator_ticket.shop_identity_available),
            "shop_id_masked": _mask(operator_ticket.shop_id),
        },
        "assisted_graph_input": {
            "safe_metadata_shop_id_present": bool(bundle.safe_metadata.get("shop_id")),
            "safe_metadata_seller_id_present": bool(bundle.safe_metadata.get("seller_id")),
            "safe_metadata_shop_name_present": bool(bundle.safe_metadata.get("shop_name")),
            "safe_metadata_shop_identity_available": bool(
                bundle.safe_metadata.get("shop_identity_available")
            ),
        },
        "reflection_context": {
            "runtime_shop_identity_available": runtime_identity,
            "runtime_shop_id_present": bool(graph_state.get("shop_id")),
            "reflection_unnecessary_identifier_detected_expected": rewrite_expected,
            "reflection_rewrite_applied_expected": rewrite_expected,
        },
    }


def _write_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Shop Identity Plumbing Debug Report",
        "",
        f"- room_id: `{summary.get('room_id')}`",
        "",
        "## Raw Room Identity",
    ]
    for key, value in summary["raw_room"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Normalized Ticket"])
    for key, value in summary["normalized_ticket"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Operator Ticket"])
    for key, value in summary["operator_ticket"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Assisted Graph Input"])
    for key, value in summary["assisted_graph_input"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Reflection Context (Expected)"])
    for key, value in summary["reflection_context"].items():
        lines.append(f"- {key}: `{value}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("live",), default="live")
    parser.add_argument("--room-id", default=None)
    parser.add_argument("--manual-shop-id", default=None)
    parser.add_argument("--text", default="لطفاً شناسه فروشگاه خود را برای تغییر نام ارسال کنید.")
    parser.add_argument("--raw-path", type=Path, default=DEFAULT_RAW_ROOMS_PATH)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--report-output", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    if (args.summary_output.exists() or args.report_output.exists()) and not args.overwrite:
        raise SystemExit("output exists; use --overwrite")

    rooms = _load_rooms(args.raw_path)
    room = _pick_room(rooms, args.room_id)
    summary = _build_summary(
        room=room,
        manual_shop_id=args.manual_shop_id,
        text=str(args.text),
    )
    args.summary_output.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        "utf-8",
    )
    _write_markdown(summary, args.report_output)
    print(
        json.dumps(
            {
                "summary_output": str(args.summary_output),
                "report_output": str(args.report_output),
                "room_id": summary.get("room_id"),
            },
            ensure_ascii=False,
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
