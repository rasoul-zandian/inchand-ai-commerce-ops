"""Tests for vendor ticket prompt construction (no LLM calls)."""

from __future__ import annotations

from app.prompts.vendor_ticket import build_vendor_ticket_prompt
from app.rag.types import RAGDocument


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
    assert "اسناد و سیاست‌های بازیابی‌شده:" in user


def test_build_vendor_ticket_prompt_includes_rag_section_with_documents() -> None:
    docs = [
        RAGDocument(
            document_id="d1",
            title="عنوان سند",
            content="متن کوتاه سیاست.",
            source_type="policy",
            score=0.91,
            metadata={},
        )
    ]
    messages = build_vendor_ticket_prompt(
        ticket_subject="س",
        ticket_body="ب",
        vendor_name="ف",
        policy_summary="پ",
        previous_cases_count=0,
        rag_documents=docs,
    )
    user = messages[1].content
    assert "اسناد و سیاست‌های بازیابی‌شده:" in user
    assert "[سند 1]" in user
    assert "عنوان: عنوان سند" in user
    assert "نوع: policy" in user
    assert "امتیاز شباهت: 0.91" in user
    assert "متن کوتاه سیاست." in user


def test_build_vendor_ticket_prompt_empty_rag_documents_shows_fallback() -> None:
    messages = build_vendor_ticket_prompt(
        ticket_subject="س",
        ticket_body="ب",
        vendor_name="ف",
        policy_summary="پ",
        previous_cases_count=0,
        rag_documents=[],
    )
    user = messages[1].content
    assert "اسناد و سیاست‌های بازیابی‌شده:" in user
    assert "(سندی بازیابی نشد)" in user


def test_build_vendor_ticket_prompt_truncates_long_rag_content() -> None:
    long_body = "X" * 600
    messages = build_vendor_ticket_prompt(
        ticket_subject="س",
        ticket_body="ب",
        vendor_name="ف",
        policy_summary="پ",
        previous_cases_count=0,
        rag_documents=[
            RAGDocument(
                document_id="d-long",
                title="طولانی",
                content=long_body,
                source_type="policy",
                score=None,
                metadata={},
            )
        ],
    )
    user = messages[1].content
    assert "…" in user
    assert user.count("X") == 500


def test_build_vendor_ticket_prompt_score_formatting_when_present() -> None:
    messages = build_vendor_ticket_prompt(
        ticket_subject="س",
        ticket_body="ب",
        vendor_name="ف",
        policy_summary="پ",
        previous_cases_count=0,
        rag_documents=[
            RAGDocument(
                document_id="d",
                title="تی",
                content="محتوا",
                source_type="approved_pattern",
                score=0.42,
                metadata={},
            )
        ],
    )
    assert "امتیاز شباهت: 0.42" in messages[1].content


def test_build_vendor_ticket_prompt_no_score_line_when_score_absent() -> None:
    messages = build_vendor_ticket_prompt(
        ticket_subject="س",
        ticket_body="ب",
        vendor_name="ف",
        policy_summary="پ",
        previous_cases_count=0,
        rag_documents=[
            RAGDocument(
                document_id="d",
                title="تی",
                content="محتوا",
                source_type="style_guide",
                score=None,
                metadata={},
            )
        ],
    )
    assert "امتیاز شباهت" not in messages[1].content
