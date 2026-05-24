"""Tests for OpenAI draft quality pilot (mock client only; no network in CI)."""

from __future__ import annotations

import json

from app.agentic_sandbox.agentic_graph import (
    initial_state_from_ticket,
    run_agentic_sandbox_workflow,
)
from app.agentic_sandbox.openai_draft_provider import (
    DRAFT_PROVIDER_MOCK_FALLBACK,
    DRAFT_PROVIDER_OPENAI,
    OpenAIDraftPromptContext,
    build_openai_draft_prompt,
    generate_openai_draft,
    generic_response_detection,
    repetitive_template_detection,
    sanitize_openai_draft,
    validate_openai_draft_quality,
)
from app.config import AppSettings
from app.evals.actionability_validation import ActionabilityValidationResult
from app.evals.offline_draft_generation import assert_draft_reply_safe
from app.llm.types import LLMMessage, LLMResponse
from app.operator_console.console_models import OperatorTicket


def _actionability(
    *,
    actionable: bool = True,
    missing: tuple[str, ...] = (),
    should_request: bool = False,
    requested_action: str = "check_order_status",
) -> ActionabilityValidationResult:
    return ActionabilityValidationResult(
        actionable=actionable,
        missing_required_entities=missing,
        requested_action=requested_action,
        validation_reason="test",
        should_request_identifier=should_request,
    )


def _prompt_context(**overrides: object) -> OpenAIDraftPromptContext:
    base = {
        "room_id": "ROOM-1",
        "seller_text": "سلام",
        "detected_intent": "general_inquiry",
        "conceptual_intent_fa": "سؤال عمومی",
        "suggested_action": "human_followup",
        "suggested_action_reason": "نیاز به جزئیات",
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "order_ids": (),
        "product_ids": (),
        "tracking_code": None,
        "knowledge_hint_document_types": ("support_faq",),
        "actionability": _actionability(should_request=False, actionable=False),
        "target_max_chars": 300,
        "hard_max_chars": 700,
    }
    base.update(overrides)
    return OpenAIDraftPromptContext(**base)  # type: ignore[arg-type]


def _openai_generate(content: str):
    def _fn(messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
        _ = messages, provider, model
        return LLMResponse(content=content, provider="openai", model=model, metadata={})

    return _fn


def test_build_openai_draft_prompt_excludes_snippets_and_transcripts() -> None:
    messages = build_openai_draft_prompt(_prompt_context(seller_text="سلام وقت بخیر"))
    combined = "\n".join(message.content for message in messages)
    assert "snippet" not in combined.lower()
    assert "transcript" not in combined.lower()
    assert "latest_vendor_message" not in combined
    assert "مطابق اقدام پیشنهادی" in combined  # banned phrase appears in rules, not output


def test_greeting_only_openai_draft_asks_for_details() -> None:
    content = json.dumps(
        {"draft_reply": "سلام؛ لطفاً موضوع درخواست خود را با جزئیات بنویسید."},
        ensure_ascii=False,
    )
    result = generate_openai_draft(
        _prompt_context(seller_text="سلام"),
        generate_fn=_openai_generate(content),
    )
    assert result.draft_provider == DRAFT_PROVIDER_OPENAI
    assert "جزئیات" in result.draft.draft_reply or "موضوع" in result.draft.draft_reply
    assert not generic_response_detection(result.draft.draft_reply)


def test_missing_identifier_openai_draft_requests_order_id() -> None:
    content = json.dumps(
        {"draft_reply": "لطفاً شماره سفارش را ارسال کنید تا وضعیت بررسی شود."},
        ensure_ascii=False,
    )
    ctx = _prompt_context(
        seller_text="وضعیت سفارش را بگویید",
        detected_intent="order_status_inquiry",
        suggested_action="check_order_status",
        actionability=_actionability(
            actionable=False,
            missing=("order_id",),
            should_request=True,
            requested_action="check_order_status",
        ),
    )
    result = generate_openai_draft(ctx, generate_fn=_openai_generate(content))
    assert "سفارش" in result.draft.draft_reply
    assert_draft_reply_safe(result.draft.draft_reply)


def test_settlement_openai_draft_is_concise_and_factual() -> None:
    draft = "تسویه پس از نهایی شدن سفارش طبق چرخه پرداخت انجام می‌شود."
    result = generate_openai_draft(
        _prompt_context(
            seller_text="زمان تسویه چه زمانی است؟",
            detected_intent="settlement_status_inquiry",
            suggested_action="check_settlement_status",
            order_ids=("1234567",),
            actionability=_actionability(actionable=True),
        ),
        generate_fn=_openai_generate(json.dumps({"draft_reply": draft}, ensure_ascii=False)),
    )
    quality = validate_openai_draft_quality(result.draft.draft_reply)
    assert "تسویه" in result.draft.draft_reply
    assert len(result.draft.draft_reply) <= 300
    assert quality.concise_reply


def test_generic_boilerplate_detection_flags_banned_phrases() -> None:
    assert generic_response_detection("مطابق اقدام پیشنهادی بررسی می‌شود.")
    assert generic_response_detection("درخواست شما دریافت شد.")
    assert repetitive_template_detection("درخواست شما دریافت شد و توسط تیم مربوطه بررسی خواهد شد.")


def test_openai_draft_quality_rejects_generic_boilerplate() -> None:
    quality = validate_openai_draft_quality("درخواست شما دریافت شد و بررسی خواهد شد.")
    assert quality.generic_reply
    assert not quality.quality_ok


def test_sanitize_openai_draft_strips_markdown_and_respects_max_length() -> None:
    raw = json.dumps({"draft_reply": "**سلام** " + ("الف" * 800)}, ensure_ascii=False)
    draft = sanitize_openai_draft(raw, max_chars=300, detected_intent="general_inquiry")
    assert "**" not in draft
    assert len(draft) <= 300
    assert_draft_reply_safe(draft, max_chars=700)


def test_hallucinated_entity_warning_when_id_not_in_seller_text() -> None:
    quality = validate_openai_draft_quality(
        "وضعیت سفارش 9999999 بررسی می‌شود.",
        seller_text="وضعیت سفارش را بگویید",
        extracted_order_ids=("9999999",),
    )
    assert any("possible_hallucinated_order" in warning for warning in quality.warnings)


def test_graceful_mock_fallback_when_openai_fails() -> None:
    def _fail(*_args: object, **_kwargs: object) -> LLMResponse:
        raise RuntimeError("openai unavailable")

    result = generate_openai_draft(
        _prompt_context(seller_text="سلام"),
        generate_fn=_fail,
    )
    assert result.used_mock_fallback
    assert result.draft_provider == DRAFT_PROVIDER_MOCK_FALLBACK
    assert result.fallback_warning
    assert result.draft.draft_reply
    assert "خروجی آزمایشی" not in result.draft.draft_reply


def test_generate_draft_node_openai_provider_with_mock_client() -> None:
    ticket = OperatorTicket(
        room_id="ROOM-OAI-1",
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
        ticket_text_preview="preview",
        open_ticket_preview="preview",
        original_vendor_issue_preview="زمان تسویه چه زمانی است؟",
        latest_vendor_message="later",
        recent_context_preview="later",
        extracted_order_id="1234567",
        extracted_order_ids="1234567",
        extracted_tracking_code=None,
        extracted_product_ids=None,
        extracted_tracking_carrier=None,
        extracted_iban=None,
        extracted_iban_masked=None,
        entity_warnings_summary=None,
        detected_intent=None,
    )

    def _mock_openai(messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
        _ = provider, model
        assert all("snippet" not in message.content.lower() for message in messages)
        return LLMResponse(
            content=json.dumps(
                {"draft_reply": "تسویه پس از نهایی شدن سفارش انجام می‌شود."},
                ensure_ascii=False,
            ),
            provider="openai",
            model=model,
            metadata={},
        )

    settings = AppSettings(knowledge_hints_enabled=False)
    initial = initial_state_from_ticket(
        ticket,
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        generate_fn=_mock_openai,
    )
    final = run_agentic_sandbox_workflow(initial, settings=settings)
    assert final.get("draft_provider") == DRAFT_PROVIDER_OPENAI
    assert final.get("safety_status") == "passed"
    assert final.get("execution_allowed") is False
    assert final.get("customer_send_allowed") is False
    assert "تسویه" in (final.get("draft_reply") or "")
    metrics = final.get("openai_draft_metrics") or {}
    assert metrics.get("draft_provider") == DRAFT_PROVIDER_OPENAI


def test_preview_shows_openai_draft_provider_label() -> None:
    from app.operator_console.agentic_sandbox_preview import sanitize_agentic_preview_result

    preview = sanitize_agentic_preview_result(
        {
            "room_id": "ROOM-1",
            "safety_status": "passed",
            "human_review_required": True,
            "execution_allowed": False,
            "customer_send_allowed": False,
            "draft_reply": "پاسخ کوتاه برای بررسی.",
            "draft_provider": "openai",
            "node_results": [{"node": "generate_draft", "status": "ok", "summary": "ok"}],
        },
        knowledge_hints_enabled=False,
        llm_provider="openai",
    )
    assert preview.draft_provider == "openai"
    assert preview.draft_is_mock is False
    assert preview.draft_reply
