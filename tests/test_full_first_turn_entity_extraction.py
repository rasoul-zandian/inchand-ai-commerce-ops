"""Step 203 — full first-turn vendor message for entity extraction only."""

from __future__ import annotations

import pytest
from app.config import AppSettings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import (
    analyze_first_turn_entity_leakage,
    assert_first_turn_entity_isolation,
    prompt_text_from_messages,
)
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_FULL_FIRST_VENDOR,
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    build_first_turn_draft_context_from_case,
    build_first_turn_draft_context_from_ticket,
    draft_entity_preview_fields,
    resolve_first_turn_text_sources_from_case,
    resolve_first_turn_text_sources_from_ticket,
)
from app.evals.offline_draft_generation import build_offline_draft_messages
from app.live_feed.open_ticket_snapshot import OPEN_TICKET_ORIGINAL_MAX_CHARS
from app.operator_console.agentic_sandbox_preview import _FORBIDDEN_PREVIEW_KEYS
from app.operator_console.console_loader import (
    DEFAULT_REDACTED_TICKETS_PATH,
    DEFAULT_REPLAY_PATH,
    attach_full_first_vendor_messages,
    load_full_first_vendor_message_index,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_preview import DraftPreviewRecord
from app.operator_console.intent_display import (
    extract_first_turn_display_entities,
    format_entity_extraction_lines,
)
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot
from app.workflows.entity_extraction_investigation import investigate_room_entity_extraction


def _truncated_preview(full_text: str) -> str:
    return full_text[:OPEN_TICKET_ORIGINAL_MAX_CHARS]


def _two_order_case() -> dict[str, object]:
    padding = "x" * 220
    full_text = f"سفارش INC-7452190 {padding} INC-7447698"
    preview = _truncated_preview(full_text)
    return {
        "room_id": "ROOM_TWO_ORDERS",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": preview,
            "full_first_vendor_message_text": full_text,
            "latest_vendor_message": "پیام بعدی INC-9999999",
        },
    }


def test_extraction_uses_full_first_message_when_preview_truncated() -> None:
    case = _two_order_case()
    sources = resolve_first_turn_text_sources_from_case(case)
    assert sources.entity_extraction_source == ENTITY_SOURCE_FULL_FIRST_VENDOR
    assert "7447698" not in sources.display_text
    assert "7447698" in sources.extraction_text
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert ctx.first_turn_entities.order_ids == ("7452190", "7447698")
    assert ctx.entity_extraction_source == ENTITY_SOURCE_FULL_FIRST_VENDOR


def test_full_first_source_not_in_draft_prompt() -> None:
    case = _two_order_case()
    full = str(case["snapshot_before_reply"]["full_first_vendor_message_text"])  # type: ignore[index]
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    messages = build_offline_draft_messages(
        case,
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=(),
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
        first_turn_context=ctx,
    )
    prompt = prompt_text_from_messages(messages)
    assert full not in prompt
    assert "INC-7447698" not in prompt or "7447698" in ctx.first_turn_text


def test_full_first_source_not_shown_in_entity_display_lines() -> None:
    case = _two_order_case()
    full = str(case["snapshot_before_reply"]["full_first_vendor_message_text"])  # type: ignore[index]
    ticket = OperatorTicket(
        room_id="ROOM_TWO_ORDERS",
        ticket_label="support",
        route_label="general_vendor_support",
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=str(
            case["snapshot_before_reply"]["original_vendor_issue_preview"],  # type: ignore[index]
        ),
        latest_vendor_message="later",
        recent_context_preview=None,
        full_first_vendor_message_text=full,
    )
    result = extract_first_turn_display_entities(ticket)
    sources = resolve_first_turn_text_sources_from_ticket(ticket)
    lines = format_entity_extraction_lines(
        result,
        entity_source=sources.entity_extraction_source,
        source_char_count=sources.entity_extraction_source_char_count,
        display_preview_char_count=sources.display_preview_char_count,
    )
    blob = "\n".join(lines)
    assert full not in blob
    assert ENTITY_SOURCE_FULL_FIRST_VENDOR in blob
    assert str(sources.entity_extraction_source_char_count) in blob


def test_entity_only_in_full_source_passes_leakage_guard() -> None:
    padding = "y" * 200
    full = f"سفارش INC-7452190 {padding} INC-7447698"
    preview = _truncated_preview(full)
    analysis = analyze_first_turn_entity_leakage(
        "بررسی سفارش 7447698",
        first_turn_text=preview,
        thread_texts=[],
        full_first_turn_text=full,
    )
    assert analysis["would_fail"] is False
    assert_first_turn_entity_isolation(
        "بررسی سفارش 7447698",
        first_turn_text=preview,
        thread_texts=[],
        full_first_turn_text=full,
    )


def test_later_message_only_entity_still_blocked() -> None:
    preview = "سفارش INC-7452190"
    full = preview
    latest = "پیگیری INC-9999999"
    with pytest.raises(ValueError, match="latest-only entity|9999999"):
        assert_first_turn_entity_isolation(
            "سفارش 9999999",
            first_turn_text=preview,
            thread_texts=[latest],
            full_first_turn_text=full,
        )


def test_draft_preview_fields_exclude_full_message_text() -> None:
    case = _two_order_case()
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    fields = draft_entity_preview_fields(ctx.first_turn_entities, context=ctx)
    full = str(case["snapshot_before_reply"]["full_first_vendor_message_text"])  # type: ignore[index]
    assert full not in fields.values()
    assert fields["entity_extraction_source"] == ENTITY_SOURCE_FULL_FIRST_VENDOR
    public = DraftPreviewRecord(
        room_id="ROOM_TWO_ORDERS",
        draft_reply="test",
        **{k: v for k, v in fields.items() if hasattr(DraftPreviewRecord, k)},
    ).to_public_dict()
    assert full not in str(public.values())


def test_agentic_preview_forbids_full_first_vendor_key() -> None:
    assert "full_first_vendor_message_text" in _FORBIDDEN_PREVIEW_KEYS


def test_attach_full_first_vendor_from_redacted(tmp_path) -> None:
    padding = "z" * 220
    full_text = f"INC-7452190 {padding} INC-7447698"
    snap = ConversationTicketSnapshot(
        room_id="ROOM_ATTACH",
        ticket_label="support",
        messages=[
            ConversationMessage(message_id="m1", sender_type="seller", text=full_text),
        ],
    )
    redacted = tmp_path / "redacted.jsonl"
    redacted.write_text(snap.model_dump_json() + "\n", encoding="utf-8")
    index = load_full_first_vendor_message_index(redacted)
    assert "ROOM_ATTACH" in index
    ticket = OperatorTicket(
        room_id="ROOM_ATTACH",
        ticket_label="support",
        route_label=None,
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=_truncated_preview(full_text),
        latest_vendor_message=None,
        recent_context_preview=None,
    )
    enriched = attach_full_first_vendor_messages([ticket], full_message_index=index)[0]
    ctx = build_first_turn_draft_context_from_ticket(
        enriched,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert ctx.entity_extraction_source == ENTITY_SOURCE_FULL_FIRST_VENDOR
    assert ctx.first_turn_entities.order_ids == ("7452190", "7447698")


@pytest.mark.skipif(
    not __import__("pathlib").Path("data/private/vendor_tickets_400.redacted.jsonl").is_file(),
    reason="redacted export required for room 43992 regression",
)
def test_room_43992_regression_two_order_ids() -> None:
    result = investigate_room_entity_extraction(
        "43992",
        replay_path=DEFAULT_REPLAY_PATH,
        redacted_path=DEFAULT_REDACTED_TICKETS_PATH,
    )
    assert result is not None
    orders = result.extracted_entities.get("order_ids") or []
    assert "7452190" in orders
    assert "7447698" in orders
    assert result.missing_entities == {}
    assert result.entity_source == ENTITY_SOURCE_FULL_FIRST_VENDOR
    assert result.likely_root_cause != "first_turn_isolation_gap"


def test_fallback_to_preview_when_full_missing() -> None:
    case = {
        "room_id": "ROOM_PREVIEW_ONLY",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": "INC-7452190 INC-7447698",
        },
    }
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert ctx.entity_extraction_source == ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    assert ctx.first_turn_entities.order_ids == ("7452190", "7447698")
