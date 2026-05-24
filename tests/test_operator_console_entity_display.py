"""Operator console entity display — first-turn vs open snapshot sources."""

from __future__ import annotations

from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.first_turn_draft_context import ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
from app.operator_console.console_models import OperatorTicket
from app.operator_console.intent_display import (
    extract_first_turn_display_entities,
    format_first_turn_entity_lines,
    format_open_snapshot_entity_lines,
    use_first_turn_entity_display,
)

_INITIAL_NO_ORDER = (
    "سلام در مورد شکایت شماره 8201241 با ایشون تماس گرفتم و مشکل حل شد. "
    "قرار شد کرم بژ روشن براشون ارسال کنم که امروز ارسال شد. لطفا شکایت رو بردارید."
)
_LATEST_ONLY_ORDER = "سفارش 8191925 مشتری تو سایت شماره تلفن درست نیست"
_ORDER_IN_ORIGINAL = "1234567"


def _ticket(
    *,
    original: str,
    latest: str | None = None,
    extracted_order_ids: str | None = None,
) -> OperatorTicket:
    return OperatorTicket(
        room_id="7743",
        ticket_label="complaint",
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
        original_vendor_issue_preview=original,
        latest_vendor_message=latest if latest is not None else original,
        recent_context_preview=None,
        extracted_order_ids=extracted_order_ids,
        extracted_order_id=extracted_order_ids,
    )


def test_first_turn_display_excludes_latest_only_order_id() -> None:
    ticket = _ticket(
        original=_INITIAL_NO_ORDER,
        latest=_LATEST_ONLY_ORDER,
        extracted_order_ids="8191925",
    )
    result = extract_first_turn_display_entities(ticket)
    assert "8191925" not in result.order_ids
    lines = format_first_turn_entity_lines(ticket)
    joined = "\n".join(lines)
    assert "8191925" not in joined
    assert ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE in joined


def test_ticket_7743_style_latest_only_order_not_in_first_turn_display() -> None:
    ticket = _ticket(
        original=_INITIAL_NO_ORDER,
        latest=_LATEST_ONLY_ORDER,
        extracted_order_ids="8191925",
    )
    assert "8191925" in "\n".join(format_open_snapshot_entity_lines(ticket))
    assert "8191925" not in "\n".join(format_first_turn_entity_lines(ticket))


def test_first_turn_display_includes_order_from_original() -> None:
    original = f"سفارش {_ORDER_IN_ORIGINAL} هنوز تسویه نشده"
    ticket = _ticket(original=original, latest="پیام بعدی", extracted_order_ids="9999999")
    result = extract_first_turn_display_entities(ticket)
    assert _ORDER_IN_ORIGINAL in result.order_ids
    assert _ORDER_IN_ORIGINAL in "\n".join(format_first_turn_entity_lines(ticket))


def test_use_first_turn_entity_display_mode_gate() -> None:
    assert use_first_turn_entity_display(draft_generation_mode=DraftGenerationMode.FIRST_TURN_ONLY)
    assert use_first_turn_entity_display(draft_generation_mode="first_turn_only")
    assert not use_first_turn_entity_display(
        draft_generation_mode=DraftGenerationMode.LIVE_THREAD_CONTEXT
    )


def test_open_snapshot_lines_still_use_ticket_globals() -> None:
    ticket = _ticket(
        original=_INITIAL_NO_ORDER,
        latest=_LATEST_ONLY_ORDER,
        extracted_order_ids="8191925",
    )
    open_lines = format_open_snapshot_entity_lines(ticket)
    assert "8191925" in "\n".join(open_lines)
    assert "open_snapshot_ai_assist" in "\n".join(open_lines)
