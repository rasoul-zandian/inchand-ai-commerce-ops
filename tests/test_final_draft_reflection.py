"""Tests for lightweight final draft reflection (single-pass)."""

from __future__ import annotations

from app.agentic_sandbox.final_draft_reflection import (
    FinalDraftReflectionContext,
    ReflectionIssueType,
    apply_final_draft_reflection_review,
    apply_reflection_rewrites,
    assert_reflection_single_pass,
    reflection_metadata_row,
    review_final_draft,
    run_deterministic_reflection_checks,
)
from app.config import AppSettings
from app.knowledge.policy_fact_extraction import SETTLEMENT_CANONICAL_DRAFT_ANSWER
from app.workflows.operational_information_sufficiency import build_panel_issue_response
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent


def _ctx(**kwargs: object) -> FinalDraftReflectionContext:
    base = {
        "seller_text": "",
        "detected_intent": None,
        "suggested_action": None,
        "conceptual_intent_fa": None,
        "draft_style": None,
        "order_ids": (),
        "product_ids": (),
        "tracking_code": None,
        "extracted_iban": None,
        "has_incomplete_iban_entity": False,
        "entity_warnings_summary": None,
        "shop_id": None,
        "policy_hints": (),
        "draft_provider": None,
    }
    base.update(kwargs)
    return FinalDraftReflectionContext(**base)  # type: ignore[arg-type]


def test_reflection_removes_repeated_order_id_request() -> None:
    seller = "سفارش 1234567 تحویل مشتری شده"
    bad = "لطفاً شماره سفارش را ارسال کنید تا ثبت تحویل انجام شود."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "شماره سفارش" not in final


def test_reflection_removes_tracking_request_when_present() -> None:
    seller = "کد رهگیری 1234567890 برای سفارش 7654321"
    bad = "لطفاً کد رهگیری و نحوه ارسال را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        suggested_action="record_update",
        order_ids=("7654321",),
        tracking_code="1234567890",
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "کد رهگیری" not in final


def test_settlement_vague_answer_replaced_with_grounded() -> None:
    seller = "بعد از خرید چند روز تسویه می‌شود؟"
    bad = "زمان تسویه به قوانین بستگی دارد؛ لطفاً به راهنما مراجعه کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="answer_policy_question",
        draft_style="policy_explanation",
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert SETTLEMENT_CANONICAL_DRAFT_ANSWER in final or "کیف پول" in final


def test_commission_policy_question_never_rewritten_to_order_or_tracking_request() -> None:
    seller = "سلام وقت بخیر\nکمیسیون فروش چند درصده؟"
    bad = (
        "سلام، کمیسیون فروش بستگی به نوع کالا و شرایط فروش دارد. "
        "برای اطلاعات دقیق‌تر می‌توانید به راهنمای کمیسیون مراجعه کنید."
    )
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        draft_style="policy_explanation",
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert "شماره سفارش" not in final
    assert "کد رهگیری" not in final
    assert "شناسه کالا" not in final
    assert "کمیسیون" in final or "کارمزد" in final
    assert result.rewrite_applied is False or "دسته‌بندی" in final or "بررسی" in final


def test_settlement_policy_reflection_stays_policy_and_never_asks_order_id() -> None:
    seller = "بعد از خرید مشتری چند روز بعد میتونم تسویه کنم؟"
    bad = "زمان تسویه به قوانین بستگی دارد؛ لطفاً به راهنما مراجعه کنید."
    final, _ = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
        suggested_action="answer_policy_question",
        draft_style="policy_explanation",
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert "شماره سفارش" not in final
    assert "کد رهگیری" not in final


def test_panel_issue_asking_panel_id_rewritten() -> None:
    seller = "سلام مشکل پنل من حل نشد؟"
    bad = "لطفاً شناسه پنل را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE.value,
        suggested_action="human_followup",
        shop_id="4136",
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert final == build_panel_issue_response()
    assert "شناسه پنل" not in final


def test_unnecessary_photo_request_removed() -> None:
    seller = "سفارش 1234567 تحویل مشتری شده"
    bad = "لطفاً فایل عکس را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        suggested_action="update_delivery_status",
        order_ids=("1234567",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "عکس" not in final


def test_tracking_fulfilled_generic_clarification_rewritten() -> None:
    bad = "لطفاً مشخص کنید چه کمکی نیاز دارید یا سوال خاصی دارید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text="051800506400081160839102",
        suggested_action="record_update",
        pending_request_type="requested_tracking_code",
        pending_request_fulfilled=True,
        context_tracking_codes=("051800506400081160839102",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "کد رهگیری دریافت شد" in final
    assert "چه کمکی نیاز دارید" not in final


def test_tracking_fulfilled_repeated_ask_rewritten() -> None:
    bad = "لطفاً کد رهگیری را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text="051800506400081160839102",
        pending_request_type="requested_tracking_code",
        pending_request_fulfilled=True,
        context_tracking_codes=("051800506400081160839102",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "کد رهگیری دریافت شد" in final
    assert "کد رهگیری را ارسال کنید" not in final


def test_tracking_fulfilled_ack_unchanged_when_already_correct() -> None:
    good = "کد رهگیری دریافت شد و درخواست شما در دست بررسی قرار گرفت."
    final, result = apply_final_draft_reflection_review(
        good,
        seller_text="051800506400081160839102",
        pending_request_type="requested_tracking_code",
        pending_request_fulfilled=True,
        context_tracking_codes=("051800506400081160839102",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert not result.rewrite_applied
    assert final == good


def test_delivery_completed_phone_off_bad_advice_rewritten_to_ack() -> None:
    seller = "سلام این سفارش تحویل دادم INC-7353428 ولی مشتری گوشیش خاموشه که کد تحویل بزنم"
    bad = (
        "برای ثبت کد تحویل، لطفاً شماره تماس مشتری را بررسی کنید یا منتظر بمانید "
        "تا گوشی او روشن شود."
    )
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("7353428",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied is True
    assert final == "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    assert "گوشی" not in final
    assert "منتظر" not in final
    assert "شماره تماس" not in final
    assert "کد تحویل" not in final
    assert "کد پیامک" not in final


def test_delivery_completed_sms_code_missing_bad_advice_rewritten_to_ack() -> None:
    seller = "سفارش 7353428 تحویل مشتری شد ولی کد پیامک ندارم"
    bad = "برای ثبت کد پیامک لطفاً کد دریافت را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        detected_intent=VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        suggested_action="update_delivery_status",
        order_ids=("7353428",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied is True
    assert final == "درخواست تحویل سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    assert "کد پیامک" not in final
    assert "کد دریافت" not in final


def test_generic_provide_more_details_removed() -> None:
    seller = "لغو سفارش 1234567"
    bad = "درخواست لغو ثبت شد. لطفاً جزئیات بیشتری ارائه دهید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        suggested_action="human_followup",
        order_ids=("1234567",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert "جزئیات بیشتری" not in final


def test_no_issue_leaves_draft_unchanged() -> None:
    good = "درخواست لغو سفارش شما ثبت شد و در دست بررسی قرار گرفت."
    final, result = apply_final_draft_reflection_review(
        good,
        seller_text="لغو سفارش 1234567",
        order_ids=("1234567",),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert final == good
    assert not result.rewrite_applied


def test_rewrite_stays_concise() -> None:
    seller = "لغو سفارش 1234567"
    bad = "لطفاً شماره سفارش را ارسال کنید. " * 20
    final, _ = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        order_ids=("1234567",),
        settings=AppSettings(
            final_draft_reflection_enabled=True,
            final_draft_reflection_max_rewrite_chars=300,
        ),
    )
    assert len(final) <= 300


def test_shop_name_change_rewrites_unnecessary_shop_id_request() -> None:
    seller = "می خواستم اسم فروشگاه رو به شالیزار تغییر بدم"
    bad = "برای تغییر نام فروشگاه، لطفاً شناسه فروشگاه خود را ارائه دهید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        suggested_action="record_update",
        shop_id="4136",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert final == "درخواست شما ثبت شد و در دست بررسی قرار گرفت."
    assert "شناسه فروشگاه" not in final


def test_shop_name_change_rewrites_unnecessary_seller_id_request() -> None:
    seller = "می‌خواهم اسم فروشگاه شالیزار شود"
    bad = "لطفاً seller id را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        suggested_action="record_update",
        shop_id="4136",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert final == "درخواست شما ثبت شد و در دست بررسی قرار گرفت."


def test_shop_identifier_request_not_rewritten_without_runtime_context() -> None:
    seller = "اسم فروشگاه را تغییر دهید"
    bad = "لطفاً شناسه فروشگاه را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text=seller,
        suggested_action="record_update",
        runtime_shop_identity_available=False,
        runtime_shop_id_present=False,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert not result.rewrite_applied
    assert "شناسه فروشگاه" in final


def test_unrelated_legitimate_order_id_request_preserved() -> None:
    seller = "سفارش ارسال شد"
    draft = "لطفاً شماره سفارش را ارسال کنید تا بررسی شود."
    final, _result = apply_final_draft_reflection_review(
        draft,
        seller_text=seller,
        suggested_action="check_order_status",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert "شماره سفارش" in final


def test_runtime_shop_identity_flags_do_not_leak_raw_shop_id() -> None:
    _final, result = apply_final_draft_reflection_review(
        "برای تغییر نام فروشگاه، لطفاً shop id را ارسال کنید.",
        seller_text="اسم فروشگاه را عوض کنید",
        suggested_action="record_update",
        shop_id="PRIVATE_SHOP_4136",
        runtime_shop_identity_available=True,
        runtime_shop_id_present=True,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    payload = reflection_metadata_row(result)
    blob = str(payload)
    assert "PRIVATE_SHOP_4136" not in blob


def test_single_pass_guard() -> None:
    result = review_final_draft(
        "test",
        _ctx(),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert_reflection_single_pass(result)
    assert result.rewrite_pass_count <= 1


def test_reflection_metadata_safe() -> None:
    result = review_final_draft(
        "لطفاً شناسه پنل را ارسال کنید.",
        _ctx(seller_text="مشکل پنل"),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    meta = reflection_metadata_row(result)
    assert "reflection_reviewed" in meta
    assert "chain" not in str(meta).lower()
    assert "reasoning" not in str(meta).lower()


def test_cancellation_reason_ask_rewritten_to_acknowledgment() -> None:
    seller = "سفارش 7367917 لغو شود"
    bad = "لطفاً دلیل لغو و توضیحات بیشتر را ارسال کنید."
    result = review_final_draft(
        bad,
        _ctx(
            seller_text=seller,
            detected_intent="cancellation_request",
            suggested_action="human_followup",
            order_ids=("7367917",),
        ),
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied is True
    assert "درخواست لغو سفارش" in result.final_draft
    assert "دلیل" not in result.final_draft


def test_reflection_blocks_repeated_optional_tracking_ask() -> None:
    bad = "لطفاً کد رهگیری را ارسال کنید."
    final, result = apply_final_draft_reflection_review(
        bad,
        seller_text="با پیک ارسال کردم",
        pending_request_type="requested_tracking_code",
        pending_request_fulfilled=True,
        tracking_optional=True,
        settings=AppSettings(final_draft_reflection_enabled=True),
    )
    assert result.rewrite_applied
    assert final == "درخواست شما ثبت و در دست بررسی قرار گرفت."
    assert "کد رهگیری را ارسال" not in final


def test_cancellation_draft_unchanged_when_no_issue() -> None:
    draft = "لطفاً شماره سفارش را ارسال کنید تا درخواست لغو بررسی شود."
    findings = run_deterministic_reflection_checks(
        draft,
        _ctx(seller_text="لغو سفارش", suggested_action="human_followup"),
    )
    assert ReflectionIssueType.REPEATED_IDENTIFIER_REQUEST not in {f.issue_type for f in findings}


def test_apply_reflection_rewrites_idempotent_single_pass() -> None:
    ctx = _ctx(
        seller_text="سفارش 7367917 لغو شود",
        order_ids=("7367917",),
        detected_intent="cancellation_request",
        suggested_action="human_followup",
    )
    bad = "لطفاً شماره سفارش را ارسال کنید."
    findings = run_deterministic_reflection_checks(bad, ctx)
    rewritten, changed = apply_reflection_rewrites(bad, ctx, findings, max_chars=300)
    assert changed
    assert "درخواست لغو" in rewritten
    rewritten2, changed2 = apply_reflection_rewrites(rewritten, ctx, findings, max_chars=300)
    assert rewritten2 == rewritten
    assert not changed2
