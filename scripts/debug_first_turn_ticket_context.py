#!/usr/bin/env python3
"""Safe debug helper for first-turn draft entity isolation (no full transcript)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.config import AppSettings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import (
    analyze_first_turn_entity_leakage,
    list_included_prompt_fields,
    prompt_text_from_messages,
)
from app.evals.first_turn_draft_context import (
    build_first_turn_draft_context_from_ticket,
    first_turn_text_from_ticket,
)
from app.evals.offline_draft_generation import build_offline_draft_messages
from app.hitl.hitl_payload_builder import build_hitl_read_only_payload_from_replay_row
from app.operator_console.console_loader import enrich_ai_assist_replay_row, load_replay_rows
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_preview import (
    _thread_texts_from_ticket,
    enrich_draft_preview_with_first_turn_entities,
)
from app.operator_console.intent_display import (
    extract_first_turn_display_entities,
    format_open_snapshot_entity_lines,
)
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)
from app.workflows.operational_entity_extraction import extract_operational_entities

_VENDOR_SENDERS = frozenset({"seller", "vendor"})


def _preview_from_snapshot(snapshot: ConversationTicketSnapshot) -> dict[str, str | None]:
    from app.live_feed.open_ticket_snapshot import (
        build_open_ticket_snapshot,
        open_ticket_snapshot_to_payload,
    )

    try:
        built = build_open_ticket_snapshot(snapshot)
        payload = open_ticket_snapshot_to_payload(built)
    except ValueError:
        payload = {}
    first_seller: str | None = None
    latest_seller: str | None = None
    for message in snapshot.messages:
        if message.sender_type not in _VENDOR_SENDERS:
            continue
        text = message.text.strip()
        if not text:
            continue
        if first_seller is None:
            first_seller = text[:500]
        latest_seller = text[:500]
    return {
        "first_seller_message_preview": first_seller,
        "latest_seller_message_preview": latest_seller,
        "original_vendor_issue_preview": payload.get("original_vendor_issue_preview"),
        "latest_vendor_message": payload.get("latest_vendor_message"),
    }


def _entity_summary_from_result(result: Any) -> dict[str, Any]:
    return {
        "order_ids": list(result.order_ids),
        "product_ids": list(result.product_ids),
        "tracking_code": result.primary_tracking_code,
        "warnings": result.entity_warnings_summary,
    }


def _entity_summary(text: str) -> dict[str, Any]:
    return _entity_summary_from_result(extract_operational_entities(text))


def _ticket_from_replay_row(row: dict[str, Any]) -> OperatorTicket:
    enriched = enrich_ai_assist_replay_row(row, retrieval_index={})
    payload = build_hitl_read_only_payload_from_replay_row(enriched)
    return OperatorTicket.from_hitl_payload(payload)


def _find_snapshot(path: Path, room_id: str) -> ConversationTicketSnapshot | None:
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            snapshot = parse_conversation_ticket_snapshot(line)
        except (ValueError, json.JSONDecodeError):
            continue
        if snapshot.room_id == room_id:
            return snapshot
    return None


def _find_replay_row(path: Path, room_id: str) -> dict[str, Any] | None:
    for row in load_replay_rows(path):
        if str(row.get("room_id")) == room_id:
            return dict(row)
    return None


def _build_prompt_debug(ticket: OperatorTicket) -> dict[str, Any]:
    settings = AppSettings(knowledge_hints_enabled=False, draft_generation_mode="first_turn_only")
    ctx = build_first_turn_draft_context_from_ticket(ticket, settings=settings, hints=())
    case = {
        "ticket_label": ticket.ticket_label,
        "route_label": ticket.route_label,
        "snapshot_before_reply": {
            "original_vendor_issue_preview": ticket.original_vendor_issue_preview,
            "latest_vendor_message": ticket.latest_vendor_message,
        },
        "open_ticket_preview": ticket.open_ticket_preview,
        "ticket_text_preview": ticket.ticket_text_preview,
    }
    messages = build_offline_draft_messages(
        case,
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=(),
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
        first_turn_context=ctx,
    )
    prompt = prompt_text_from_messages(messages)
    included = list_included_prompt_fields(
        case,
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=(),
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
    )
    first_turn = first_turn_text_from_ticket(ticket)
    leakage = analyze_first_turn_entity_leakage(
        prompt,
        first_turn_text=first_turn,
        thread_texts=_thread_texts_from_ticket(ticket),
        ticket=ticket,
    )
    return {
        "prompt_included_fields": included,
        "forbidden_later_only_values": leakage["forbidden_later_only_values"],
        "prompt_contains_forbidden_later_only_values": leakage[
            "prompt_contains_forbidden_later_only_values"
        ],
        "entity_leakage_analysis": leakage,
        "prompt_char_count": len(prompt),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--room-id", required=True)
    parser.add_argument(
        "--redacted-jsonl",
        default="data/private/vendor_tickets_400.redacted.jsonl",
    )
    parser.add_argument(
        "--replay-jsonl",
        default="reports/ai_assist_shadow_replay_v1.jsonl",
    )
    args = parser.parse_args()
    room_id = args.room_id.strip()

    snapshot = _find_snapshot(Path(args.redacted_jsonl), room_id)
    replay_row = _find_replay_row(Path(args.replay_jsonl), room_id)
    if replay_row is None:
        print(
            json.dumps(
                {"error": f"room_id {room_id} not found in replay JSONL"},
                ensure_ascii=False,
            ),
        )
        return 1

    ticket = _ticket_from_replay_row(replay_row)
    previews: dict[str, str | None] = {
        "first_seller_message_preview": None,
        "latest_seller_message_preview": None,
        "original_vendor_issue_preview": ticket.original_vendor_issue_preview,
        "latest_vendor_message": ticket.latest_vendor_message,
    }
    if snapshot is not None:
        previews.update(_preview_from_snapshot(snapshot))

    first_turn_text = first_turn_text_from_ticket(ticket)
    first_turn_display_entities = _entity_summary_from_result(
        extract_first_turn_display_entities(ticket),
    )
    latest_text = previews.get("latest_vendor_message") or ""
    latest_only_entities = _entity_summary(latest_text)
    open_snapshot_entities = {
        "ticket_row_fields": {
            "extracted_order_ids": ticket.extracted_order_ids,
            "extracted_order_id": ticket.extracted_order_id,
            "extracted_product_ids": ticket.extracted_product_ids,
            "extracted_tracking_code": ticket.extracted_tracking_code,
        },
        "from_latest_vendor_message_text": latest_only_entities,
        "console_debug_lines": format_open_snapshot_entity_lines(ticket),
    }

    debug_settings = AppSettings(
        knowledge_hints_enabled=False,
        draft_generation_mode="first_turn_only",
    )
    from app.operator_console.draft_preview import DraftPreviewRecord

    stub = DraftPreviewRecord(room_id=room_id, draft_reply="(debug)")
    enriched = enrich_draft_preview_with_first_turn_entities(
        stub,
        ticket,
        settings=debug_settings,
    )
    draft_entities: dict[str, Any] = _entity_summary(first_turn_text)
    if enriched is not None:
        draft_entities = {
            "order_ids": _split_csv(enriched.draft_extracted_order_ids),
            "product_ids": _split_csv(enriched.draft_extracted_product_ids),
            "tracking_code": enriched.draft_extracted_tracking_code,
            "warnings": enriched.draft_entity_warnings_summary,
            "draft_entity_source": enriched.draft_entity_source,
        }

    prompt_debug = _build_prompt_debug(ticket)

    report = {
        "room_id": room_id,
        "ticket_label": ticket.ticket_label,
        "first_seller_message_preview": previews.get("first_seller_message_preview"),
        "latest_seller_message_preview": previews.get("latest_seller_message_preview"),
        "original_vendor_issue_preview": previews.get("original_vendor_issue_preview"),
        "latest_vendor_message_preview": previews.get("latest_vendor_message"),
        "first_turn_display_entities": first_turn_display_entities,
        "open_snapshot_entities": open_snapshot_entities,
        "latest_only_entities": latest_only_entities,
        "draft_context_entities": draft_entities,
        **prompt_debug,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _split_csv(value: str | None) -> list[str]:
    if not value or not value.strip():
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


if __name__ == "__main__":
    sys.exit(main())
