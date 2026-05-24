"""Step 179 — first-turn entity isolation for draft prompts."""

from __future__ import annotations

import pytest
from app.config import AppSettings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import (
    analyze_first_turn_entity_leakage,
    assert_first_turn_entity_isolation,
    assert_prompt_messages_safe,
    prompt_text_from_messages,
)
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_FULL_FIRST_VENDOR,
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    build_first_turn_draft_context_from_case,
    first_turn_text_from_case,
)
from app.evals.offline_draft_generation import build_offline_draft_messages
from app.llm.types import LLMResponse
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_preview import generate_draft_for_operator_ticket
from app.operator_console.knowledge_hints import build_knowledge_hint_query

_INITIAL_NO_ORDER = "تسویه اولیه فروشنده — بدون شماره سفارش"
_LATEST_WITH_ORDER = "لطفاً سفارش 1234567 را پیگیری کنید"
_ORDER_ID = "1234567"
_LATEST_ONLY = "آخرین پیام متفاوت"
_RECENT_ONLY = "support: پاسخ قبلی"


def _case(*, original: str, latest: str, recent: str = _RECENT_ONLY) -> dict[str, object]:
    return {
        "case_id": "ROOM_EI__first_vendor_turn",
        "room_id": "ROOM_EI",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": original,
            "latest_vendor_message": latest,
            "recent_context_preview": recent,
        },
    }


def test_first_turn_prompt_excludes_order_id_from_latest_message() -> None:
    case = _case(original=_INITIAL_NO_ORDER, latest=_LATEST_WITH_ORDER)
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert ctx.entity_source == ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    assert _ORDER_ID not in ctx.first_turn_entities.order_ids
    messages = build_offline_draft_messages(
        case,
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=ctx.first_turn_policy_hints,
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
        first_turn_context=ctx,
    )
    prompt = prompt_text_from_messages(messages)
    assert _INITIAL_NO_ORDER in prompt
    assert _LATEST_WITH_ORDER not in prompt
    assert _ORDER_ID not in prompt


def test_first_turn_prompt_includes_order_from_original_only() -> None:
    original = f"سفارش {_ORDER_ID} هنوز تسویه نشده"
    case = _case(original=original, latest="پیام بعدی بدون شماره")
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert _ORDER_ID in ctx.first_turn_entities.order_ids
    messages = build_offline_draft_messages(
        case,
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=(),
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
        first_turn_context=ctx,
    )
    prompt = prompt_text_from_messages(messages)
    assert _ORDER_ID in prompt


def test_entity_isolation_guard_raises_for_thread_only_order() -> None:
    case = _case(original=_INITIAL_NO_ORDER, latest=_LATEST_WITH_ORDER)
    with pytest.raises(ValueError, match="latest-only entity"):
        assert_first_turn_entity_isolation(
            f"شناسه سفارش {_ORDER_ID}",
            first_turn_text=first_turn_text_from_case(case),
            thread_texts=[_LATEST_WITH_ORDER],
        )


_COMPLAINT_ORIGINAL = (
    "سلام در مورد شکایت شماره 8201241 با ایشون تماس گرفتم و مشکل حل شد. "
    "قرار شد کرم بژ روشن براشون ارسال کنم که امروز ارسال شد. لطفا شکایت رو بردارید."
)
_LATEST_ORDER_8191925 = "سلام در مورد شکایت شماره 8191925 ، بسته ی ارسالی مرجوع شده بود"


def test_room_7743_style_first_turn_extracts_complaint_order_id() -> None:
    case = {
        "case_id": "7743__first_vendor_turn",
        "room_id": "7743",
        "snapshot_before_reply": {"original_vendor_issue_preview": _COMPLAINT_ORIGINAL},
    }
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert ctx.first_turn_entities.order_ids == ("8201241",)


def test_room_7536_style_first_turn_extracts_order_without_safaresh_keyword() -> None:
    """Regression: 7-digit in original without order keyword → first-turn order_ids."""
    original = "مشکل تسویه برای 8246738 هنوز حل نشده"
    case = {
        "case_id": "7536__first_vendor_turn",
        "room_id": "7536",
        "snapshot_before_reply": {"original_vendor_issue_preview": original},
    }
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert ctx.first_turn_entities.order_ids == ("8246738",)


def test_room_7743_style_prompt_allows_original_complaint_number() -> None:
    """8201241 in original must not fail when open_ticket re-extracts it from thread preview."""
    case = {
        "case_id": "7743__first_vendor_turn",
        "room_id": "7743",
        "ticket_label": "complaint",
        "route_label": "general_vendor_support",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": _COMPLAINT_ORIGINAL,
            "latest_vendor_message": _LATEST_ORDER_8191925,
        },
        "open_ticket_preview": (
            "Original: " + _COMPLAINT_ORIGINAL + " | Latest: " + _LATEST_ORDER_8191925
        ),
    }
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
    assert "8201241" in prompt
    assert "8191925" not in prompt
    assert_prompt_messages_safe(
        messages,
        forbidden_values=[],
        first_turn_text=_COMPLAINT_ORIGINAL,
        thread_texts=[
            _LATEST_ORDER_8191925,
            str(case.get("open_ticket_preview") or ""),
        ],
    )


def test_true_leakage_includes_diagnostics() -> None:
    from app.evals.draft_prompt_leakage import analyze_first_turn_entity_leakage

    original = "سلام لطفا بررسی کنید"
    latest = "سفارش 8191925"
    analysis = analyze_first_turn_entity_leakage(
        "شناسه سفارش 8191925",
        first_turn_text=original,
        thread_texts=[latest],
    )
    assert analysis["would_fail"] is True
    assert "8191925" in analysis["prompt_contains_forbidden_later_only_values"]
    with pytest.raises(ValueError, match="8191925"):
        assert_first_turn_entity_isolation(
            "شناسه سفارش 8191925",
            first_turn_text=original,
            thread_texts=[latest],
        )


def test_knowledge_hint_query_uses_original_only_in_first_turn_mode() -> None:
    ticket = OperatorTicket(
        room_id="ROOM_KH",
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
        original_vendor_issue_preview=_INITIAL_NO_ORDER,
        latest_vendor_message=_LATEST_WITH_ORDER,
        recent_context_preview=_RECENT_ONLY,
    )
    query = build_knowledge_hint_query(ticket, first_turn_only=True)
    assert _INITIAL_NO_ORDER in query
    assert _LATEST_WITH_ORDER not in query
    assert _RECENT_ONLY not in query


def test_operator_regenerate_ignores_ticket_thread_entities() -> None:
    settings = AppSettings(
        operator_draft_generation_enabled=True,
        knowledge_hints_enabled=False,
        draft_generation_mode="first_turn_only",
    )
    ticket = OperatorTicket(
        room_id="ROOM_OP_EI",
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
        original_vendor_issue_preview=_INITIAL_NO_ORDER,
        latest_vendor_message=_LATEST_WITH_ORDER,
        recent_context_preview=_RECENT_ONLY,
        extracted_order_ids=_ORDER_ID,
        extracted_order_id=_ORDER_ID,
    )

    captured: list[str] = []

    def _mock_generate(messages, *, provider: str, model: str) -> LLMResponse:
        prompt = "\n".join(m.content for m in messages)
        captured.append(prompt)
        assert _ORDER_ID not in prompt
        return LLMResponse(
            content=(
                '{"conceptual_intent_fa": "پیگیری تسویه", '
                '"draft_reply": "برای بررسی به تیم مربوطه ارجاع شد."}'
            ),
            provider=provider,
            model=model,
            metadata={},
        )

    record = generate_draft_for_operator_ticket(
        ticket,
        settings=settings,
        generate_fn=_mock_generate,
    )
    assert record.entity_source == ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    assert captured


def test_entity_in_full_first_source_only_allowed_for_isolation() -> None:
    padding = "a" * 200
    full = f"سفارش INC-7452190 {padding} INC-7447698"
    preview = full[:200]
    case = {
        "room_id": "ROOM_FULL_ONLY",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": preview,
            "full_first_vendor_message_text": full,
        },
    }
    ctx = build_first_turn_draft_context_from_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
    )
    assert ctx.entity_extraction_source == ENTITY_SOURCE_FULL_FIRST_VENDOR
    assert "7447698" in ctx.first_turn_entities.order_ids
    analysis = analyze_first_turn_entity_leakage(
        "پیگیری 7447698",
        first_turn_text=preview,
        thread_texts=[],
        full_first_turn_text=full,
    )
    assert analysis["would_fail"] is False
    leak_rows = analysis.get("leak_diagnostics") or []
    if leak_rows:
        assert leak_rows[0].get("allowed_by_full_first_turn_source") is not True
