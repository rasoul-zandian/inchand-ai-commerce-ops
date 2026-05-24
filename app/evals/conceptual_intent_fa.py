"""Exploratory Persian conceptual intent labels for draft review (not workflow routing)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.hitl.ticket_text_preview import _contains_unredacted_pii
from app.llm.types import LLMMessage
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits

CONCEPTUAL_INTENT_MAX_WORDS = 4
CONCEPTUAL_INTENT_MAX_CHARS = 40
DEFAULT_DRAFT_MAX_CHARS = 700

_PERSIAN_CHAR_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_HEAVY_PUNCTUATION_RE = re.compile(r"[.!?;:،]{3,}")
_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

_ACTION_REQUEST_VERBS = (
    "ثبت کنید",
    "ثبت کن",
    "تغییر بدید",
    "تغییر بده",
    "تغییر دهید",
    "تایید کنید",
    "تأیید کنید",
    "بررسی کنید",
    "پیگیری کنید",
    "اصلاح کنید",
    "ویرایش کنید",
    "بزنید",
    "کنید",
)

_GENERIC_CONCEPTUAL_LABELS = frozenset(
    {
        "بررسی درخواست فروشنده",
        "سوال درباره کالا",
        "سوال درباره قوانین",
        "استعلام وضعیت سفارش",
        "استعلام وضعیت کالا",
        "پشتیبانی عمومی فروشنده",
        "نیت نامشخص",
    },
)

# Review-facing fallbacks when the model omits or returns an invalid label.
_DETECTED_INTENT_FALLBACK_FA: dict[str, str] = {
    "settlement_status_inquiry": "پیگیری تسویه حساب",
    "settlement_panel_access_issue": "مشکل پنل تسویه",
    "product_approval_review": "درخواست تایید کالا",
    "product_publishing_question": "سوال انتشار کالا",
    "prohibited_goods_question": "سوال کالای ممنوعه",
    "delivery_confirmation_request": "ثبت تحویل سفارش",
    "tracking_code_notification": "اطلاع کد رهگیری",
    "order_status_review": "تغییر وضعیت سفارش",
    "seller_notification": "اطلاع فروشنده",
    "seller_operational_request": "درخواست عملیاتی فروشنده",
    "complaint_escalation": "پیگیری شکایت",
    "general_vendor_support": "پشتیبانی عمومی فروشنده",
    "unknown": "نیت نامشخص",
}

_LLMGenerateFn = Any


@dataclass(frozen=True)
class DraftWithConceptualIntent:
    """Internal draft generation result for operator review."""

    draft_reply: str
    conceptual_intent_fa: str


def normalize_conceptual_intent_label(label: str) -> str:
    """Normalize a conceptual intent label for display and future dictionary aggregation."""
    cleaned = " ".join(label.strip().split())
    cleaned = cleaned.strip("«»\"'[](){}،,.!?;:")
    return cleaned


def _word_count(text: str) -> int:
    return len([part for part in text.split() if part.strip()])


def is_generic_conceptual_label(label: str) -> bool:
    """True when label summarizes topic instead of a specific operational request."""
    normalized = normalize_conceptual_intent_label(label)
    if not normalized:
        return True
    if normalized in _GENERIC_CONCEPTUAL_LABELS:
        return True
    if normalized.startswith("سوال درباره"):
        return True
    if normalized.startswith("استعلام وضعیت"):
        return True
    if normalized.startswith("بررسی درخواست"):
        return True
    return False


def extract_operational_request_phrase(source_text: str) -> str | None:
    """Lightweight rule-assisted guess of the seller's requested operational action."""
    if not source_text or not source_text.strip():
        return None
    text = normalize_persian_arabic_digits(source_text.strip())
    lowered = text.lower()

    has_action_verb = any(verb in lowered for verb in _ACTION_REQUEST_VERBS)
    mentions_order = "سفارش" in lowered
    mentions_product = "کالا" in lowered or "محصول" in lowered
    mentions_delivery = "تحویل" in lowered or "تحويل" in lowered
    mentions_settlement = "تسویه" in lowered or "تصفیه" in lowered
    mentions_refund = "مرجوعی" in lowered or "مرجوع" in lowered
    mentions_approval = "تایید" in lowered or "تأیید" in lowered
    mentions_edit = "ویرایش" in lowered or "اصلاح" in lowered

    if mentions_delivery and mentions_order:
        if has_action_verb or "تحویل شده" in lowered or "تحويل شده" in lowered:
            if "تغییر" in lowered or "ثبت" in lowered or "بزن" in lowered:
                return "ثبت تحویل سفارش"
        if "تغییر" in lowered and "وضعیت" in lowered:
            return "تغییر وضعیت سفارش"

    if mentions_approval and mentions_product:
        if (
            "نشده" in lowered
            or "نکرد" in lowered
            or "نمی" in lowered
            or "درخواست" in lowered
            or has_action_verb
        ):
            return "درخواست تایید کالا"

    if mentions_refund:
        return "پیگیری مرجوعی سفارش"

    if mentions_edit and mentions_product:
        return "درخواست ویرایش کالا"

    if mentions_settlement:
        if (
            "چرا" in lowered
            or "نشده" in lowered
            or "نکرد" in lowered
            or "واریز" in lowered
            or "پیگیری" in lowered
            or has_action_verb
        ):
            return "پیگیری تسویه حساب"

    if mentions_order and has_action_verb and ("وضعیت" in lowered or mentions_delivery):
        return "تغییر وضعیت سفارش"

    if has_action_verb and mentions_product and mentions_approval:
        return "درخواست تایید کالا"

    return None


def operational_intent_hint_for_prompt(source_text: str) -> str | None:
    """Optional hint line injected into draft prompts to steer conceptual_intent_fa."""
    phrase = extract_operational_request_phrase(source_text)
    if phrase:
        return phrase
    return None


def assert_conceptual_intent_safe(label: str) -> None:
    """Reject conceptual intent labels that are unsafe or unusable for review."""
    text = normalize_conceptual_intent_label(label)
    if not text:
        raise ValueError("conceptual_intent_fa must be non-empty")
    if len(text) > CONCEPTUAL_INTENT_MAX_CHARS:
        raise ValueError(f"conceptual_intent_fa exceeds max length {CONCEPTUAL_INTENT_MAX_CHARS}")
    if _word_count(text) > CONCEPTUAL_INTENT_MAX_WORDS:
        raise ValueError(f"conceptual_intent_fa exceeds max words {CONCEPTUAL_INTENT_MAX_WORDS}")
    if not _PERSIAN_CHAR_RE.search(text):
        raise ValueError("conceptual_intent_fa must contain Persian-readable text")
    if _HEAVY_PUNCTUATION_RE.search(text):
        raise ValueError("conceptual_intent_fa must not be punctuation-heavy")
    if sum(1 for ch in text if ch in ".!?;:،") > 2:
        raise ValueError("conceptual_intent_fa must not be punctuation-heavy")
    if _contains_unredacted_pii(text):
        raise ValueError("conceptual_intent_fa contains unredacted PII-like patterns")


def fallback_conceptual_intent_fa(
    detected_intent: str,
    *,
    source_text: str | None = None,
) -> str:
    """Map rule-based ``detected_intent`` to a short Persian review label."""
    hint = extract_operational_request_phrase(source_text or "")
    if hint:
        return hint
    key = detected_intent.strip().lower()
    mapped = _DETECTED_INTENT_FALLBACK_FA.get(key, "پشتیبانی عمومی فروشنده")
    if is_generic_conceptual_label(mapped) and hint:
        return hint
    return mapped


def resolve_conceptual_intent_fa(
    raw_label: str | None,
    *,
    detected_intent: str,
    source_text: str | None = None,
    operational_hint: str | None = None,
) -> str:
    """Validate model label; prefer operational phrasing over topic summaries."""
    hint = operational_hint or extract_operational_request_phrase(source_text or "")

    if raw_label:
        try:
            normalized = normalize_conceptual_intent_label(raw_label)
            assert_conceptual_intent_safe(normalized)
            if hint and is_generic_conceptual_label(normalized):
                return hint
            if not is_generic_conceptual_label(normalized):
                return normalized
        except ValueError:
            pass

    if hint:
        return hint
    return fallback_conceptual_intent_fa(detected_intent, source_text=source_text)


def _strip_json_fences(content: str) -> str:
    text = content.strip()
    text = _JSON_FENCE_RE.sub("", text).strip()
    return text


def parse_draft_generation_content(
    content: str,
    *,
    detected_intent: str,
    max_chars: int = DEFAULT_DRAFT_MAX_CHARS,
    source_text: str | None = None,
    operational_hint: str | None = None,
) -> DraftWithConceptualIntent:
    """Parse JSON ``{conceptual_intent_fa, draft_reply}`` or plain-text draft fallback."""
    stripped = _strip_json_fences(content)
    conceptual_raw: str | None = None
    draft_raw: str | None = None

    if stripped.startswith("{"):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            ci = payload.get("conceptual_intent_fa")
            dr = payload.get("draft_reply")
            if isinstance(ci, str):
                conceptual_raw = ci
            if isinstance(dr, str):
                draft_raw = dr

    if draft_raw is None:
        draft_raw = stripped

    if not isinstance(draft_raw, str) or not draft_raw.strip():
        raise ValueError("draft_reply must be non-empty")

    from app.evals.offline_draft_generation import _truncate_draft, assert_draft_reply_safe

    draft = _truncate_draft(draft_raw, max_chars=max_chars)
    assert_draft_reply_safe(draft, max_chars=max_chars)
    conceptual = resolve_conceptual_intent_fa(
        conceptual_raw,
        detected_intent=detected_intent,
        source_text=source_text,
        operational_hint=operational_hint,
    )
    return DraftWithConceptualIntent(draft_reply=draft, conceptual_intent_fa=conceptual)


def generate_draft_with_conceptual_intent(
    messages: list[LLMMessage],
    *,
    detected_intent: str,
    provider: str,
    model: str,
    generate_fn: _LLMGenerateFn | None = None,
    max_chars: int = DEFAULT_DRAFT_MAX_CHARS,
    source_text: str | None = None,
    operational_hint: str | None = None,
) -> DraftWithConceptualIntent:
    """Call LLM and return draft plus exploratory Persian conceptual intent."""
    if generate_fn is None:
        from app.llm.factory import generate_text

        fn = generate_text
    else:
        fn = generate_fn
    response = fn(messages, provider=provider, model=model)
    content = getattr(response, "content", response)
    if not isinstance(content, str):
        raise ValueError("LLM response content must be a string")
    return parse_draft_generation_content(
        content,
        detected_intent=detected_intent,
        max_chars=max_chars,
        source_text=source_text,
        operational_hint=operational_hint,
    )


def draft_generation_json_instruction() -> str:
    """System-prompt fragment requesting structured draft output."""
    return (
        "- خروجی را فقط به‌صورت یک شیء JSON معتبر برگردان (بدون markdown یا توضیح اضافه):\n"
        '  {"conceptual_intent_fa": "...", "draft_reply": "..."}\n'
        "- conceptual_intent_fa: نیت مفهومی را بر اساس اقدام یا درخواستی که فروشنده "
        "از پشتیبانی دارد بنویس، نه موضوع کلی متن. حداکثر ۴ کلمه فارسی؛ "
        "برای اپراتور قابل فهم باشد، نه enum انگلیسی.\n"
        "- از عبارات کلی مثل «بررسی درخواست فروشنده»، «سوال درباره کالا»، "
        "«استعلام وضعیت سفارش» پرهیز کن.\n"
        "- نمونه‌ها:\n"
        "  - «لطفا وضعیت سفارش را تحویل شده کنید» → «ثبت تحویل سفارش»\n"
        "  - «کالای من تایید نشده» → «درخواست تایید کالا»\n"
        "  - «مرجوعی این سفارش را بررسی کنید» → «پیگیری مرجوعی سفارش»\n"
        "  - «چرا تسویه انجام نشده؟» → «پیگیری تسویه حساب»\n"
        "- draft_reply: متن پیش‌نویس پاسخ فارسی به فروشنده."
    )


def operational_intent_prompt_block(source_text: str) -> str:
    """User-prompt block steering conceptual_intent_fa toward operational requests."""
    hint = operational_intent_hint_for_prompt(source_text)
    if not hint:
        return ""
    return f"راهنمای نیت عملیاتی (فقط برای conceptual_intent_fa — اقدام درخواستی فروشنده): {hint}\n"
