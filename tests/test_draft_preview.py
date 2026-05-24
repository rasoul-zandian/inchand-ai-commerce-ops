"""Tests for operator-console internal draft preview and session regeneration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import AppSettings
from app.evals.offline_draft_generation import (
    assert_prompt_excludes_gold_reference,
    build_offline_draft_messages,
)
from app.llm.types import LLMMessage, LLMResponse
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_preview import (
    SESSION_DRAFT_OVERRIDES_KEY,
    assert_draft_preview_record_safe,
    build_draft_preview_record,
    find_draft_for_room_or_case,
    generate_draft_for_operator_ticket,
    get_session_draft_overrides,
    load_draft_preview_for_ticket,
    load_offline_draft_suggestions,
    store_session_draft,
)


def _offline_row(*, room_id: str = "ROOM_A", case_id: str | None = None) -> dict[str, object]:
    return {
        "room_id": room_id,
        "case_id": case_id or f"{room_id}__first_vendor_turn",
        "draft_reply": "سلام — پیش‌نویس داخلی برای بررسی اپراتور.",
        "detected_intent": "settlement_status_inquiry",
        "suggested_action": "billing_review",
        "knowledge_hint_document_types": ["settlement_rules"],
        "draft_generated": True,
        "llm_model": "gpt-4o-mini",
        "llm_provider": "openai",
        "generated_at_utc": "2026-05-20T12:00:00+00:00",
    }


def _operator_ticket(*, room_id: str = "ROOM_A") -> OperatorTicket:
    return OperatorTicket(
        room_id=room_id,
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
        original_vendor_issue_preview="تسویه من واریز نشده",
        latest_vendor_message="لطفاً وضعیت را بگویید",
        recent_context_preview="vendor: تسویه",
    )


def test_load_offline_draft_by_room_and_case_id(tmp_path: Path) -> None:
    path = tmp_path / "drafts.jsonl"
    path.write_text(
        json.dumps(_offline_row(room_id="ROOM_A"))
        + "\n"
        + json.dumps(_offline_row(room_id="ROOM_B", case_id="ROOM_B__other"))
        + "\n",
        encoding="utf-8",
    )
    by_room, by_case = load_offline_draft_suggestions(path)
    assert "ROOM_A" in by_room
    assert "ROOM_A__first_vendor_turn" in by_case
    found = find_draft_for_room_or_case("ROOM_A", by_room=by_room, by_case=by_case)
    assert found is not None
    assert found["draft_reply"].startswith("سلام")


def test_find_draft_prefers_explicit_case_id(tmp_path: Path) -> None:
    by_room = {"ROOM_A": _offline_row(room_id="ROOM_A")}
    by_case = {
        "ROOM_A__first_vendor_turn": _offline_row(room_id="ROOM_A"),
        "ROOM_A__custom": {**_offline_row(room_id="ROOM_A"), "draft_reply": "پیش‌نویس سفارشی"},
    }
    found = find_draft_for_room_or_case(
        "ROOM_A",
        by_room=by_room,
        by_case=by_case,
        case_id="ROOM_A__custom",
    )
    assert found is not None
    assert found["draft_reply"] == "پیش‌نویس سفارشی"


def test_draft_preview_record_excludes_forbidden_fields() -> None:
    record = build_draft_preview_record(_offline_row())
    assert record is not None
    public = record.to_public_dict()
    assert "gold_reference_reply" not in public
    assert_draft_preview_record_safe(public)
    with pytest.raises(ValueError, match="forbidden keys"):
        assert_draft_preview_record_safe({**public, "messages": []})


def test_generation_disabled_by_default() -> None:
    settings = AppSettings(operator_draft_generation_enabled=False)
    with pytest.raises(ValueError, match="disabled"):
        generate_draft_for_operator_ticket(_operator_ticket(), settings=settings)


def _mock_generate(messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
    combined = "\n".join(m.content for m in messages)
    assert "gold_reference_reply" not in combined.lower()
    assert "تسویه" in combined or "واریز" in combined
    return LLMResponse(
        content="سلام — واحد مالی در حال بررسی درخواست تسویه شماست.",
        provider=provider,
        model=model,
        metadata={},
    )


def test_generation_uses_safe_fields_only() -> None:
    settings = AppSettings(
        operator_draft_generation_enabled=True,
        knowledge_hints_enabled=False,
        operator_draft_model="gpt-4o-mini",
        operator_draft_max_chars=700,
    )
    ticket = _operator_ticket()
    record = generate_draft_for_operator_ticket(
        ticket,
        settings=settings,
        generate_fn=_mock_generate,
    )
    assert record.draft_generated is True
    assert record.source == "session_regenerate"
    assert record.detected_intent
    assert "سلام" in record.draft_reply


def test_generation_prompt_excludes_gold() -> None:
    from app.workflows.seller_notification_detection import normalize_persian_arabic_digits
    from app.workflows.vendor_ticket_ai_assist_shadow import _suggested_action_for_intent
    from app.workflows.vendor_ticket_intent_detection import detect_vendor_ticket_intent

    ticket = _operator_ticket()
    source = " ".join(
        part
        for part in (
            ticket.original_vendor_issue_preview,
            ticket.latest_vendor_message,
            ticket.recent_context_preview,
        )
        if part
    )
    intent_result = detect_vendor_ticket_intent(
        source,
        ticket_label=ticket.ticket_label,
        route_label=ticket.route_label,
    )
    normalized = normalize_persian_arabic_digits(source)
    suggested = _suggested_action_for_intent(
        intent_result.intent,
        normalized_text=normalized,
    ).value
    case = {
        "ticket_label": ticket.ticket_label,
        "route_label": ticket.route_label,
        "snapshot_before_reply": {
            "original_vendor_issue_preview": ticket.original_vendor_issue_preview,
            "latest_vendor_message": ticket.latest_vendor_message,
            "recent_context_preview": ticket.recent_context_preview,
        },
    }
    messages = build_offline_draft_messages(
        case,
        intent_result=intent_result,
        suggested_action=suggested,
        policy_hints=[],
    )
    assert_prompt_excludes_gold_reference(
        messages,
        "سلام — این پاسخ مرجع طلایی است که نباید در پرامپت باشد.",
    )


def test_unsafe_draft_rejected_on_generation() -> None:
    settings = AppSettings(operator_draft_generation_enabled=True)

    def _unsafe_generate(
        _messages: list[LLMMessage],
        *,
        provider: str,
        model: str,
    ) -> LLMResponse:
        return LLMResponse(
            content="ارسال خودکار به فروشنده انجام شد.",
            provider=provider,
            model=model,
            metadata={},
        )

    with pytest.raises(ValueError, match="auto-send"):
        generate_draft_for_operator_ticket(
            _operator_ticket(),
            settings=settings,
            generate_fn=_unsafe_generate,
        )


def test_preview_displays_conceptual_intent_when_present() -> None:
    row = _offline_row()
    row["conceptual_intent_fa"] = "درخواست ویرایش کالا"
    record = build_draft_preview_record(row)
    assert record is not None
    assert record.conceptual_intent_fa == "درخواست ویرایش کالا"


def test_session_only_override_wins_over_offline(tmp_path: Path) -> None:
    path = tmp_path / "drafts.jsonl"
    path.write_text(json.dumps(_offline_row()) + "\n", encoding="utf-8")
    session: dict[str, object] = {}
    offline_record = build_draft_preview_record(_offline_row())
    assert offline_record is not None
    session_record = offline_record.__class__(
        room_id=offline_record.room_id,
        draft_reply="پیش‌نویس جلسه",
        detected_intent=offline_record.detected_intent,
        suggested_action=offline_record.suggested_action,
        source="session_regenerate",
        draft_generated=True,
    )
    store_session_draft(session, session_record)
    overrides = get_session_draft_overrides(session)
    loaded = load_draft_preview_for_ticket(
        _operator_ticket(),
        suggestions_path=path,
        session_overrides=overrides,
        load_offline=True,
    )
    assert loaded is not None
    assert loaded.draft_reply == "پیش‌نویس جلسه"
    assert loaded.source == "session_regenerate"
    assert SESSION_DRAFT_OVERRIDES_KEY in session
