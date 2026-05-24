"""Deterministic Persian/domain query normalization for sandbox knowledge hints."""

from __future__ import annotations

# Longest phrases first so partial overlaps resolve predictably.
_PHRASE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("تصفیه حساب", "تسویه حساب"),
    ("تصفیه پنل", "تسویه حساب فروشنده"),
    ("قسمت تصفیه", "بخش تسویه حساب"),
    ("پول واریز نشده", "وضعیت تسویه فروشنده"),
    ("واریزی نیومده", "وضعیت تسویه فروشنده"),
    ("پولم نیومده", "وضعیت تسویه فروشنده"),
    ("پرداخت فروشنده", "تسویه حساب فروشنده"),
    ("کیف پول", "تسویه حساب فروشنده"),
    ("برداشت", "تسویه حساب فروشنده"),
    ("کالای غیر اصل", "کالای غیراصل"),
    ("فیک", "کالای غیراصل"),
    ("تقلبی", "کالای غیراصل"),
    ("ثبت کالا", "قوانین انتشار کالا"),
    ("انتشار کالا", "قوانین انتشار کالا"),
    ("تایید کالا", "قوانین انتشار کالا"),
)

_SETTLEMENT_EXPANSION = "تسویه حساب فروشنده"
_PRODUCT_PUBLISHING_EXPANSION = "قوانین انتشار کالا"
_PROHIBITED_GOODS_EXPANSION = "کالای غیراصل"

_SETTLEMENT_TRIGGERS = (
    "تسویه",
    "وضعیت تسویه فروشنده",
    "تسویه حساب",
    "واریز",
    "برداشت",
    "کیف پول",
)
_PRODUCT_TRIGGERS = (
    "قوانین انتشار کالا",
    "انتشار",
    "ثبت کالا",
)
_PROHIBITED_TRIGGERS = (
    "غیراصل",
    "غیر اصل",
    "تقلبی",
)


def normalize_persian_support_query(text: str) -> str:
    """Apply explicit Persian vendor-support spelling/synonym replacements."""
    normalized = text.strip()
    if not normalized:
        return ""
    for source, target in _PHRASE_REPLACEMENTS:
        normalized = normalized.replace(source, target)
    return normalized.strip()


def build_domain_query_expansions(text: str) -> list[str]:
    """Return short domain intent phrases implied by normalized query text."""
    normalized = normalize_persian_support_query(text)
    if not normalized:
        return []

    expansions: list[str] = []
    if any(trigger in normalized for trigger in _SETTLEMENT_TRIGGERS):
        expansions.append(_SETTLEMENT_EXPANSION)
    if any(trigger in normalized for trigger in _PRODUCT_TRIGGERS):
        expansions.append(_PRODUCT_PUBLISHING_EXPANSION)
    if any(trigger in normalized for trigger in _PROHIBITED_TRIGGERS):
        expansions.append(_PROHIBITED_GOODS_EXPANSION)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in expansions:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped
