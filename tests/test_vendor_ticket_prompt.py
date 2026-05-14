"""Tests for vendor ticket prompt construction (no LLM calls)."""

from __future__ import annotations

from app.prompts.vendor_ticket import build_vendor_ticket_prompt


def test_build_vendor_ticket_prompt_structure() -> None:
    messages = build_vendor_ticket_prompt(
        ticket_subject="عنوان تست",
        ticket_body="متن تست",
        vendor_name="فروشنده تست",
        policy_summary="خلاصه سیاست",
        previous_cases_count=3,
    )
    assert len(messages) == 2
    assert messages[0].role == "system"
    assert messages[1].role == "user"


def test_build_vendor_ticket_prompt_system_constraints() -> None:
    messages = build_vendor_ticket_prompt(
        ticket_subject="s",
        ticket_body="b",
        vendor_name="v",
        policy_summary="p",
        previous_cases_count=0,
    )
    system = messages[0].content
    assert "You are an AI assistant helping Inchand support operators" in system
    assert "Do not promise refunds" in system
    assert "Do not guarantee financial adjustments" in system
    assert "Ask for clarification" in system
    assert "professional" in system.lower()


def test_build_vendor_ticket_prompt_user_includes_context() -> None:
    messages = build_vendor_ticket_prompt(
        ticket_subject="موضوع ویژه",
        ticket_body="بدنه ویژه",
        vendor_name="نام فروشنده",
        policy_summary="",
        previous_cases_count=5,
    )
    user = messages[1].content
    assert "موضوع ویژه" in user
    assert "بدنه ویژه" in user
    assert "نام فروشنده" in user
    assert "تعداد نمونه‌های پاسخ تأییدشدهٔ مشابه در داده: 5" in user
    assert "(خلاصه‌ای در دسترس نیست)" in user
