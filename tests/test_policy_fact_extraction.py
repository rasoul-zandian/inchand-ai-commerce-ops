"""Tests for safe policy fact extraction and grounded policy drafts."""

from __future__ import annotations

import json

from app.agentic_sandbox.agentic_batch_report import state_to_batch_row
from app.agentic_sandbox.agentic_state import initial_agentic_sandbox_state
from app.agentic_sandbox.final_draft_reflection import apply_final_draft_reflection_review
from app.agentic_sandbox.mock_draft_templates import (
    MockOperationalDraftInput,
    generate_mock_operational_draft,
)
from app.agentic_sandbox.openai_draft_provider import (
    OpenAIDraftPromptContext,
    build_openai_draft_prompt,
)
from app.config import AppSettings
from app.evals.actionability_validation import ActionabilityValidationResult
from app.evals.draft_policy_grounding_calibration import (
    apply_policy_grounding_calibration,
    draft_is_ungrounded_settlement_reply,
)
from app.evals.draft_style import (
    DRAFT_STYLE_OPERATIONAL_SHORT,
    DRAFT_STYLE_POLICY_EXPLANATION,
    resolve_effective_draft_style,
)
from app.knowledge.knowledge_retrieval_smoke import (
    SETTLEMENT_BANK_QUERY,
    evaluate_settlement_bank_smoke,
)
from app.knowledge.policy_fact_extraction import (
    COMMISSION_POLICY_FALLBACK_DRAFT_ANSWER,
    SETTLEMENT_BANK_CANONICAL_DRAFT_ANSWER,
    SETTLEMENT_CANONICAL_DRAFT_ANSWER,
    build_policy_facts_prompt_block,
    build_settlement_account_operational_ack,
    calibrate_settlement_policy_draft,
    hint_to_prompt_dict,
    is_commission_policy_question,
    is_policy_or_informational_question,
    is_settlement_account_operational_request,
    is_settlement_bank_policy_question,
    is_settlement_timing_policy_question,
    is_vague_commission_policy_draft,
    render_policy_facts_for_prompt,
    resolve_policy_question_type,
    select_policy_facts_for_draft,
    settlement_bank_fact_present,
    settlement_bank_policy_answer,
)
from app.operator_console.knowledge_hints import KnowledgeHint
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_SETTLEMENT_QUESTION = "بعد از خرید کالا توسط مشتری، چند روز دیگه میتونم تسویه کنم؟"
_SETTLEMENT_SNIPPET = (
    "مبلغ ناشی از فروش کالا ابتدا در کیف پول فروشنده بصورت بلاک ذخیره می‌شود و "
    "۳ روز بعد از نهایی شدن سفارش، قابل تسویه می‌شود و در اولین بازه تسویه "
    "به حساب فروشنده واریز می‌شود."
)
_VAGUE_SETTLEMENT_DRAFT = (
    "تسویه حساب پس از تایید پرداخت و تحویل کالا انجام می‌شود و زمان دقیق بستگی دارد؛ "
    "لطفاً به قوانین مراجعه کنید."
)


def _settlement_hint() -> KnowledgeHint:
    return KnowledgeHint(
        document_type="settlement_rules",
        section_title="زمان تسویه",
        source_lane="official_policy",
        priority_rank=1,
        snippet=_SETTLEMENT_SNIPPET,
        score=0.95,
    )


def _publishing_hint() -> KnowledgeHint:
    return KnowledgeHint(
        document_type="product_publishing_rules",
        section_title="شرایط انتشار",
        source_lane="official_policy",
        priority_rank=1,
        snippet="عنوان، توضیحات، قیمت و تصاویر باید کامل و مطابق قوانین انتشار باشد.",
        score=0.9,
    )


def test_settlement_prompt_includes_safe_policy_fact() -> None:
    block = build_policy_facts_prompt_block(
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        seller_text=_SETTLEMENT_QUESTION,
        hints=(_settlement_hint(),),
    )
    assert "کیف پول" in block
    assert "۳ روز" in block
    assert "نهایی شدن سفارش" in block
    assert "Relevant official policy facts" in block


def test_openai_prompt_includes_policy_facts_for_policy_explanation() -> None:
    facts_block = build_policy_facts_prompt_block(
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        seller_text=_SETTLEMENT_QUESTION,
        hints=(_settlement_hint(),),
    )
    context = OpenAIDraftPromptContext(
        room_id="ROOM-1",
        seller_text=_SETTLEMENT_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        conceptual_intent_fa="زمان تسویه",
        suggested_action="check_settlement_status",
        suggested_action_reason="test",
        ticket_label="fund",
        route_label="billing_review",
        order_ids=(),
        product_ids=(),
        tracking_code=None,
        knowledge_hint_document_types=("settlement_rules",),
        actionability=ActionabilityValidationResult(
            actionable=True,
            missing_required_entities=(),
            requested_action="check_settlement_status",
            validation_reason="test",
            should_request_identifier=False,
        ),
        target_max_chars=600,
        hard_max_chars=700,
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
        max_sentences=4,
        policy_facts_prompt=facts_block,
    )
    combined = "\n".join(message.content for message in build_openai_draft_prompt(context))
    assert "کیف پول" in combined
    assert "زمان‌بندی دیگری اختراع نکن" in combined


def test_vague_settlement_draft_is_detected_as_ungrounded() -> None:
    assert draft_is_ungrounded_settlement_reply(_VAGUE_SETTLEMENT_DRAFT)


def test_settlement_fallback_produces_exact_canonical_answer() -> None:
    calibrated, changed = calibrate_settlement_policy_draft(
        _VAGUE_SETTLEMENT_DRAFT,
        seller_text=_SETTLEMENT_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        hints=(_settlement_hint(),),
    )
    assert changed is True
    assert calibrated == SETTLEMENT_CANONICAL_DRAFT_ANSWER
    assert "کیف پول" in calibrated
    assert "۳ روز" in calibrated
    assert "اولین بازه تسویه" in calibrated


def test_batch_reports_exclude_raw_snippet_text() -> None:
    state = initial_agentic_sandbox_state(
        room_id="ROOM_SNIP",
        first_turn_text=_SETTLEMENT_QUESTION,
        knowledge_hints_enabled=True,
    )
    state["knowledge_hints"] = [
        {
            "document_type": "settlement_rules",
            "section_title": "زمان تسویه",
            "source_lane": "official_policy",
            "priority_rank": 1,
            "snippet_chars": len(_SETTLEMENT_SNIPPET),
        },
    ]
    state["knowledge_hints_for_prompt"] = [hint_to_prompt_dict(_settlement_hint())]
    state["draft_reply"] = SETTLEMENT_CANONICAL_DRAFT_ANSWER
    state["safety_status"] = "passed"
    row = state_to_batch_row(state, success=True, knowledge_hints_enabled=True)
    payload = json.dumps(row.to_json_dict(), ensure_ascii=False)
    assert "prompt_snippet" not in payload
    assert "کیف پول" not in payload
    assert row.knowledge_hint_document_types == ("settlement_rules",)


def test_publishing_policy_facts_selected_for_publishing_question() -> None:
    seller = "قوانین انتشار محصول جدید چیست؟"
    facts = select_policy_facts_for_draft(
        detected_intent=VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION.value,
        suggested_action="answer_policy_question",
        seller_text=seller,
        hints=(_publishing_hint(), _settlement_hint()),
    )
    assert facts
    assert facts[0].document_type == "product_publishing_rules"
    rendered = render_policy_facts_for_prompt(facts)
    assert "انتشار" in rendered


def test_apply_policy_grounding_calibration_for_settlement() -> None:
    result = apply_policy_grounding_calibration(
        _VAGUE_SETTLEMENT_DRAFT,
        seller_text=_SETTLEMENT_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
        hints=(_settlement_hint(),),
    )
    assert result.settlement_grounding_calibrated is True
    assert result.draft_reply == SETTLEMENT_CANONICAL_DRAFT_ANSWER


_IBAN_REGISTRATION_ISSUE = (
    "سلام هر کار میکنم شماره شبام ثبت نمیشع شماره شبا IR120170000000123456789001"
)
_ACCOUNT_REGISTRATION_REQUEST = "جهت ثبت اطلاعات تسویه حساب پنل و شماره شبا لطفاً ثبت و اعلام گردد"
_TIMING_FORBIDDEN_MARKERS = (
    "کیف پول",
    "بلاک",
    "۳ روز",
    "نهایی شدن سفارش",
    "اولین بازه تسویه",
)


def test_settlement_timing_question_gets_canonical_answer() -> None:
    calibrated, changed = calibrate_settlement_policy_draft(
        _VAGUE_SETTLEMENT_DRAFT,
        seller_text=_SETTLEMENT_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        hints=(_settlement_hint(),),
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
    )
    assert changed is True
    assert calibrated == SETTLEMENT_CANONICAL_DRAFT_ANSWER


def test_iban_registration_issue_gets_operational_ack_not_timing() -> None:
    assert is_settlement_account_operational_request(_IBAN_REGISTRATION_ISSUE) is True
    assert is_settlement_timing_policy_question(_IBAN_REGISTRATION_ISSUE) is False

    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_IBAN_REGISTRATION_ISSUE,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="check_settlement_status",
        ),
    )
    for marker in _TIMING_FORBIDDEN_MARKERS:
        assert marker not in draft
    assert "شبا" in draft or "بررسی" in draft

    result = apply_policy_grounding_calibration(
        SETTLEMENT_CANONICAL_DRAFT_ANSWER,
        seller_text=_IBAN_REGISTRATION_ISSUE,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        draft_style=DRAFT_STYLE_OPERATIONAL_SHORT,
        hints=(_settlement_hint(),),
    )
    for marker in _TIMING_FORBIDDEN_MARKERS:
        assert marker not in result.draft_reply
    assert result.policy_grounding_calibrated is True


def test_account_registration_request_gets_operational_ack() -> None:
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_ACCOUNT_REGISTRATION_REQUEST,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="billing_review",
        ),
    )
    assert draft == build_settlement_account_operational_ack(_ACCOUNT_REGISTRATION_REQUEST)
    for marker in _TIMING_FORBIDDEN_MARKERS:
        assert marker not in draft


def test_settlement_rules_hint_with_iban_issue_no_policy_explanation() -> None:
    style = resolve_effective_draft_style(
        seller_text=_IBAN_REGISTRATION_ISSUE,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
    )
    assert style == DRAFT_STYLE_OPERATIONAL_SHORT

    block = build_policy_facts_prompt_block(
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        seller_text=_IBAN_REGISTRATION_ISSUE,
        hints=(_settlement_hint(),),
    )
    assert block == ""

    result = apply_policy_grounding_calibration(
        _VAGUE_SETTLEMENT_DRAFT,
        seller_text=_IBAN_REGISTRATION_ISSUE,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
        hints=(_settlement_hint(),),
    )
    assert result.settlement_grounding_calibrated is False
    for marker in _TIMING_FORBIDDEN_MARKERS:
        assert marker not in result.draft_reply


def test_explicit_timing_question_with_settlement_rules_uses_policy_explanation() -> None:
    assert is_settlement_timing_policy_question(_SETTLEMENT_QUESTION) is True
    style = resolve_effective_draft_style(
        seller_text=_SETTLEMENT_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
    )
    assert style == DRAFT_STYLE_POLICY_EXPLANATION

    block = build_policy_facts_prompt_block(
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        seller_text=_SETTLEMENT_QUESTION,
        hints=(_settlement_hint(),),
    )
    assert "کیف پول" in block


def test_openai_prompt_for_iban_issue_includes_no_timing_rule() -> None:
    context = OpenAIDraftPromptContext(
        room_id="ROOM-IBAN",
        seller_text=_IBAN_REGISTRATION_ISSUE,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        conceptual_intent_fa="ثبت شبا",
        suggested_action="check_settlement_status",
        suggested_action_reason="test",
        ticket_label="fund",
        route_label="billing_review",
        order_ids=(),
        product_ids=(),
        tracking_code=None,
        knowledge_hint_document_types=("settlement_rules",),
        actionability=ActionabilityValidationResult(
            actionable=True,
            missing_required_entities=(),
            requested_action="check_settlement_status",
            validation_reason="test",
            should_request_identifier=False,
        ),
        target_max_chars=300,
        hard_max_chars=300,
        draft_style=DRAFT_STYLE_OPERATIONAL_SHORT,
        max_sentences=2,
        policy_facts_prompt="",
    )
    combined = "\n".join(message.content for message in build_openai_draft_prompt(context))
    assert "زمان‌بندی تسویه نده" in combined
    assert "کیف پول" not in combined


_BANK_POLICY_QUESTION = "برای تسویه حساب شماره حسابی یا شبا باید مربوط به کدام بانک باشد؟"
_BANK_POLICY_QUESTION_ALT = "شبای چه بانکی برای تسویه قابل قبول است؟"
_BANK_SNIPPET = (
    "به دلیل محدودیت‌های اعمال‌شده از سوی بانک مرکزی، از ابتدای ماه آینده (بهمن) "
    "تمامی تسویه‌حساب‌ها صرفاً از طریق حساب‌های بانک سامان انجام خواهد شد."
)
_SHEBA_REGISTRATION_ISSUE = "شماره شبام ثبت نمیشه IR120170000000123456789001"
_SHEBA_SUBMIT_REQUEST = "لطفا این شماره شبا را ثبت کنید IR120170000000123456789001"
_BAD_BANK_POLICY_DRAFT = "لطفاً شماره شبای صحیح خود را ارسال کنید تا ثبت شود."


def _bank_settlement_hint() -> KnowledgeHint:
    return KnowledgeHint(
        document_type="settlement_rules",
        section_title="بانک تسویه",
        source_lane="official_policy",
        priority_rank=1,
        snippet=_BANK_SNIPPET,
        score=0.95,
    )


def test_settlement_bank_policy_question_detection_and_style() -> None:
    assert is_settlement_bank_policy_question(_BANK_POLICY_QUESTION) is True
    assert resolve_policy_question_type(_BANK_POLICY_QUESTION) == "settlement_bank"
    assert is_settlement_account_operational_request(_BANK_POLICY_QUESTION) is False

    style = resolve_effective_draft_style(
        seller_text=_BANK_POLICY_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
    )
    assert style == DRAFT_STYLE_POLICY_EXPLANATION

    calibrated, changed = calibrate_settlement_policy_draft(
        _BAD_BANK_POLICY_DRAFT,
        seller_text=_BANK_POLICY_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="check_settlement_status",
        hints=(_bank_settlement_hint(),),
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
    )
    assert changed is True
    assert "بانک سامان" in calibrated
    assert "شماره شبای صحیح خود را ارسال کنید" not in calibrated


def test_settlement_bank_policy_alt_question() -> None:
    assert is_settlement_bank_policy_question(_BANK_POLICY_QUESTION_ALT) is True
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_BANK_POLICY_QUESTION_ALT,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="answer_policy_question",
        ),
    )
    assert "بانک سامان" in draft
    assert SETTLEMENT_CANONICAL_DRAFT_ANSWER not in draft


def test_sheba_operational_not_bank_policy() -> None:
    assert is_settlement_bank_policy_question(_SHEBA_REGISTRATION_ISSUE) is False
    assert is_settlement_account_operational_request(_SHEBA_REGISTRATION_ISSUE) is True

    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_SHEBA_REGISTRATION_ISSUE,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="check_settlement_status",
        ),
    )
    assert "بانک سامان" not in draft


def test_sheba_submit_request_not_bank_policy() -> None:
    assert is_settlement_bank_policy_question(_SHEBA_SUBMIT_REQUEST) is False
    assert is_settlement_account_operational_request(_SHEBA_SUBMIT_REQUEST) is True
    draft = generate_mock_operational_draft(
        MockOperationalDraftInput(
            seller_text=_SHEBA_SUBMIT_REQUEST,
            detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
            suggested_action="billing_review",
        ),
    )
    assert draft == build_settlement_account_operational_ack(_SHEBA_SUBMIT_REQUEST)
    assert "بانک سامان" not in draft


def test_settlement_bank_retrieval_smoke_markers() -> None:
    case = evaluate_settlement_bank_smoke(
        [
            {
                "document_type": "settlement_rules",
                "section_title": "بانک",
                "text_snippet": _BANK_SNIPPET,
            },
        ],
    )
    assert case.passed
    assert case.query == SETTLEMENT_BANK_QUERY


def test_settlement_bank_policy_fact_extraction() -> None:
    facts = select_policy_facts_for_draft(
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="answer_policy_question",
        seller_text=_BANK_POLICY_QUESTION,
        hints=(_bank_settlement_hint(),),
    )
    assert settlement_bank_fact_present(facts)
    answer = settlement_bank_policy_answer(facts)
    assert answer == SETTLEMENT_BANK_CANONICAL_DRAFT_ANSWER
    assert "بانک سامان" in answer


def test_reflection_rewrites_sheba_request_for_bank_policy_question() -> None:
    final, result = apply_final_draft_reflection_review(
        _BAD_BANK_POLICY_DRAFT,
        seller_text=_BANK_POLICY_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="answer_policy_question",
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "بانک سامان" in final
    assert "شماره شبای صحیح خود را ارسال کنید" not in final


def test_openai_prompt_for_bank_policy_includes_no_sheba_rule() -> None:
    facts_block = build_policy_facts_prompt_block(
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="answer_policy_question",
        seller_text=_BANK_POLICY_QUESTION,
        hints=(_bank_settlement_hint(),),
    )
    context = OpenAIDraftPromptContext(
        room_id="ROOM-BANK",
        seller_text=_BANK_POLICY_QUESTION,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        conceptual_intent_fa="بانک تسویه",
        suggested_action="answer_policy_question",
        suggested_action_reason="test",
        ticket_label="fund",
        route_label="billing_review",
        order_ids=(),
        product_ids=(),
        tracking_code=None,
        knowledge_hint_document_types=("settlement_rules",),
        actionability=ActionabilityValidationResult(
            actionable=True,
            missing_required_entities=(),
            requested_action="answer_policy_question",
            validation_reason="test",
            should_request_identifier=False,
        ),
        target_max_chars=600,
        hard_max_chars=700,
        draft_style=DRAFT_STYLE_POLICY_EXPLANATION,
        max_sentences=4,
        policy_facts_prompt=facts_block,
    )
    combined = "\n".join(message.content for message in build_openai_draft_prompt(context))
    assert "شماره شبا نخواه" in combined
    assert "کدام بانک" in combined or "بانک قابل قبول" in combined


def test_commission_policy_question_detection() -> None:
    seller = "سلام وقت بخیر کمیسیون فروش چند درصده؟"
    assert is_commission_policy_question(seller)
    assert is_policy_or_informational_question(
        seller,
        detected_intent=VendorTicketIntent.COMMISSION_POLICY_QUESTION.value,
    )


def test_commission_vague_draft_detected_for_safe_fallback() -> None:
    draft = "کمیسیون بستگی دارد؛ برای اطلاعات بیشتر به راهنما مراجعه کنید."
    assert is_vague_commission_policy_draft(draft)
    assert "کمیسیون" in COMMISSION_POLICY_FALLBACK_DRAFT_ANSWER
