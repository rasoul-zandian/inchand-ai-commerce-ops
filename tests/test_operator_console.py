"""Minimal sanity tests for internal operator console loader/models."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.hitl.hitl_payload_builder import build_hitl_read_only_payload_from_replay_row
from app.operator_console.console_loader import (
    DEFAULT_OPERATOR_CONSOLE_DISPLAY_LIMIT_LABEL,
    apply_operator_console_display_limit,
    build_operator_tickets_from_rows,
    enrich_ai_assist_replay_row,
    filter_operator_tickets,
    load_operator_tickets,
    load_replay_rows,
    operator_tickets_from_hitl_payloads,
    parse_operator_console_display_limit,
)
from app.operator_console.console_models import (
    OperatorTicket,
    compute_console_metrics,
    ticket_row_display_label,
)
from app.operator_console.intent_display import (
    format_operational_intent_lines,
    operational_intent_fallback_message,
    ticket_has_operational_intent_data,
)
from app.operator_console.intent_enrichment import enrich_ai_assist_row_intent_fields


def _sample_row() -> dict[str, object]:
    return {
        "room_id": "ROOM_1",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "review_priority": "LOW",
        "assigned_department": "billing",
        "ai_assist_shadow_generated": True,
        "ai_assist_suggested_priority": "medium",
        "ai_assist_escalation_recommended": True,
        "ai_assist_duplicate_possible": False,
        "ai_assist_suggested_action": "billing_review",
        "ai_assist_confidence_band": "high",
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
        "errors": [],
    }


def test_load_replay_rows_and_build_tickets(tmp_path: Path) -> None:
    path = tmp_path / "replay.jsonl"
    path.write_text(json.dumps(_sample_row()) + "\n", encoding="utf-8")
    rows = load_replay_rows(path)
    tickets = build_operator_tickets_from_rows(rows)
    assert len(tickets) == 1
    assert tickets[0].room_id == "ROOM_1"
    assert tickets[0].suggested_action == "billing_review"


def test_ticket_row_display_label_starts_at_one() -> None:
    tickets = build_operator_tickets_from_rows(
        [_sample_row(), {**_sample_row(), "room_id": "ROOM_2"}]
    )
    assert ticket_row_display_label(1, tickets[0]) == "#1 — Ticket ROOM_1 · fund"
    assert ticket_row_display_label(2, tickets[1]) == "#2 — Ticket ROOM_2 · fund"


def test_filtered_ticket_row_numbering_is_sequential() -> None:
    rows = [
        _sample_row(),
        {**_sample_row(), "room_id": "ROOM_2", "ticket_label": "support"},
        {**_sample_row(), "room_id": "ROOM_3", "ticket_label": "fund"},
    ]
    tickets = build_operator_tickets_from_rows(rows)
    filtered = filter_operator_tickets(tickets, ticket_label="fund")
    labels = [ticket_row_display_label(index, ticket) for index, ticket in enumerate(filtered, 1)]
    assert labels == [
        "#1 — Ticket ROOM_1 · fund",
        "#2 — Ticket ROOM_3 · fund",
    ]


def test_filter_and_metrics() -> None:
    rows = [_sample_row(), {**_sample_row(), "room_id": "ROOM_2", "ticket_label": "support"}]
    tickets = build_operator_tickets_from_rows(rows)
    filtered = filter_operator_tickets(tickets, ticket_label="fund", escalation_only=True)
    assert len(filtered) == 1
    metrics = compute_console_metrics(filtered)
    assert metrics.total_tickets == 1
    assert metrics.escalation_count == 1
    assert metrics.action_distribution["billing_review"] == 1


def test_operator_ticket_includes_text_preview() -> None:
    row = _sample_row()
    row["ticket_text_preview"] = "Redacted seller preview text."
    tickets = build_operator_tickets_from_rows([row])
    assert tickets[0].ticket_text_preview == "Redacted seller preview text."


def test_enrich_replay_row_from_shadow_index() -> None:
    assist_row = {
        "room_id": "ROOM_1",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "review_priority": "LOW",
        "assigned_department": "billing",
        "ai_assist_shadow_generated": True,
        "ai_assist_suggested_priority": "low",
        "ai_assist_escalation_recommended": False,
        "ai_assist_duplicate_possible": True,
        "ai_assist_suggested_action": "billing_review",
        "ai_assist_confidence_band": "high",
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
        "errors": [],
    }
    index = {
        "ROOM_1": {
            "retrieval_gate_decision": "allow",
            "retrieval_result_count": 5,
            "retrieval_sandbox_only": True,
            "retrieval_activated": False,
        },
    }
    enriched = enrich_ai_assist_replay_row(assist_row, index)
    tickets = build_operator_tickets_from_rows([enriched])
    assert tickets[0].retrieval_gate_decision == "allow"
    assert tickets[0].retrieval_result_count == 5


def test_rejects_unsafe_replay_row() -> None:
    bad = {**_sample_row(), "user_input": "secret transcript"}
    with pytest.raises(ValueError, match="forbidden"):
        build_operator_tickets_from_rows([bad])


def test_loader_loads_more_than_twenty_five_rows(tmp_path: Path) -> None:
    path = tmp_path / "replay_many.jsonl"
    lines = []
    for index in range(30):
        row = _sample_row()
        row = {**row, "room_id": f"ROOM_{index}"}
        lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rows = load_replay_rows(path)
    tickets = build_operator_tickets_from_rows(
        rows,
        retrieval_index={},
        preview_index={},
        open_snapshot_index={},
    )
    assert len(rows) == 30
    assert len(tickets) == 30


def test_load_operator_tickets_not_truncated_by_default(tmp_path: Path) -> None:
    replay = tmp_path / "replay.jsonl"
    shadow = tmp_path / "shadow.jsonl"
    lines = []
    for index in range(32):
        row = _sample_row()
        row = {**row, "room_id": f"ROOM_{index}"}
        lines.append(json.dumps(row))
    replay.write_text("\n".join(lines) + "\n", encoding="utf-8")
    shadow.write_text("", encoding="utf-8")
    tickets = load_operator_tickets(
        replay,
        shadow_replay_path=shadow,
        redacted_tickets_path=None,
    )
    assert len(tickets) == 32


def test_display_limit_default_is_all() -> None:
    parsed = parse_operator_console_display_limit(
        DEFAULT_OPERATOR_CONSOLE_DISPLAY_LIMIT_LABEL,
    )
    assert parsed is None


def test_apply_display_limit_slices_tickets() -> None:
    rows = [{**_sample_row(), "room_id": f"ROOM_{index}"} for index in range(10)]
    tickets = build_operator_tickets_from_rows(rows)
    assert len(apply_operator_console_display_limit(tickets, limit=25)) == 10
    assert len(apply_operator_console_display_limit(tickets, limit=5)) == 5
    assert len(apply_operator_console_display_limit(tickets, limit=None)) == 10


def test_enrich_backfills_intent_from_preview_text() -> None:
    row = {
        **_sample_row(),
        "latest_vendor_message": "تسویه من واریز نشده",
        "ai_assist_shadow_generated": True,
    }
    enriched = enrich_ai_assist_row_intent_fields(row)
    assert enriched["detected_intent"] == "settlement_status_inquiry"
    assert enriched["intent_confidence_band"] in ("low", "medium", "high")
    assert enriched["intent_reasons_summary"]
    payload = build_hitl_read_only_payload_from_replay_row(enriched)
    assert payload["detected_intent"] == "settlement_status_inquiry"
    tickets = build_operator_tickets_from_rows([enrich_ai_assist_replay_row(row, {})])
    assert tickets[0].detected_intent == "settlement_status_inquiry"


def test_old_row_without_intent_does_not_crash() -> None:
    row = _sample_row()
    tickets = build_operator_tickets_from_rows([row])
    assert tickets[0].detected_intent is None
    assert not ticket_has_operational_intent_data(tickets[0])
    assert format_operational_intent_lines(tickets[0]) == []
    assert operational_intent_fallback_message()


def test_intent_display_lines() -> None:
    ticket = OperatorTicket.from_hitl_payload(
        {
            "room_id": "ROOM_X",
            "detected_intent": "tracking_code_notification",
            "intent_confidence_band": "high",
            "intent_reasons_summary": "tracking_code_present",
            "intent_related_document_types": "shipping_delivery_rules",
            "extracted_order_ids": "1234567,4567890",
            "extracted_tracking_code": "9876543210",
        },
    )
    lines = format_operational_intent_lines(ticket)
    joined = "\n".join(lines)
    assert "tracking_code_notification" in joined
    assert "9876543210" not in joined


def test_entity_display_lines() -> None:
    from app.operator_console.intent_display import (
        format_operational_entity_lines,
        ticket_has_operational_entity_data,
    )

    ticket = OperatorTicket.from_hitl_payload(
        {
            "room_id": "ROOM_ENT",
            "extracted_order_ids": "1234567",
            "extracted_product_ids": "87654321",
            "extracted_tracking_code": "1" * 24,
            "extracted_tracking_carrier": "iran_post",
            "entity_warnings_summary": "شماره سفارش ناقص احتمالی",
        },
    )
    assert ticket_has_operational_entity_data(ticket)
    joined = "\n".join(format_operational_entity_lines(ticket))
    assert "1234567" in joined
    assert "87654321" in joined
    assert "iran_post" in joined
    assert "شماره سفارش ناقص احتمالی" in joined


def test_live_payload_enrichment_preserves_intent_fields() -> None:
    payload = {
        "room_id": "ROOM_LIVE",
        "ticket_label": "fund",
        "ai_assist_shadow_generated": True,
        "ai_assist_suggested_action": "billing_review",
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_activated": False,
        "detected_intent": "settlement_status_inquiry",
        "intent_confidence_band": "medium",
        "latest_vendor_message": "تسویه",
    }
    tickets = operator_tickets_from_hitl_payloads([payload])
    assert tickets[0].detected_intent == "settlement_status_inquiry"
