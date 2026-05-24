"""Tests for deterministic Persian domain query normalization."""

from __future__ import annotations

from app.knowledge.domain_query_normalization import (
    build_domain_query_expansions,
    normalize_persian_support_query,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import (
    assert_query_built_from_safe_ticket_fields,
    build_knowledge_hint_query,
)


def test_tasfiye_panel_normalizes_to_settlement_vendor_account() -> None:
    assert normalize_persian_support_query("تصفیه پنل") == "تسویه حساب فروشنده"


def test_polam_nayoomade_expands_to_settlement_status() -> None:
    normalized = normalize_persian_support_query("پولم نیومده")
    assert normalized == "وضعیت تسویه فروشنده"
    assert build_domain_query_expansions(normalized) == ["تسویه حساب فروشنده"]


def test_non_finance_text_unchanged() -> None:
    text = "سلام، لطفاً وضعیت شکایت مشتری را بررسی کنید."
    assert normalize_persian_support_query(text) == text
    assert build_domain_query_expansions(text) == []


def test_knowledge_hint_query_includes_normalized_phrase() -> None:
    ticket = OperatorTicket(
        room_id="ROOM_SETTLE",
        ticket_label="fund",
        route_label="billing_review",
        assigned_department="finance",
        review_priority="LOW",
        suggested_action="billing_review",
        suggested_priority="medium",
        escalation_recommended=False,
        duplicate_possible=False,
        confidence_band="high",
        retrieval_gate_decision="allow",
        retrieval_result_count=3,
        ticket_text_preview="must not appear",
        open_ticket_preview="must not appear",
        original_vendor_issue_preview=("سلام وقت بخیر، قسمت تصفیه پنل هنوز بسته هستش، باز کنید"),
        latest_vendor_message=None,
        recent_context_preview=None,
    )
    query = build_knowledge_hint_query(ticket)
    assert "بخش تسویه حساب" in query or "تسویه حساب فروشنده" in query
    assert "تصفیه" not in query
    assert "| intent:" in query
    assert "تسویه حساب فروشنده" in query
    assert "| boost:" in query
    assert_query_built_from_safe_ticket_fields(ticket, query)
