"""Tests for first-turn-only draft prompt isolation (Step 175)."""

from __future__ import annotations

import pytest
from app.config import AppSettings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import (
    assert_no_prompt_leakage,
    build_prompt_audit_record,
    extract_forbidden_values_from_benchmark_case,
    list_excluded_prompt_fields,
    list_included_prompt_fields,
    prompt_text_from_messages,
)
from app.evals.offline_draft_generation import (
    build_offline_draft_messages,
    resolve_draft_generation_mode,
)
from app.llm.types import LLMResponse
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_preview import generate_draft_for_operator_ticket
from app.workflows.vendor_ticket_intent_detection import detect_vendor_ticket_intent

_INITIAL_ISSUE = "تسویه اولیه فروشنده — فقط موضوع اول"
_LATEST_ONLY = "آخرین پیام متفاوت که نباید در پرامپت باشد"
_RECENT_ONLY = "support: پاسخ قبلی که نباید در پرامپت باشد"
_OPEN_PREVIEW = "open ticket preview sentinel 88102"


def _first_turn_case() -> dict[str, object]:
    return {
        "case_id": "ROOM_FT__first_vendor_turn",
        "room_id": "ROOM_FT",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": _INITIAL_ISSUE,
            "latest_vendor_message": _LATEST_ONLY,
            "recent_context_preview": _RECENT_ONLY,
        },
        "gold_reference_reply": "gold sentinel must not leak",
        "open_ticket_preview": _OPEN_PREVIEW,
    }


def _intent(case: dict[str, object]):
    return detect_vendor_ticket_intent(
        _INITIAL_ISSUE,
        ticket_label=str(case.get("ticket_label")),
        route_label=str(case.get("route_label")),
    )


def test_first_turn_prompt_contains_original_issue_only() -> None:
    case = _first_turn_case()
    messages = build_offline_draft_messages(
        case,
        intent_result=_intent(case),
        suggested_action="billing_review",
        policy_hints=[],
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
    )
    prompt = prompt_text_from_messages(messages)
    assert _INITIAL_ISSUE in prompt
    assert "موضوع اولیه" in prompt or "درخواست اولیه" in prompt


def test_first_turn_prompt_excludes_latest_vendor_message() -> None:
    case = _first_turn_case()
    messages = build_offline_draft_messages(
        case,
        intent_result=_intent(case),
        suggested_action="billing_review",
        policy_hints=[],
    )
    prompt = prompt_text_from_messages(messages)
    assert _LATEST_ONLY not in prompt
    assert "آخرین پیام فروشنده" not in prompt


def test_first_turn_prompt_excludes_recent_context_preview() -> None:
    case = _first_turn_case()
    messages = build_offline_draft_messages(
        case,
        intent_result=_intent(case),
        suggested_action="billing_review",
        policy_hints=[],
    )
    prompt = prompt_text_from_messages(messages)
    assert _RECENT_ONLY not in prompt
    assert "زمینه اخیر" not in prompt


def test_first_turn_prompt_excludes_open_ticket_preview() -> None:
    case = _first_turn_case()
    messages = build_offline_draft_messages(
        case,
        intent_result=_intent(case),
        suggested_action="billing_review",
        policy_hints=[],
    )
    prompt = prompt_text_from_messages(messages)
    assert _OPEN_PREVIEW not in prompt


def test_leakage_guard_fails_if_latest_vendor_message_injected() -> None:
    case = _first_turn_case()
    forbidden = extract_forbidden_values_from_benchmark_case(
        case,
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
    )
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_prompt_leakage(
            f"متن: {_INITIAL_ISSUE} و ادامه: {_LATEST_ONLY}",
            forbidden,
            mode=DraftGenerationMode.FIRST_TURN_ONLY,
        )


def test_operator_regenerate_uses_isolated_prompt() -> None:
    settings = AppSettings(
        operator_draft_generation_enabled=True,
        knowledge_hints_enabled=False,
        draft_generation_mode="first_turn_only",
    )
    ticket = OperatorTicket(
        room_id="ROOM_OP_FT",
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
        ticket_text_preview=_OPEN_PREVIEW,
        open_ticket_preview=_OPEN_PREVIEW,
        original_vendor_issue_preview=_INITIAL_ISSUE,
        latest_vendor_message=_LATEST_ONLY,
        recent_context_preview=_RECENT_ONLY,
    )

    captured: list[str] = []

    def _mock_generate(messages, *, provider: str, model: str) -> LLMResponse:
        prompt = "\n".join(m.content for m in messages)
        captured.append(prompt)
        assert _INITIAL_ISSUE in prompt
        assert _LATEST_ONLY not in prompt
        assert _RECENT_ONLY not in prompt
        assert _OPEN_PREVIEW not in prompt
        return LLMResponse(
            content="سلام — پیش‌نویس اولین پاسخ.",
            provider=provider,
            model=model,
            metadata={},
        )

    record = generate_draft_for_operator_ticket(
        ticket,
        settings=settings,
        generate_fn=_mock_generate,
    )
    assert record.draft_generated is True
    assert captured


def test_audit_metadata_matches_first_turn_fields() -> None:
    case = _first_turn_case()
    intent = _intent(case)
    messages = build_offline_draft_messages(
        case,
        intent_result=intent,
        suggested_action="billing_review",
        policy_hints=[],
    )
    included = list_included_prompt_fields(
        case,
        intent_result=intent,
        suggested_action="billing_review",
        policy_hints=[],
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
    )
    audit = build_prompt_audit_record(
        case_id=str(case["case_id"]),
        messages=messages,
        included_fields=included,
        case=case,
        mode=DraftGenerationMode.FIRST_TURN_ONLY,
    )
    assert audit["draft_generation_mode"] == "first_turn_only"
    assert "snapshot_before_reply.original_vendor_issue_preview" in included
    assert "detected_intent" in included
    assert "suggested_action" in included
    excluded = audit["excluded_fields"]
    assert "snapshot_before_reply.latest_vendor_message" in excluded
    assert "snapshot_before_reply.recent_context_preview" in excluded
    assert "open_ticket_preview" in excluded
    assert audit["leakage_check_passed"] is True


def test_default_config_is_first_turn_only() -> None:
    assert resolve_draft_generation_mode(AppSettings()) == DraftGenerationMode.FIRST_TURN_ONLY
    assert list_excluded_prompt_fields(DraftGenerationMode.FIRST_TURN_ONLY)
