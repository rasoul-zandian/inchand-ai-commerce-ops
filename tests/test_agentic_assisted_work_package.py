"""Tests for simplified operator-assisted work package UI sections."""

from __future__ import annotations

from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.agentic_assisted_work_package import (
    build_assisted_work_package_debug_lines,
    build_assisted_work_package_main_sections,
    debug_section_markers,
    main_section_keys,
)
from app.operator_console.agentic_sandbox_preview import sanitize_agentic_preview_result
from app.operator_console.console_models import OperatorTicket
from app.operator_console.i18n import LANG_FA


def _graph():
    return sanitize_agentic_preview_result(
        {
            "room_id": "7743",
            "detected_intent": "settlement_status_inquiry",
            "conceptual_intent_fa": "پیگیری تسویه",
            "suggested_action": "check_settlement_status",
            "suggested_action_reason": "fund_route",
            "actionability": {
                "actionability_actionable": True,
                "actionability_missing_entities": None,
                "actionability_validation_reason": "ok",
            },
            "extracted_entities": {"order_ids": ["1234567"], "product_ids": []},
            "draft_reply": "تسویه سفارش‌ها پس از نهایی شدن فرآیند سفارش انجام می‌شود.",
            "safety_status": "passed",
            "human_review_required": True,
            "execution_allowed": False,
            "customer_send_allowed": False,
            "errors": [],
            "node_results": [
                {"node": "detect_intent", "status": "ok", "summary": "intent"},
            ],
        },
        knowledge_hints_enabled=True,
        llm_provider="mock",
    )


def _ticket() -> OperatorTicket:
    return OperatorTicket(
        room_id="7743",
        ticket_label="fund",
        route_label="billing_review",
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
        original_vendor_issue_preview="زمان تسویه چه زمانی است؟",
        latest_vendor_message=None,
        recent_context_preview=None,
    )


def test_main_sections_exclude_technical_blocks() -> None:
    package = AgenticAssistedPackage(
        room_id="7743",
        graph=_graph(),
        operator_checklist=("verify intent",),
        graduation_overall_status="ready_for_operator_assisted_phase",
        graduation_gate_passed=True,
    )
    main = build_assisted_work_package_main_sections(package, _ticket(), lang=LANG_FA)
    assert main_section_keys() == set(main.keys())
    joined = "\n".join(main.values())
    for marker in debug_section_markers():
        assert marker not in joined
    assert "detect_intent" not in joined
    assert "تسویه" in main["internal_draft"]


def test_debug_expander_includes_node_statuses() -> None:
    package = AgenticAssistedPackage(
        room_id="7743",
        graph=_graph(),
        operator_checklist=("verify intent",),
        graduation_overall_status=None,
        graduation_gate_passed=True,
    )
    debug = "\n".join(build_assisted_work_package_debug_lines(package, lang=LANG_FA))
    assert "`detect_intent`" in debug
    assert "knowledge_hint" in debug or "Graph status" in debug or "وضعیت گراف" in debug
