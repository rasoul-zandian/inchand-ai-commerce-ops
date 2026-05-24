"""Informational reply completion — avoid unnecessary operational follow-up filler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.evals.draft_style import _SENTENCE_SPLIT_RE, count_persian_sentences
from app.workflows.suggested_action_taxonomy import _seller_asks_operational_action
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

_INFORMATIONAL_INTENT_VALUES = frozenset(
    {
        VendorTicketIntent.PROHIBITED_GOODS_QUESTION.value,
        VendorTicketIntent.PRODUCT_PUBLISHING_QUESTION.value,
        VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value,
    },
)

_POLICY_QUESTION_MARKERS = (
    "چند روز",
    "چقدر طول",
    "چه زمانی",
    "کی میتونم",
    "کی می‌تونم",
    "کی میتوانم",
    "کی می‌توانم",
    "چطور",
    "چگونه",
    "آیا میتوان",
    "آیا می‌توان",
    "آیا میشود",
    "آیا می‌شود",
    "قوانین",
    "مقررات",
    "سیاست",
    "مجاز است",
    "مجاز هست",
    "میتونم",
    "می‌تونم",
    "میتوانم",
    "می‌توانم",
    "چند روز دیگه",
    "چند روز دیگر",
    "بعد از خرید",
    "پس از خرید",
    "نهایی شدن سفارش",
)

_SPECIFIC_DELAY_COMPLAINT_MARKERS = (
    "هنوز واریز",
    "هنوز تسویه",
    "واریز نشده",
    "تسویه نشده",
    "تأخیر",
    "تاخیر",
    "دیر شده",
    "پیگیری کنید",
    "بررسی کنید",
)

_FOLLOWUP_IMPLIED_ACTIONS = frozenset(
    {
        "human_followup",
        "escalate",
        "billing_review",
        "check_order_status",
        "update_delivery_status",
        "check_product_approval",
        "review_product_edit",
        "check_return_request",
        "request_missing_info",
        "review_product_status",
        "route_review",
        "duplicate_check",
    },
)

_ESCALATION_INTENTS = frozenset(
    {
        VendorTicketIntent.COMPLAINT_ESCALATION.value,
        VendorTicketIntent.SELLER_OPERATIONAL_REQUEST.value,
        VendorTicketIntent.ORDER_STATUS_REVIEW.value,
        VendorTicketIntent.PRODUCT_APPROVAL_REVIEW.value,
        VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        VendorTicketIntent.SETTLEMENT_PANEL_ACCESS_ISSUE.value,
    },
)

_FILLER_SUBSTRINGS = (
    "لطفا صبر کنید",
    "لطفاً صبر کنید",
    "کمی صبر کنید",
    "لطفا کمی صبر",
    "لطفاً کمی صبر",
    "در حال بررسی",
    "مورد در حال بررسی",
    "بررسی لازم انجام شود",
    "بررسی لازم",
    "نتیجه اطلاع‌رسانی خواهد شد",
    "به تیم مربوطه ارجاع شد",
    "پیگیری خواهد شد",
    "پیگیری می‌شود",
    "پیگیری میشود",
    "اپراتور بررسی می‌کند",
    "اپراتور بررسی میکند",
)

_CONTACT_CLOSING_FILLER_MARKERS = (
    "در صورت نیاز به اطلاعات بیشتر، لطفاً با ما تماس بگیرید",
    "در صورت نیاز به اطلاعات بیشتر",
    "لطفاً با ما تماس بگیرید",
    "لطفا با ما تماس بگیرید",
    "اگر سوال دیگری داشتید",
    "اگر سؤال دیگری داشتید",
    "در صورت نیاز به راهنمایی بیشتر",
    "هر زمان سوالی داشتید",
    "لطفاً با ما در تماس باشید",
    "لطفا با ما در تماس باشید",
)

_CONTACT_SUPPORT_QUESTION_MARKERS = (
    "چطور تماس",
    "چگونه تماس",
    "چطور ارتباط",
    "چگونه ارتباط",
    "شماره تماس",
    "راه تماس",
    "با چه کسی تماس",
    "چطور پیگیری کنم",
    "چگونه پیگیری کنم",
    "چطور با پشتیبانی",
    "چگونه با پشتیبانی",
)

_QUESTION_MARKERS = ("؟", "?")


@dataclass(frozen=True)
class DraftCompletionCalibrationResult:
    """Outcome of optional trailing-filler cleanup."""

    draft_reply: str
    unnecessary_followup_detected: bool
    completion_calibration_applied: bool
    trailing_filler_removed: bool
    contact_closing_filler_removed: bool = False


def build_completion_calibration_instruction() -> str:
    """Persian prompt fragment for informational reply completion."""
    return (
        "- اگر پاسخ سوال فروشنده کامل و نهایی است، پاسخ را همان‌جا تمام کن.\n"
        "- وقتی هیچ بررسی یا اقدام انسانی لازم نیست، جمله پیگیری یا انتظار اضافه نکن.\n"
        "- برای سوال‌های اطلاعاتی (سیاست، زمان‌بندی تسویه، قوانین) فقط پاسخ factual بده.\n"
        "- پاسخ را بدون جمله پایانی عمومی مثل «تماس بگیرید» یا «اگر سوالی داشتید» تمام کن، "
        "مگر فروشنده صریحاً درباره راه تماس پرسیده باشد."
    )


def _normalize_intent(detected_intent: str | VendorTicketIntent | None) -> str | None:
    if detected_intent is None:
        return None
    if isinstance(detected_intent, VendorTicketIntent):
        return detected_intent.value
    text = str(detected_intent).strip().lower()
    return text or None


def _normalize_action(suggested_action: str | None) -> str:
    return (suggested_action or "").strip().lower()


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def is_informational_question(
    seller_text: str,
    *,
    detected_intent: str | VendorTicketIntent | None = None,
) -> bool:
    """True when the seller asks a factual/policy question (not an operational ask)."""
    text = seller_text.strip()
    if not text:
        return False
    if _seller_asks_operational_action(text):
        return False
    if _has_any(text, _SPECIFIC_DELAY_COMPLAINT_MARKERS):
        return False

    intent_value = _normalize_intent(detected_intent)
    if intent_value in _INFORMATIONAL_INTENT_VALUES:
        return True

    has_question = any(marker in text for marker in _QUESTION_MARKERS)
    has_policy_markers = _has_any(text, _POLICY_QUESTION_MARKERS)
    if has_question and has_policy_markers:
        return True
    if has_question and intent_value == VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value:
        return True
    return bool(has_policy_markers and "تسویه" in text and has_question)


def draft_requires_operational_followup(
    *,
    seller_text: str = "",
    suggested_action: str | None = None,
    detected_intent: str | VendorTicketIntent | None = None,
    entity_warnings_summary: str | None = None,
) -> bool:
    """True when the draft may include human-review / follow-up closure."""
    action = _normalize_action(suggested_action)
    if action in _FOLLOWUP_IMPLIED_ACTIONS:
        return True

    intent_value = _normalize_intent(detected_intent)
    if intent_value in _ESCALATION_INTENTS:
        return True

    if entity_warnings_summary and str(entity_warnings_summary).strip():
        return True

    if _seller_asks_operational_action(seller_text):
        return True

    if action == "answer_policy_question":
        return False

    if is_informational_question(seller_text, detected_intent=detected_intent):
        if action in ("monitor", "record_update", "check_settlement_status"):
            return False

    return action not in ("monitor", "record_update", "check_settlement_status", "")


def detect_unnecessary_followup_sentence(sentence: str) -> bool:
    """True if a sentence matches operational wait/review filler patterns."""
    cleaned = sentence.strip()
    if not cleaned:
        return False
    return any(substring in cleaned for substring in _FILLER_SUBSTRINGS)


def seller_explicitly_asked_contact_support(seller_text: str) -> bool:
    """True when seller explicitly asks how to contact support."""
    normalized = seller_text.strip().lower()
    if not normalized:
        return False
    return _has_any(normalized, _CONTACT_SUPPORT_QUESTION_MARKERS)


def detect_contact_closing_filler_sentence(sentence: str) -> bool:
    """True when a sentence is generic contact/closing filler."""
    cleaned = sentence.strip()
    if not cleaned:
        return False
    return _has_any(cleaned, _CONTACT_CLOSING_FILLER_MARKERS)


def strip_trailing_contact_closing_filler(
    draft: str,
    *,
    seller_text: str = "",
) -> tuple[str, bool]:
    """Remove trailing generic contact/closing filler unless seller asked how to contact."""
    if seller_explicitly_asked_contact_support(seller_text):
        return draft.strip(), False

    sentences = _split_sentences(draft)
    if not sentences:
        return draft.strip(), False
    if not detect_contact_closing_filler_sentence(sentences[-1]):
        return draft.strip(), False

    if len(sentences) == 1:
        return "", True

    cleaned = _rejoin_sentences(sentences[:-1]).strip()
    return cleaned, True


def _split_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    parts = [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]
    return parts


def _rejoin_sentences(sentences: list[str]) -> str:
    if not sentences:
        return ""
    text = ". ".join(sentences)
    if not text.endswith((".", "؟", "!", "؟")):
        text += "."
    return text


def detect_unnecessary_followup_in_draft(
    draft: str,
    *,
    seller_text: str = "",
    suggested_action: str | None = None,
    detected_intent: str | VendorTicketIntent | None = None,
    entity_warnings_summary: str | None = None,
) -> bool:
    """True if draft ends with filler that should not appear on informational replies."""
    if draft_requires_operational_followup(
        seller_text=seller_text,
        suggested_action=suggested_action,
        detected_intent=detected_intent,
        entity_warnings_summary=entity_warnings_summary,
    ):
        return False
    if not is_informational_question(seller_text, detected_intent=detected_intent):
        return False
    sentences = _split_sentences(draft)
    if not sentences:
        return False
    return detect_unnecessary_followup_sentence(sentences[-1])


def strip_unnecessary_trailing_followup(
    draft: str,
    *,
    seller_text: str = "",
    suggested_action: str | None = None,
    detected_intent: str | VendorTicketIntent | None = None,
    entity_warnings_summary: str | None = None,
) -> tuple[str, bool]:
    """Remove only the trailing filler sentence when informational completion applies."""
    if not detect_unnecessary_followup_in_draft(
        draft,
        seller_text=seller_text,
        suggested_action=suggested_action,
        detected_intent=detected_intent,
        entity_warnings_summary=entity_warnings_summary,
    ):
        return draft.strip(), False

    sentences = _split_sentences(draft)
    if len(sentences) < 2:
        return draft.strip(), False

    if not detect_unnecessary_followup_sentence(sentences[-1]):
        return draft.strip(), False

    cleaned = _rejoin_sentences(sentences[:-1]).strip()
    return cleaned, True


def apply_draft_completion_calibration(
    draft: str,
    *,
    seller_text: str = "",
    suggested_action: str | None = None,
    detected_intent: str | VendorTicketIntent | None = None,
    entity_warnings_summary: str | None = None,
) -> DraftCompletionCalibrationResult:
    """Detect trailing filler and optionally strip it."""
    working = draft.strip()
    contact_removed = False
    contact_cleaned, contact_removed = strip_trailing_contact_closing_filler(
        working,
        seller_text=seller_text,
    )
    working = contact_cleaned

    detected = detect_unnecessary_followup_in_draft(
        working,
        seller_text=seller_text,
        suggested_action=suggested_action,
        detected_intent=detected_intent,
        entity_warnings_summary=entity_warnings_summary,
    )
    cleaned, removed = strip_unnecessary_trailing_followup(
        working,
        seller_text=seller_text,
        suggested_action=suggested_action,
        detected_intent=detected_intent,
        entity_warnings_summary=entity_warnings_summary,
    )
    return DraftCompletionCalibrationResult(
        draft_reply=cleaned,
        unnecessary_followup_detected=detected,
        completion_calibration_applied=removed or contact_removed,
        trailing_filler_removed=removed,
        contact_closing_filler_removed=contact_removed,
    )


def completion_calibration_metadata_row(
    result: DraftCompletionCalibrationResult,
) -> dict[str, Any]:
    """Serialize completion calibration for JSONL / operator preview."""
    return {
        "unnecessary_followup_detected": result.unnecessary_followup_detected,
        "completion_calibration_applied": result.completion_calibration_applied,
        "trailing_filler_removed": result.trailing_filler_removed,
        "contact_closing_filler_removed": result.contact_closing_filler_removed,
        "draft_sentence_count_after_calibration": count_persian_sentences(result.draft_reply),
    }
