"""Operational short and policy explanation draft style — prompt instructions and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

DRAFT_STYLE_OPERATIONAL_SHORT = "operational_short"
DRAFT_STYLE_POLICY_EXPLANATION = "policy_explanation"

DEFAULT_DRAFT_MAX_SENTENCES = 2
DEFAULT_DRAFT_TARGET_MAX_CHARS = 180
DEFAULT_DRAFT_HARD_MAX_CHARS = 300

POLICY_EXPLANATION_DEFAULT_MAX_SENTENCES = 4
POLICY_EXPLANATION_DEFAULT_TARGET_MAX_CHARS = 600
POLICY_EXPLANATION_DEFAULT_HARD_MAX_CHARS = 700

_BANNED_FLUFFY_PHRASES = (
    "درخواست شما با موفقیت ثبت شد",
    "در اسرع وقت",
    "نتیجه اطلاع‌رسانی خواهد شد",
    "از صبر و شکیبایی شما سپاسگزاریم",
    "طبق قوانین و مقررات",
    "کارشناسان مربوطه",
    "همراهی شما",
)

_GENERIC_POLICY_REFERRAL_PHRASES = (
    "به راهنمای سایت مراجعه",
    "به راهنما مراجعه",
    "فقط به راهنما",
    "در سایت مراجعه کنید",
    "به سایت مراجعه",
)

_SENTENCE_SPLIT_RE = re.compile(r"[.!?؟!\n]+")


@dataclass(frozen=True)
class DraftStyleValidationResult:
    draft_style: str
    draft_char_count: int
    draft_sentence_count: int
    draft_style_ok: bool
    draft_style_warnings: tuple[str, ...]


def build_draft_style_instruction(
    style: str,
    *,
    max_sentences: int = DEFAULT_DRAFT_MAX_SENTENCES,
    target_max_chars: int = DEFAULT_DRAFT_TARGET_MAX_CHARS,
) -> str:
    """Persian system-prompt fragment for draft style."""
    if style == DRAFT_STYLE_POLICY_EXPLANATION:
        return (
            f"- سبک پاسخ: policy_explanation — تا {max_sentences} جمله، "
            f"هدف حدود {target_max_chars} کاراکتر.\n"
            "- پاسخ را کامل و شفاف بده؛ متن قانون مرتبط را توضیح بده.\n"
            "- خلاصه‌سازی بیش از حد یا ارجاع کلی به راهنما نده.\n"
            "- زمان‌بندی/قواعد تسویه و نهایی شدن را صریح بنویس.\n"
            "- از متن راهنمای سیاست استفاده کن؛ وعده اجرا یا زمان ساختگی نساز."
        )
    if style != DRAFT_STYLE_OPERATIONAL_SHORT:
        return ""
    return (
        f"- سبک پاسخ: operational_short — حداکثر {max_sentences} جمله، "
        f"هدف حدود {target_max_chars} کاراکتر.\n"
        "- پاسخ را حداکثر در ۱ تا ۲ جمله بنویس.\n"
        "- کوتاه، عملیاتی، محترمانه.\n"
        "- تعارف، توضیح اضافه، قول قطعی، یا متن کلیشه‌ای ننویس.\n"
        "- اگر نیاز به بررسی انسانی است، کوتاه بگو: "
        "«برای بررسی به تیم مربوطه ارجاع شد.»\n"
        "- اگر شناسه‌ای در پیام اول وجود ندارد، هیچ شناسه‌ای ذکر نکن."
    )


def merge_style_and_completion_instructions(
    style: str,
    *,
    max_sentences: int = DEFAULT_DRAFT_MAX_SENTENCES,
    target_max_chars: int = DEFAULT_DRAFT_TARGET_MAX_CHARS,
) -> str:
    """Style block plus completion and evidence wording calibration instructions."""
    from app.evals.draft_completion_calibration import build_completion_calibration_instruction
    from app.evals.draft_evidence_wording_calibration import (
        build_photo_evidence_wording_instruction,
    )

    base = build_draft_style_instruction(
        style,
        max_sentences=max_sentences,
        target_max_chars=target_max_chars,
    )
    if not base:
        return base
    parts = [
        base,
        build_completion_calibration_instruction(),
        build_photo_evidence_wording_instruction(),
    ]
    return "\n".join(parts)


def resolve_effective_draft_style(
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
    base_style: str = DRAFT_STYLE_OPERATIONAL_SHORT,
) -> str:
    """Choose operational_short vs policy_explanation from seller context."""
    from app.evals.draft_completion_calibration import is_informational_question
    from app.knowledge.policy_fact_extraction import (
        is_settlement_account_operational_request,
        is_settlement_timing_policy_question,
    )
    from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

    if is_settlement_account_operational_request(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return base_style

    action = (suggested_action or "").strip().lower()
    if action == "answer_policy_question":
        return DRAFT_STYLE_POLICY_EXPLANATION

    intent = (detected_intent or "").strip().lower()
    if intent == VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value:
        if is_settlement_timing_policy_question(
            seller_text,
            detected_intent=detected_intent,
            conceptual_intent_fa=conceptual_intent_fa,
            suggested_action=suggested_action,
        ):
            return DRAFT_STYLE_POLICY_EXPLANATION
        return base_style

    if intent in {
        VendorTicketIntent.PROHIBITED_GOODS_QUESTION.value,
        VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION.value,
    }:
        return DRAFT_STYLE_POLICY_EXPLANATION

    if is_informational_question(seller_text, detected_intent=detected_intent):
        if "تسویه" in seller_text and not is_settlement_timing_policy_question(
            seller_text,
            detected_intent=detected_intent,
            conceptual_intent_fa=conceptual_intent_fa,
            suggested_action=suggested_action,
        ):
            return base_style
        return DRAFT_STYLE_POLICY_EXPLANATION
    return base_style


def count_persian_sentences(text: str) -> int:
    """Approximate sentence count (Persian/Latin terminators and newlines)."""
    cleaned = text.strip()
    if not cleaned:
        return 0
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]
    return max(1, len(parts))


def validate_operational_short_draft(
    text: str,
    *,
    target_max_chars: int = DEFAULT_DRAFT_TARGET_MAX_CHARS,
    hard_max_chars: int = DEFAULT_DRAFT_HARD_MAX_CHARS,
    max_sentences: int = DEFAULT_DRAFT_MAX_SENTENCES,
    style: str = DRAFT_STYLE_OPERATIONAL_SHORT,
) -> DraftStyleValidationResult:
    """Validate draft length, sentence count, and banned generic phrases."""
    draft = text.strip()
    warnings: list[str] = []
    char_count = len(draft)
    sentence_count = count_persian_sentences(draft)

    if char_count > hard_max_chars:
        warnings.append(f"exceeds hard max {hard_max_chars} chars")
    elif char_count > target_max_chars:
        warnings.append(f"exceeds target {target_max_chars} chars")

    if sentence_count > max_sentences:
        warnings.append(f"exceeds max {max_sentences} sentences")

    for phrase in _BANNED_FLUFFY_PHRASES:
        if phrase in draft:
            warnings.append(f"banned phrase: {phrase}")

    ok = not warnings
    return DraftStyleValidationResult(
        draft_style=style,
        draft_char_count=char_count,
        draft_sentence_count=sentence_count,
        draft_style_ok=ok,
        draft_style_warnings=tuple(warnings),
    )


def validate_policy_explanation_draft(
    text: str,
    *,
    target_max_chars: int = POLICY_EXPLANATION_DEFAULT_TARGET_MAX_CHARS,
    hard_max_chars: int = POLICY_EXPLANATION_DEFAULT_HARD_MAX_CHARS,
    max_sentences: int = POLICY_EXPLANATION_DEFAULT_MAX_SENTENCES,
    style: str = DRAFT_STYLE_POLICY_EXPLANATION,
) -> DraftStyleValidationResult:
    """Validate longer policy answers — allow more length, forbid generic referral."""
    draft = text.strip()
    warnings: list[str] = []
    char_count = len(draft)
    sentence_count = count_persian_sentences(draft)

    if char_count > hard_max_chars:
        warnings.append(f"exceeds hard max {hard_max_chars} chars")
    if sentence_count > max_sentences:
        warnings.append(f"exceeds max {max_sentences} sentences")
    if char_count < 80:
        warnings.append("policy answer too short/vague")

    for phrase in _GENERIC_POLICY_REFERRAL_PHRASES:
        if phrase in draft:
            warnings.append(f"generic policy referral: {phrase}")

    for phrase in _BANNED_FLUFFY_PHRASES:
        if phrase in draft:
            warnings.append(f"banned phrase: {phrase}")

    ok = not warnings
    return DraftStyleValidationResult(
        draft_style=style,
        draft_char_count=char_count,
        draft_sentence_count=sentence_count,
        draft_style_ok=ok,
        draft_style_warnings=tuple(warnings),
    )


def draft_style_metadata_row(
    validation: DraftStyleValidationResult,
) -> dict[str, str | int | bool | list[str]]:
    """Serialize style validation for JSONL / operator preview."""
    return {
        "draft_style": validation.draft_style,
        "draft_char_count": validation.draft_char_count,
        "draft_sentence_count": validation.draft_sentence_count,
        "draft_style_ok": validation.draft_style_ok,
        "draft_style_warnings": list(validation.draft_style_warnings),
    }


def resolve_draft_style_limits(settings: Any) -> tuple[str, int, int, int]:
    """Return (style, max_sentences, target_chars, hard_chars) from AppSettings."""
    style = getattr(settings, "draft_style", DRAFT_STYLE_OPERATIONAL_SHORT) or (
        DRAFT_STYLE_OPERATIONAL_SHORT
    )
    max_sentences = int(getattr(settings, "draft_max_sentences", DEFAULT_DRAFT_MAX_SENTENCES))
    target_chars = int(
        getattr(settings, "draft_target_max_chars", DEFAULT_DRAFT_TARGET_MAX_CHARS),
    )
    hard_chars = int(getattr(settings, "draft_hard_max_chars", DEFAULT_DRAFT_HARD_MAX_CHARS))
    return style.strip(), max_sentences, target_chars, hard_chars


def resolve_effective_draft_style_limits(
    settings: Any,
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
) -> tuple[str, int, int, int]:
    """Return style limits after applying policy_explanation override when needed."""
    base_style, max_sentences, target_chars, hard_chars = resolve_draft_style_limits(settings)
    effective_style = resolve_effective_draft_style(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
        base_style=base_style,
    )
    if effective_style != DRAFT_STYLE_POLICY_EXPLANATION:
        return effective_style, max_sentences, target_chars, hard_chars
    return (
        effective_style,
        int(
            getattr(
                settings, "policy_draft_max_sentences", POLICY_EXPLANATION_DEFAULT_MAX_SENTENCES
            )
        ),
        int(
            getattr(
                settings,
                "policy_draft_target_max_chars",
                POLICY_EXPLANATION_DEFAULT_TARGET_MAX_CHARS,
            ),
        ),
        int(
            getattr(
                settings, "policy_draft_hard_max_chars", POLICY_EXPLANATION_DEFAULT_HARD_MAX_CHARS
            )
        ),
    )


def apply_draft_style_checks(
    draft: str,
    settings: Any,
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    suggested_action: str | None = None,
) -> DraftStyleValidationResult:
    """Run style validation using context-aware effective style limits."""
    style, max_sentences, target_chars, hard_chars = resolve_effective_draft_style_limits(
        settings,
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
    )
    if style == DRAFT_STYLE_POLICY_EXPLANATION:
        return validate_policy_explanation_draft(
            draft,
            target_max_chars=target_chars,
            hard_max_chars=hard_chars,
            max_sentences=max_sentences,
            style=style,
        )
    if style != DRAFT_STYLE_OPERATIONAL_SHORT:
        return DraftStyleValidationResult(
            draft_style=style,
            draft_char_count=len(draft.strip()),
            draft_sentence_count=count_persian_sentences(draft),
            draft_style_ok=True,
            draft_style_warnings=(),
        )
    return validate_operational_short_draft(
        draft,
        target_max_chars=target_chars,
        hard_max_chars=hard_chars,
        max_sentences=max_sentences,
        style=style,
    )


def apply_operational_short_style_checks(
    draft: str,
    settings: Any,
) -> DraftStyleValidationResult:
    """Run style validation using settings-backed limits (legacy entry point)."""
    return apply_draft_style_checks(draft, settings)
