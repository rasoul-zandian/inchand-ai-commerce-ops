"""Tests for draft prompt leakage guards (gold/future replies must not enter prompts)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.config import AppSettings
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import (
    assert_audit_record_safe,
    assert_no_prompt_leakage,
    assert_prompt_messages_safe,
    build_prompt_audit_record,
    extract_forbidden_values_from_benchmark_case,
    extract_forbidden_values_from_operator_ticket,
    list_included_prompt_fields,
    prompt_text_from_messages,
    safe_snapshot_before_reply,
)
from app.evals.first_turn_draft_context import build_first_turn_draft_context_from_case
from app.evals.offline_draft_generation import (
    build_offline_draft_messages,
    generate_offline_draft_suggestions,
    process_benchmark_case,
)
from app.llm.types import LLMResponse
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_preview import generate_draft_for_operator_ticket
from app.workflows.vendor_ticket_intent_detection import detect_vendor_ticket_intent

_GOLD_SENTINEL = "__GOLD_SENTINEL_DO_NOT_LEAK_77421__"
_FUTURE_SUPPORT_SENTINEL = "__FUTURE_SUPPORT_SENTINEL_DO_NOT_LEAK_99102__"
_COMPLAINT_ORIGINAL = (
    "سلام در مورد شکایت شماره 8201241 با ایشون تماس گرفتم و مشکل حل شد. "
    "قرار شد کرم بژ روشن براشون ارسال کنم که امروز ارسال شد. لطفا شکایت رو بردارید."
)
_COMPLAINT_ID = "8201241"


def _base_case() -> dict[str, object]:
    return {
        "case_id": "ROOM_LEAK__first_vendor_turn",
        "room_id": "ROOM_LEAK",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": "تسویه من واریز نشده",
            "latest_vendor_message": "لطفاً وضعیت را بگویید",
            "recent_context_preview": "vendor: تسویه",
        },
        "gold_reference_reply": _GOLD_SENTINEL,
        "responder_role": "support_agent",
    }


def _intent_for_case(case: dict[str, object]):
    snap = case["snapshot_before_reply"]
    assert isinstance(snap, dict)
    text = " ".join(
        str(snap.get(key) or "")
        for key in (
            "original_vendor_issue_preview",
            "latest_vendor_message",
            "recent_context_preview",
        )
    )
    return detect_vendor_ticket_intent(
        text,
        ticket_label=str(case.get("ticket_label")),
        route_label=str(case.get("route_label")),
    )


def test_prompt_excludes_gold_sentinel() -> None:
    case = _base_case()
    intent = _intent_for_case(case)
    messages = build_offline_draft_messages(
        case,
        intent_result=intent,
        suggested_action="billing_review",
        policy_hints=[],
    )
    prompt = prompt_text_from_messages(messages)
    assert _GOLD_SENTINEL not in prompt


def test_prompt_excludes_future_support_reply_top_level() -> None:
    case = _base_case()
    case["future_support_reply"] = _FUTURE_SUPPORT_SENTINEL
    intent = _intent_for_case(case)
    messages = build_offline_draft_messages(
        case,
        intent_result=intent,
        suggested_action="billing_review",
        policy_hints=[],
    )
    prompt = prompt_text_from_messages(messages)
    assert _FUTURE_SUPPORT_SENTINEL not in prompt


def test_prompt_ignores_extra_snapshot_and_messages_fields() -> None:
    case = _base_case()
    snap = case["snapshot_before_reply"]
    assert isinstance(snap, dict)
    snap["future_support_reply"] = _FUTURE_SUPPORT_SENTINEL
    case["messages"] = [
        {"sender_type": "support_agent", "text": _FUTURE_SUPPORT_SENTINEL},
    ]
    case["final_response"] = _FUTURE_SUPPORT_SENTINEL
    intent = _intent_for_case(case)
    messages = build_offline_draft_messages(
        case,
        intent_result=intent,
        suggested_action="billing_review",
        policy_hints=[],
    )
    prompt = prompt_text_from_messages(messages)
    assert _FUTURE_SUPPORT_SENTINEL not in prompt
    assert _GOLD_SENTINEL not in prompt


def test_safe_snapshot_strips_non_allowlisted_keys() -> None:
    snap = safe_snapshot_before_reply(
        {
            "original_vendor_issue_preview": "vendor only",
            "future_support_reply": _FUTURE_SUPPORT_SENTINEL,
        },
    )
    assert snap["original_vendor_issue_preview"] == "vendor only"
    assert "future_support_reply" not in snap


def test_included_fields_allowlist_only() -> None:
    case = _base_case()
    intent = _intent_for_case(case)
    fields = list_included_prompt_fields(
        case,
        intent_result=intent,
        suggested_action="billing_review",
        policy_hints=[],
    )
    assert "snapshot_before_reply.original_vendor_issue_preview" in fields
    assert "snapshot_before_reply.latest_vendor_message" not in fields
    assert "snapshot_before_reply.recent_context_preview" not in fields
    assert "detected_intent" in fields
    assert "suggested_action" in fields
    assert not any("gold" in field for field in fields)


def test_prompt_audit_record_metadata_only(tmp_path: Path) -> None:
    case = _base_case()
    intent = _intent_for_case(case)
    messages = build_offline_draft_messages(
        case,
        intent_result=intent,
        suggested_action="billing_review",
        policy_hints=[],
    )
    audit = build_prompt_audit_record(
        case_id=str(case["case_id"]),
        messages=messages,
        included_fields=list_included_prompt_fields(
            case,
            intent_result=intent,
            suggested_action="billing_review",
            policy_hints=[],
        ),
        case=case,
    )
    assert audit["draft_generation_mode"] == "first_turn_only"
    assert audit["contains_gold_reference"] is False
    assert audit["contains_forbidden_markers"] is False
    assert audit["leakage_check_passed"] is True
    assert "excluded_fields" in audit
    assert "prompt" not in audit
    assert _GOLD_SENTINEL not in json.dumps(audit)
    assert_audit_record_safe(audit)


def test_assert_no_prompt_leakage_rejects_sentinel() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_prompt_leakage(f"prefix {_GOLD_SENTINEL} suffix", [_GOLD_SENTINEL])


def test_first_turn_original_allowed_when_latest_matches() -> None:
    """Regression for room 7743 — identical latest must not forbid original in prompt."""
    case = {
        "case_id": "ROOM_7743__first_vendor_turn",
        "room_id": "7743",
        "ticket_label": "complaint",
        "route_label": "general_vendor_support",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": _COMPLAINT_ORIGINAL,
            "latest_vendor_message": _COMPLAINT_ORIGINAL,
            "recent_context_preview": "vendor: follow-up",
        },
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
    forbidden = extract_forbidden_values_from_benchmark_case(case)
    assert _COMPLAINT_ORIGINAL not in forbidden
    assert_prompt_messages_safe(
        messages,
        forbidden_values=forbidden,
        first_turn_text=_COMPLAINT_ORIGINAL,
    )
    prompt = prompt_text_from_messages(messages)
    assert _COMPLAINT_ID in prompt


def test_latest_only_complaint_id_still_blocked() -> None:
    original = "سلام لطفا شکایت را بررسی کنید."
    latest = f"شکایت شماره {_COMPLAINT_ID} هنوز باز است"
    case = {
        "case_id": "ROOM_LEAK_ID__first_vendor_turn",
        "room_id": "ROOM_LEAK_ID",
        "ticket_label": "complaint",
        "snapshot_before_reply": {
            "original_vendor_issue_preview": original,
            "latest_vendor_message": latest,
        },
    }
    forbidden = extract_forbidden_values_from_benchmark_case(case)
    assert latest in forbidden
    prompt = f"متن درخواست:\n{original}\n{latest}"
    with pytest.raises(ValueError, match="forbidden"):
        assert_no_prompt_leakage(
            prompt,
            forbidden,
            allowed_values=[original],
        )


def test_allowed_values_exempts_prefix_from_original() -> None:
    prompt = f"متن درخواست:\n{_COMPLAINT_ORIGINAL}"
    forbidden = [_COMPLAINT_ORIGINAL]
    assert_no_prompt_leakage(
        prompt,
        forbidden,
        allowed_values=[_COMPLAINT_ORIGINAL],
    )


def test_operator_ticket_same_latest_not_forbidden() -> None:
    ticket = OperatorTicket(
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
        original_vendor_issue_preview=_COMPLAINT_ORIGINAL,
        latest_vendor_message=_COMPLAINT_ORIGINAL,
        recent_context_preview=None,
    )
    forbidden = extract_forbidden_values_from_operator_ticket(ticket)
    assert _COMPLAINT_ORIGINAL not in forbidden


def test_operator_regenerate_prompt_excludes_reference_fields() -> None:
    settings = AppSettings(
        operator_draft_generation_enabled=True,
        knowledge_hints_enabled=False,
    )
    ticket = OperatorTicket(
        room_id="ROOM_OP",
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
        ticket_text_preview=_GOLD_SENTINEL,
        open_ticket_preview=_FUTURE_SUPPORT_SENTINEL,
        original_vendor_issue_preview="تسویه",
        latest_vendor_message="وضعیت؟",
        recent_context_preview=None,
    )
    forbidden = extract_forbidden_values_from_operator_ticket(ticket)
    assert _GOLD_SENTINEL in forbidden

    def _mock_generate(_messages, *, provider: str, model: str) -> LLMResponse:
        combined = "\n".join(m.content for m in _messages)
        assert _GOLD_SENTINEL not in combined
        assert _FUTURE_SUPPORT_SENTINEL not in combined
        return LLMResponse(
            content="سلام — پیش‌نویس امن.",
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


def test_write_prompt_audit_jsonl(tmp_path: Path) -> None:
    case = _base_case()
    settings = AppSettings(knowledge_hints_enabled=False)

    def _mock_generate(_messages, *, provider: str, model: str) -> LLMResponse:
        return LLMResponse(content="سلام — پیش‌نویس.", provider=provider, model=model, metadata={})

    audit_path = tmp_path / "offline_draft_prompt_audit.jsonl"
    generate_offline_draft_suggestions(
        _write_benchmark(tmp_path, [case]),
        output_jsonl_path=tmp_path / "drafts.jsonl",
        output_summary_path=tmp_path / "summary.json",
        settings=settings,
        generate_fn=_mock_generate,
        prompt_audit_path=audit_path,
    )
    lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["case_id"] == case["case_id"]
    assert row["contains_gold_reference"] is False
    assert "included_fields" in row
    assert_audit_record_safe(row)


def _write_benchmark(tmp_path: Path, cases: list[dict[str, object]]) -> Path:
    path = tmp_path / "benchmark.jsonl"
    path.write_text(
        "\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n",
        encoding="utf-8",
    )
    return path


def test_process_benchmark_case_collects_audit_without_leaking() -> None:
    case = _base_case()
    row = process_benchmark_case(
        case,
        settings=AppSettings(knowledge_hints_enabled=False),
        provider="mock",
        model="mock",
        generate_fn=lambda _m, *, provider, model: LLMResponse(
            content="سلام — بررسی می‌شود.",
            provider=provider,
            model=model,
            metadata={},
        ),
        collect_prompt_audit=True,
    )
    audit = row.pop("_prompt_audit")
    assert isinstance(audit, dict)
    assert audit["leakage_check_passed"] is True
    assert _GOLD_SENTINEL not in json.dumps(row)
    assert_audit_record_safe(audit)
