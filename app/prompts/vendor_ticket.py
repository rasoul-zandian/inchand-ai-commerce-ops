"""Prompt templates for the vendor ticket drafting workflow."""

from __future__ import annotations

from app.llm import LLMMessage
from app.rag.types import RAGDocument

_RAG_CONTENT_MAX_CHARS = 500


def _truncate_rag_content(text: str, *, max_chars: int = _RAG_CONTENT_MAX_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


def _format_rag_context(documents: list[RAGDocument]) -> str:
    """Format retrieved documents as plain Persian text; empty input uses the standard fallback."""
    if not documents:
        return "(سندی بازیابی نشد)"

    blocks: list[str] = []
    for index, doc in enumerate(documents, start=1):
        lines: list[str] = [
            f"[سند {index}]",
            f"عنوان: {doc.title}",
            f"نوع: {doc.source_type}",
        ]
        if doc.score is not None:
            lines.append(f"امتیاز شباهت: {doc.score}")
        lines.append("محتوا:")
        lines.append(_truncate_rag_content(doc.content))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_vendor_ticket_prompt(
    *,
    ticket_subject: str,
    ticket_body: str,
    vendor_name: str,
    policy_summary: str,
    previous_cases_count: int,
    rag_documents: list[RAGDocument] | None = None,
) -> list[LLMMessage]:
    """Build system + user messages for safe Persian support reply drafting."""
    system_content = (
        "You are an AI assistant helping Inchand support operators draft safe "
        "vendor ticket replies in Persian.\n"
        "Constraints:\n"
        "- Do not promise refunds.\n"
        "- Do not guarantee financial adjustments.\n"
        "- Ask for clarification when information is missing or ambiguous.\n"
        "- Keep tone professional and aligned with marketplace support standards."
    )

    rag_block = _format_rag_context(list(rag_documents or []))

    user_content = (
        "برای پیش‌نویس پاسخ، از اطلاعات زیر استفاده کن:\n\n"
        f"عنوان تیکت:\n{ticket_subject}\n\n"
        f"متن تیکت:\n{ticket_body}\n\n"
        f"نام فروشنده:\n{vendor_name}\n\n"
        "خلاصه سیاست (در صورت موجود بودن):\n"
        f"{policy_summary or '(خلاصه‌ای در دسترس نیست)'}\n\n"
        f"تعداد نمونه‌های پاسخ تأییدشدهٔ مشابه در داده: {previous_cases_count}\n\n"
        "اسناد و سیاست‌های بازیابی‌شده:\n"
        f"{rag_block}\n"
    )

    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content=user_content),
    ]


def build_controlled_redraft_prompt(
    *,
    ticket_subject: str,
    ticket_body: str,
    vendor_name: str,
    policy_summary: str,
    previous_draft: str,
    operator_comment: str,
    rag_documents: list[RAGDocument] | None = None,
) -> list[LLMMessage]:
    """Build messages for operator-guided redraft (single controlled regeneration)."""
    system_content = (
        "You are an AI assistant helping Inchand support operators revise a vendor ticket "
        "draft in Persian under human supervision.\n"
        "Constraints:\n"
        "- Apply the operator revision instructions exactly.\n"
        "- Do not promise refunds or guarantee financial adjustments.\n"
        "- Keep tone professional.\n"
        "- Output only the revised draft text."
    )
    rag_block = _format_rag_context(list(rag_documents or []))
    user_content = (
        "یک پیش‌نویس قبلی و دستورالعمل بازبینی اپراتور دارید. فقط پیش‌نویس بازنگری‌شده را بنویسید.\n\n"
        f"عنوان تیکت:\n{ticket_subject}\n\n"
        f"متن تیکت:\n{ticket_body}\n\n"
        f"نام فروشنده:\n{vendor_name}\n\n"
        "خلاصه سیاست:\n"
        f"{policy_summary or '(خلاصه‌ای در دسترس نیست)'}\n\n"
        "پیش‌نویس قبلی:\n"
        f"{previous_draft}\n\n"
        "دستورالعمل بازبینی اپراتور:\n"
        f"{operator_comment}\n\n"
        "اسناد بازیابی‌شده (مرجع):\n"
        f"{rag_block}\n"
    )
    return [
        LLMMessage(role="system", content=system_content),
        LLMMessage(role="user", content=user_content),
    ]
