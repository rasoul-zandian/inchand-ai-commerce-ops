"""Lightweight cancellation-request phrase detection (no taxonomy imports)."""

from __future__ import annotations

import re

_CANCELLATION_MARKERS = (
    "لغو سفارش",
    "درخواست لغو",
    "تقاضا لغو",
    "تقاضای لغو",
    "لغو کنید",
    "لغو کن",
    "لغو شود",
    "لغو بشه",
    "لغو بشود",
    "لغو دار",
    "کنسل شود",
    "کنسل بشه",
    "کنسل بشود",
    "مشتری درخواست لغو",
    "مشتری تقاضای لغو",
    "سفارش را لغو کنید",
    "لطفاً لغو کنید",
    "لطفا لغو کنید",
    "امکان لغو",
    "ابطال سفارش",
    "cancel order",
    "cancellation_request",
    "cancel_order",
)

_CANCELLATION_SUBSTRINGS = (
    "لغو شود",
    "لغو بشه",
    "لغو بشود",
    "لغو دار",
    "کنسل شود",
    "کنسل بشه",
    "تقاضا لغو",
    "تقاضای لغو",
    "درخواست لغو",
    "لغو سفارش",
)

_CANCELLATION_REASON_PHRASES = (
    "دلیل لغو",
    "علت لغو",
    "چرا می‌خواهید لغو",
    "چرا میخواهید لغو",
    "دلیل درخواست لغو",
)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def is_cancellation_request_message(seller_text: str) -> bool:
    """True when seller requests order cancellation (overrides shipment/delivery signals)."""
    normalized = seller_text.strip().lower()
    if not normalized:
        return False
    if _has_any(normalized, _CANCELLATION_MARKERS):
        return True
    if _has_any(normalized, _CANCELLATION_SUBSTRINGS):
        return True
    if re.search(r"سفارش.{0,40}لغو", normalized):
        return True
    if re.search(r"لغو.{0,40}سفارش", normalized):
        return True
    return "لغو" in normalized and "سفارش" in normalized


def draft_asks_cancellation_reason(draft: str) -> bool:
    """True when draft asks for cancellation reason/details (forbidden when order id exists)."""
    normalized = draft.strip().lower()
    if not normalized:
        return False
    if _has_any(normalized, _CANCELLATION_REASON_PHRASES):
        return True
    return any(
        token in normalized for token in ("دلیل", "علت", "جزئیات", "توضیح بیشتر", "توضیحات بیشتر")
    )
