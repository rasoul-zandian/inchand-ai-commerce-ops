"""Deterministic mock tools for retrieval (no I/O, database, network, or LLM)."""

from __future__ import annotations

import hashlib
from typing import Any


def get_ticket(ticket_id: str) -> dict[str, Any]:
    """Return a fixed vendor ticket shape for the given id."""
    return {
        "id": ticket_id,
        "subject": "مشکل در تسویه فروش هفتگی",
        "body": ("سلام، مبلغ تسویه این هفته با فاکتور فروش هم‌خوانی ندارد. لطفاً بررسی کنید."),
        "status": "open",
        "vendor_id": "demo-vendor-001",
    }


def get_vendor_profile(vendor_id: str) -> dict[str, Any]:
    """Return a fixed vendor profile for the given id."""
    return {
        "id": vendor_id,
        "name": "فروشگاه نمونه اینچند",
        "status": "active",
        "trust_score": 0.78,
    }


def search_support_policy(query: str) -> dict[str, Any]:
    """Return a mock policy bundle; output varies deterministically with query text."""
    safe_query = query.strip() or "پرسش عمومی پشتیبانی"
    return {
        "source_type": "internal_policy",
        "title": f"راهنمای پاسخ‌گویی تیکت فروشنده — {safe_query[:48]}",
        "summary": (
            "طبق سیاست اینچند، پاسخ به تیکت فروشنده باید محترمانه، شفاف و بدون تعهد مالی باشد؛ "
            "هرگونه تعدیل مالی نیازمند تأیید انسانی است. "
            f"کلیدواژه پرسش: «{safe_query}»."
        ),
        "policy_points": [
            "از زبان رسمی و محترمانه استفاده کنید.",
            "بدون تأیید واحد مالی، عدد یا تاریخ قطعی اعلام نکنید.",
            "در صورت ابهام مالی، درخواست مدارک تکمیلی (فاکتور/بازه) را شفاف مطرح کنید.",
        ],
    }


def search_previous_ticket_responses(query: str) -> list[dict[str, Any]]:
    """Return short, approved-style prior cases; stable for a given query string."""
    safe_query = query.strip() or "پرسش عمومی"
    query_key = hashlib.sha256(safe_query.encode("utf-8")).hexdigest()[:8]
    return [
        {
            "case_id": "CASE-1001",
            "detected_intent": "billing_discrepancy",
            "response_summary": (
                "پاسخ تأییدشده: درخواست فاکتور و بازه زمانی، "
                "وعده بررسی توسط مالی بدون تعهد قطعی به مبلغ."
            ),
            "approved": True,
        },
        {
            "case_id": f"CASE-1002-{query_key}",
            "detected_intent": "payout_delay",
            "response_summary": (
                f"نمونه مرتبط با پرسش «{safe_query[:40]}»: "
                "اطلاع‌رسانی تأخیر احتمالی و مسیر پیگیری داخلی."
            ),
            "approved": True,
        },
    ]
