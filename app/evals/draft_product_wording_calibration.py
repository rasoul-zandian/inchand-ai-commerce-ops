"""Normalize explicit product/category names in drafts to generic کالا wording."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.evals.draft_style import DRAFT_STYLE_POLICY_EXPLANATION

_EXPLICIT_PRODUCT_TERMS: tuple[str, ...] = (
    "بازی",
    "ادکلن",
    "عطر",
    "کتاب",
    "موبایل",
    "گوشی",
    "ساعت",
    "کفش",
    "لباس",
    "کیف",
    "لپ‌تاپ",
    "لپ تاپ",
    "هدفون",
    "لوازم جانبی",
    "قطعه",
    "قطعات",
)

_PRODUCT_WORKFLOW_ACTIONS = frozenset(
    {
        "check_product_approval",
        "review_product_edit",
        "review_product_status",
    },
)

_SELLER_PRODUCT_WORKFLOW_MARKERS = (
    "تایید کالا",
    "تأیید کالا",
    "ویرایش کالا",
    "شناسه کالا",
    "محصول",
    "کالا",
    "بارگذاری",
    "انتشار",
    "رد شد",
    "رد شدند",
    "تایید نشده",
    "نیاز به بررسی",
    "تعریف شده",
    "بررسی مجدد",
    "علت رد",
    "عدم تایید",
    "عدم تأیید",
)

_CONTEXT_PREFIXES = (
    "شناسه",
    "اصلاح",
    "تایید",
    "تأیید",
    "بررسی",
    "رد شدن",
    "رد شد",
    "انتشار",
    "بارگذاری",
    "نیاز به اصلاح",
    "علت نیاز به اصلاح",
)

_PHRASE_PREFIXES_PLURAL: tuple[tuple[str, str], ...] = (
    ("علت نیاز به اصلاح ", "علت نیاز به اصلاح کالاها"),
    ("نیاز به اصلاح ", "نیاز به اصلاح کالاها"),
    ("شناسه ", "شناسه کالاها"),
    ("بررسی ", "بررسی کالاها"),
    ("تایید ", "تایید کالاها"),
    ("تأیید ", "تأیید کالاها"),
    ("رد شدن ", "رد شدن کالاها"),
    ("رد شد ", "رد شدن کالاها"),
    ("اصلاح ", "اصلاح کالاها"),
    ("انتشار ", "انتشار کالاها"),
    ("بارگذاری ", "بارگذاری کالاها"),
)

_PHRASE_PREFIXES_SINGULAR: tuple[tuple[str, str], ...] = (("شناسه ", "شناسه کالا"),)


@dataclass(frozen=True)
class ProductWordingCalibrationResult:
    """Outcome of product reference wording normalization."""

    original_draft: str
    calibrated_draft: str
    explicit_product_terms_detected: tuple[str, ...] = ()
    replacements_applied: tuple[str, ...] = ()
    product_wording_normalized: bool = False


@dataclass(frozen=True)
class ProductWordingContext:
    """Inputs for deciding whether product wording calibration applies."""

    seller_text: str = ""
    detected_intent: str | None = None
    suggested_action: str | None = None
    conceptual_intent_fa: str | None = None
    draft_style: str | None = None
    product_ids: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)


def _normalize_action(action: str | None) -> str:
    return (action or "").strip().lower()


def _term_variants(term: str) -> tuple[str, str]:
    """Return (singular, plural) surface forms for a product term."""
    base = term.strip()
    if not base:
        return "", ""
    plural_forms = (
        f"{base}‌ها",
        f"{base} ها",
        f"{base}\u200cها",
    )
    if base.endswith("ات") or base == "قطعات":
        return base, base
    if base.endswith("ه"):
        return base, plural_forms[0]
    return base, plural_forms[0]


def detect_explicit_product_terms(text: str) -> list[str]:
    """Return explicit product/category terms found in Persian or mixed text."""
    blob = (text or "").strip()
    if not blob:
        return []
    normalized = blob.lower()
    found: list[str] = []
    for term in sorted(_EXPLICIT_PRODUCT_TERMS, key=len, reverse=True):
        if term in normalized or term in blob:
            found.append(term)
    return found


def is_product_support_context(
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    draft_style: str | None = None,
    product_ids: Sequence[str] = (),
) -> bool:
    """True when draft/source context indicates product listing workflow."""
    from app.workflows.operational_information_sufficiency import (
        _SCENARIO_PRODUCT_APPROVAL,
        detect_operational_scenario,
    )

    if draft_style == DRAFT_STYLE_POLICY_EXPLANATION:
        scenario = detect_operational_scenario(
            seller_text=seller_text,
            detected_intent=detected_intent,
            suggested_action=suggested_action,
            conceptual_intent_fa=conceptual_intent_fa,
        )
        if scenario != _SCENARIO_PRODUCT_APPROVAL:
            return False

    scenario = detect_operational_scenario(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    if scenario == _SCENARIO_PRODUCT_APPROVAL:
        return True

    action = _normalize_action(suggested_action)
    intent = (detected_intent or "").strip().lower()
    if action in _PRODUCT_WORKFLOW_ACTIONS or "product" in intent:
        return True

    conceptual = (conceptual_intent_fa or "").strip()
    if any(token in conceptual for token in ("تایید کالا", "تأیید کالا", "ویرایش کالا")):
        return True

    seller = (seller_text or "").strip()
    if not seller:
        return False
    if _has_any(seller, _SELLER_PRODUCT_WORKFLOW_MARKERS) and detect_explicit_product_terms(
        seller,
    ):
        return True
    if detect_explicit_product_terms(seller) and _has_any(
        seller,
        ("تعریف شده", "نیاز به بررسی", "تایید نشده", "رد شد", "بارگذاری", "انتشار"),
    ):
        return True
    if product_ids and detect_explicit_product_terms(seller):
        return True
    return False


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _apply_phrase_replacement(
    draft: str,
    *,
    singular: str,
    plural: str,
    replacements_applied: list[str],
) -> str:
    result = draft
    forms = (
        (plural, _PHRASE_PREFIXES_PLURAL),
        (singular, _PHRASE_PREFIXES_SINGULAR),
    )
    for form, prefixes in forms:
        if not form or form in ("محصول", "قطعات"):
            continue
        if form not in result:
            continue
        for prefix, replacement in prefixes:
            needle = f"{prefix}{form}"
            if needle in result:
                result = result.replace(needle, replacement)
                replacements_applied.append(f"{needle}->{replacement}")
    return result


def _apply_contextual_term_swap(
    draft: str,
    term: str,
    *,
    replacements_applied: list[str],
) -> str:
    singular, plural = _term_variants(term)
    if not singular or singular in ("محصول",):
        return draft
    result = draft
    for prefix in _CONTEXT_PREFIXES:
        for form, target in ((plural, "کالاها"), (singular, "کالا")):
            if not form:
                continue
            pattern = rf"({re.escape(prefix)}\s+){re.escape(form)}"
            new_result = re.sub(pattern, rf"\g<1>{target}", result)
            if new_result != result:
                replacements_applied.append(f"{prefix}+{form}->{target}")
                result = new_result
    for form, target in ((plural, "کالاها"), (singular, "کالا")):
        if not form:
            continue
        pattern = rf"(?<=[\s،.؛:]){re.escape(form)}(?=[\s،.؛:!؟])"
        new_result = re.sub(pattern, target, result)
        if new_result != result:
            replacements_applied.append(f"standalone:{form}->{target}")
            result = new_result
    return result


def replace_product_specific_identifier_phrases(
    draft: str,
    *,
    terms: Sequence[str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Replace product-specific identifier phrasing with generic کالا wording."""
    text = (draft or "").strip()
    if not text:
        return "", ()

    active_terms = list(terms or detect_explicit_product_terms(text))
    if not active_terms:
        return text, ()

    replacements_applied: list[str] = []
    result = text
    for term in sorted(set(active_terms), key=len, reverse=True):
        singular, plural = _term_variants(term)
        if singular not in result and plural not in result:
            continue
        result = _apply_phrase_replacement(
            result,
            singular=singular,
            plural=plural,
            replacements_applied=replacements_applied,
        )
        result = _apply_contextual_term_swap(
            result,
            term,
            replacements_applied=replacements_applied,
        )

    return result, tuple(replacements_applied)


def calibrate_product_reference_wording(
    draft: str,
    source_text: str,
    context: ProductWordingContext | None = None,
) -> ProductWordingCalibrationResult:
    """Normalize product/category names in a support draft when product workflow applies."""
    original = (draft or "").strip()
    ctx = context or ProductWordingContext()
    seller = ctx.seller_text or source_text

    if not is_product_support_context(
        seller_text=seller,
        detected_intent=ctx.detected_intent,
        suggested_action=ctx.suggested_action,
        conceptual_intent_fa=ctx.conceptual_intent_fa,
        draft_style=ctx.draft_style,
        product_ids=ctx.product_ids,
    ):
        return ProductWordingCalibrationResult(
            original_draft=original,
            calibrated_draft=original,
            product_wording_normalized=False,
        )

    terms = tuple(
        dict.fromkeys(
            detect_explicit_product_terms(seller) + detect_explicit_product_terms(original),
        ),
    )
    if not terms:
        return ProductWordingCalibrationResult(
            original_draft=original,
            calibrated_draft=original,
            product_wording_normalized=False,
        )

    calibrated, replacements = replace_product_specific_identifier_phrases(
        original,
        terms=terms,
    )
    normalized = calibrated != original
    return ProductWordingCalibrationResult(
        original_draft=original,
        calibrated_draft=calibrated,
        explicit_product_terms_detected=terms,
        replacements_applied=replacements,
        product_wording_normalized=normalized,
    )


def apply_product_wording_calibration(
    draft: str,
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    draft_style: str | None = None,
    product_ids: Sequence[str] = (),
) -> tuple[str, ProductWordingCalibrationResult]:
    """Apply product wording calibration; returns (draft, result)."""
    result = calibrate_product_reference_wording(
        draft,
        seller_text,
        ProductWordingContext(
            seller_text=seller_text,
            detected_intent=detected_intent,
            suggested_action=suggested_action,
            conceptual_intent_fa=conceptual_intent_fa,
            draft_style=draft_style,
            product_ids=tuple(product_ids),
        ),
    )
    return result.calibrated_draft, result


def build_product_wording_prompt_instruction(
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    draft_style: str | None = None,
) -> str:
    """Persian/English prompt guardrail for generic کالا wording in product workflows."""
    if not is_product_support_context(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
        draft_style=draft_style,
    ):
        return ""
    return (
        "- برای ارجاع به کالاهای فروشنده از واژه‌های عمومی "
        "کالا / کالاها / شناسه کالا / شناسه کالاها استفاده کن.\n"
        "- نام دسته یا نوع کالا (مثل بازی، ادکلن، کتاب، موبایل) را "
        "در پاسخ پشتیبانی تکرار نکن.\n"
    )


def product_wording_metadata_row(result: ProductWordingCalibrationResult) -> dict[str, Any]:
    """Serialize product wording calibration for draft quality metadata."""
    return {
        "product_wording_normalized": result.product_wording_normalized,
        "explicit_product_terms_detected": list(result.explicit_product_terms_detected),
        "product_wording_replacements": list(result.replacements_applied),
    }
