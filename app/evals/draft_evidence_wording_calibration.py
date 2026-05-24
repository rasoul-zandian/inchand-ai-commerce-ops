"""Photo/file evidence wording — opt-in requests only; file uploads not photo IDs."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.evals.draft_style import _SENTENCE_SPLIT_RE
from app.knowledge.policy_fact_extraction import (
    build_sheba_issue_draft_response,
    is_settlement_account_operational_request,
)

_FORBIDDEN_PHOTO_ID_PHRASES = (
    "شناسه عکس",
    "کد عکس",
    "photo id",
    "image id",
    "شناسه تصویر",
    "image identifier",
)

_SELLER_PHOTO_EVIDENCE_MARKERS = (
    "عکس",
    "تصویر",
    "فایل عکس",
    "مدارک تصویری",
    "تصویر کالا",
    "عکس کالا",
    "عکس محصول",
    "بارگذاری عکس",
    "بارگذاری تصویر",
    "آپلود عکس",
    "آپلود تصویر",
)

_DRAFT_PHOTO_REQUEST_MARKERS = (
    "لطفاً فایل عکس",
    "لطفاً تصویر",
    "لطفاً عکس",
    "فایل عکس را",
    "تصویر را ارسال",
    "عکس را ارسال",
    "اسکرین‌شات",
    "اسکرین شات",
    "screenshot",
    "عکس از",
    "تصویر از",
    "تصویر صفحه",
    "فایل عکس از",
)

_BRAND_PANEL_MARKERS = (
    "برند",
    "brand",
    "منو",
    "صفحه",
    "پیدا نمی",
    "پیدا نمیکنم",
    "پیدا نمی‌کنم",
)

_PRODUCT_WORKFLOW_ACTIONS = frozenset(
    {
        "check_product_approval",
        "review_product_edit",
        "review_product_status",
    },
)

DEFAULT_PHOTO_FILE_REQUEST = "لطفاً فایل عکس را ارسال کنید."
PRODUCT_PHOTO_FILE_REQUEST = "لطفاً تصویر کالا را به‌صورت فایل ارسال کنید."
PRODUCT_ID_REQUEST = "لطفاً شناسه کالا را ارسال کنید تا بررسی شود."
PRODUCT_REVIEW_ACK = "درخواست شما برای بررسی کالا ثبت شد و در دست بررسی قرار گرفت."
BRAND_NAME_REQUEST = "لطفاً نام دقیق برند موردنظر را ارسال کنید تا بررسی شود."
GENERIC_REVIEW_ACK = "درخواست شما ثبت شد و در دست بررسی قرار گرفت."


@dataclass(frozen=True)
class PhotoEvidenceWordingResult:
    """Outcome of photo/file evidence wording calibration."""

    draft_reply: str
    photo_wording_calibrated: bool
    unnecessary_photo_request_detected: bool = False


def build_photo_evidence_wording_instruction(
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    missing_entities: Sequence[str] = (),
) -> str:
    """Persian prompt guardrails for photo/file evidence requests."""
    lines = [
        "- درخواست عکس، تصویر یا اسکرین‌شات نکن مگر اینکه فروشنده خودش "
        "درباره عکس/تصویر/مدرک تصویری صحبت کرده باشد یا فرایند مشخصاً به عکس نیاز داشته باشد.",
        "- برای مشکل شبا، عکس شبا نخواه؛ شماره شبای صحیح را بخواه.",
        "- برای مشکل کالا، اگر شناسه کالا نیست، شناسه کالا را بخواه نه عکس کالا.",
        "- برای مشکل برند/پنل، به‌صورت پیش‌فرض اسکرین‌شات نخواه.",
    ]
    if should_request_photo_file(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
        missing_entities=missing_entities,
    ):
        lines.extend(
            [
                "- برای مدارک تصویری، فایل عکس/تصویر را بخواه — نه شناسه یا کد عکس.",
                "- مثال: «لطفاً فایل عکس را ارسال کنید.»",
            ],
        )
    return "\n".join(lines)


def _has_any(text: str, markers: tuple[str, ...] | frozenset[str]) -> bool:
    return any(marker in text for marker in markers)


def _normalize_action(action: str | None) -> str:
    return (action or "").strip().lower()


def seller_context_needs_photo_evidence(seller_text: str) -> bool:
    """True when seller message explicitly involves photo/image evidence."""
    return _has_any(seller_text.strip(), _SELLER_PHOTO_EVIDENCE_MARKERS)


def _is_brand_panel_issue(
    seller_text: str,
    *,
    conceptual_intent_fa: str | None = None,
) -> bool:
    text = seller_text.strip()
    if not text:
        return False
    if _has_any(text, _BRAND_PANEL_MARKERS):
        return True
    conceptual = (conceptual_intent_fa or "").strip()
    return "برند" in conceptual or "منو" in conceptual


def _is_product_workflow_issue(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    conceptual_intent_fa: str | None = None,
) -> bool:
    from app.workflows.operational_information_sufficiency import (
        _SCENARIO_PRODUCT_APPROVAL,
        detect_operational_scenario,
    )

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
    return any(token in conceptual for token in ("تایید کالا", "تأیید کالا", "ویرایش کالا"))


def _is_sheba_account_issue(
    seller_text: str,
    *,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
) -> bool:
    return is_settlement_account_operational_request(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    )


def _is_non_photo_operational_scenario(
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    conceptual_intent_fa: str | None = None,
) -> bool:
    from app.workflows.operational_information_sufficiency import (
        _SCENARIO_CANCELLATION,
        _SCENARIO_DELIVERY_COMPLETED,
        _SCENARIO_SETTLEMENT_INFO,
        _SCENARIO_SHIPMENT,
        detect_operational_scenario,
    )

    scenario = detect_operational_scenario(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    )
    return scenario in {
        _SCENARIO_CANCELLATION,
        _SCENARIO_DELIVERY_COMPLETED,
        _SCENARIO_SHIPMENT,
        _SCENARIO_SETTLEMENT_INFO,
    }


def should_request_photo_file(
    source_text: str,
    *,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    missing_entities: Sequence[str] = (),
    draft: str = "",
) -> bool:
    """True only when photo/file evidence is contextually appropriate."""
    text = (source_text or "").strip()
    if not text and not draft:
        return False

    if _is_sheba_account_issue(
        text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return False

    if seller_context_needs_photo_evidence(text):
        return True

    if _is_brand_panel_issue(text, conceptual_intent_fa=conceptual_intent_fa):
        return False
    if _is_product_workflow_issue(
        seller_text=text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    ):
        return False
    if _is_non_photo_operational_scenario(
        seller_text=text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    ):
        return False

    if (
        draft
        and draft_uses_forbidden_photo_id_wording(draft)
        and seller_context_needs_photo_evidence(text)
    ):
        return True

    _ = missing_entities
    return False


def draft_uses_forbidden_photo_id_wording(draft: str) -> bool:
    """True when draft asks for a photo/image identifier instead of a file."""
    text = draft.strip()
    if not text:
        return False
    lowered = text.lower()
    return any(phrase in text or phrase in lowered for phrase in _FORBIDDEN_PHOTO_ID_PHRASES)


def draft_requests_photo_evidence(draft: str) -> bool:
    """True when draft asks the seller to send a photo/image/screenshot."""
    text = draft.strip()
    if not text:
        return False
    lowered = text.lower()
    if any(marker in text or marker in lowered for marker in _DRAFT_PHOTO_REQUEST_MARKERS):
        return True
    if draft_uses_forbidden_photo_id_wording(text):
        return True
    return bool(re.search(r"لطفاً.{0,40}(عکس|تصویر|اسکرین)", text))


def _preferred_photo_file_request(seller_text: str) -> str:
    if any(marker in seller_text for marker in ("تصویر کالا", "عکس محصول", "عکس کالا")):
        return PRODUCT_PHOTO_FILE_REQUEST
    return DEFAULT_PHOTO_FILE_REQUEST


def _split_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    return [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]


def _rejoin_sentences(sentences: list[str]) -> str:
    if not sentences:
        return ""
    joined = ". ".join(sentences)
    if not joined.endswith((".", "؟", "!")):
        joined += "."
    return joined


def _sentence_requests_photo_evidence(sentence: str) -> bool:
    return draft_requests_photo_evidence(sentence)


def _has_product_id(
    *,
    seller_text: str,
    product_ids: Sequence[str],
    missing_entities: Sequence[str],
) -> bool:
    if any(str(value).strip() for value in product_ids):
        return True
    if "product_id" in {entity.strip().lower() for entity in missing_entities}:
        return False
    return bool(re.search(r"\b\d{5,}\b", seller_text))


def build_scenario_replacement_for_photo_request(
    *,
    seller_text: str,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    missing_entities: Sequence[str] = (),
    product_ids: Sequence[str] = (),
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> str:
    """Deterministic non-photo request for the current scenario."""
    if _is_sheba_account_issue(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return build_sheba_issue_draft_response(
            seller_text,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )

    if _is_product_workflow_issue(
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        conceptual_intent_fa=conceptual_intent_fa,
    ):
        if _has_product_id(
            seller_text=seller_text,
            product_ids=product_ids,
            missing_entities=missing_entities,
        ):
            return PRODUCT_REVIEW_ACK
        return PRODUCT_ID_REQUEST

    if _is_brand_panel_issue(seller_text, conceptual_intent_fa=conceptual_intent_fa):
        if "برند" in seller_text and any(
            token in seller_text for token in ("پیدا نمی", "پیدا نمیکنم", "پیدا نمی‌کنم")
        ):
            return BRAND_NAME_REQUEST
        return GENERIC_REVIEW_ACK

    return GENERIC_REVIEW_ACK


def _strip_unnecessary_photo_requests(
    draft: str,
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    missing_entities: Sequence[str] = (),
    product_ids: Sequence[str] = (),
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> tuple[str, bool]:
    if not draft_requests_photo_evidence(draft):
        return draft.strip(), False
    if should_request_photo_file(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
        missing_entities=missing_entities,
        draft=draft,
    ):
        return draft.strip(), False

    replacement = build_scenario_replacement_for_photo_request(
        seller_text=seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
        missing_entities=missing_entities,
        product_ids=product_ids,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
    )
    sentences = _split_sentences(draft)
    if not sentences:
        return replacement, True

    kept: list[str] = []
    replaced = False
    for sentence in sentences:
        if _sentence_requests_photo_evidence(sentence):
            if not replaced:
                kept.append(replacement.rstrip("."))
                replaced = True
        else:
            kept.append(sentence)

    result = _rejoin_sentences(kept).strip()
    if not result:
        return replacement, True
    return result, replaced


def calibrate_photo_evidence_wording(
    draft: str,
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    missing_entities: Sequence[str] = (),
    product_ids: Sequence[str] = (),
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> tuple[str, bool, bool]:
    """Strip inappropriate photo asks; fix photo-ID wording when photo is relevant."""
    stripped, unnecessary = _strip_unnecessary_photo_requests(
        draft,
        seller_text=seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
        missing_entities=missing_entities,
        product_ids=product_ids,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
    )
    if unnecessary:
        return stripped, True, True

    if not draft_uses_forbidden_photo_id_wording(stripped):
        return stripped, False, False

    if not should_request_photo_file(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
        missing_entities=missing_entities,
        draft=stripped,
    ):
        replacement = build_scenario_replacement_for_photo_request(
            seller_text=seller_text,
            detected_intent=detected_intent,
            conceptual_intent_fa=conceptual_intent_fa,
            suggested_action=suggested_action,
            missing_entities=missing_entities,
            product_ids=product_ids,
        )
        return replacement, True, True

    preferred = _preferred_photo_file_request(seller_text)
    sentences = _split_sentences(stripped)
    if not sentences:
        return preferred, True, False

    calibrated: list[str] = []
    changed = False
    for sentence in sentences:
        if draft_uses_forbidden_photo_id_wording(sentence):
            calibrated.append(preferred.rstrip("."))
            changed = True
        else:
            calibrated.append(sentence)

    result = _rejoin_sentences(calibrated).strip()
    if not result:
        return preferred, True, False
    return result, changed, False


def apply_photo_evidence_wording_calibration(
    draft: str,
    *,
    seller_text: str = "",
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    missing_entities: Sequence[str] = (),
    product_ids: Sequence[str] = (),
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> PhotoEvidenceWordingResult:
    """Apply photo/file evidence wording calibration to a draft."""
    calibrated, changed, unnecessary = calibrate_photo_evidence_wording(
        draft,
        seller_text=seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
        missing_entities=missing_entities,
        product_ids=product_ids,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
    )
    return PhotoEvidenceWordingResult(
        draft_reply=calibrated,
        photo_wording_calibrated=changed,
        unnecessary_photo_request_detected=unnecessary,
    )


def photo_evidence_wording_metadata_row(result: PhotoEvidenceWordingResult) -> dict[str, Any]:
    """Serialize photo wording calibration for metrics rows."""
    return {
        "photo_wording_calibrated": result.photo_wording_calibrated,
        "unnecessary_photo_request_detected": result.unnecessary_photo_request_detected,
    }
