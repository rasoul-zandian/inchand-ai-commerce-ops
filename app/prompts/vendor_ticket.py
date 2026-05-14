"""Prompt templates for the vendor ticket drafting workflow."""

from __future__ import annotations

from app.llm import LLMMessage


def build_vendor_ticket_prompt(
    *,
    ticket_subject: str,
    ticket_body: str,
    vendor_name: str,
    policy_summary: str,
    previous_cases_count: int,
) -> list[LLMMessage]:
    """Build system + user messages for safe Persian support reply drafting."""
    system_content = (
        "You are an AI assistant helping Inchand support operators draft safe vendor ticket replies in Persian.\n"
        "Constraints:\n"
        "- Do not promise refunds.\n"
        "- Do not guarantee financial adjustments.\n"
        "- Ask for clarification when information is missing or ambiguous.\n"
        "- Keep tone professional and aligned with marketplace support standards."
    )

    user_content = (
        "برای پیش‌نویس پاسخ، از اطلاعات زیر استفاده کن:\n\n"
        f"عنوان تیکت:\n{ticket_subject}\n\n"
        f"متن تیکت:\n{ticket_body}\n\n"
        f"نام فروشنده:\n{vendor_name}\n\n"
        "خلاصه سیاست (در صورت موجود بودن):\n"
        f"{policy_summary or '(خلاصه‌ای در دسترس نیست)'}\n\n"
        f"تعداد نمونه‌های پاسخ تأییدشدهٔ مشابه در داده: {previous_cases_count}\n"
    )

    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content=user_content),
    ]
