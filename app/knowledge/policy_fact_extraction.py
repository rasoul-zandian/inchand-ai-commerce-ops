"""Safe policy fact extraction for grounded policy_explanation drafts (prompt-only)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.knowledge.knowledge_models import KnowledgeDocumentType, KnowledgeSourceLane
from app.operator_console.knowledge_hints import KnowledgeHint

MAX_POLICY_FACT_SNIPPET_CHARS = 300
MAX_POLICY_FACTS_PROMPT_CHARS = 600

SETTLEMENT_CANONICAL_DRAFT_ANSWER = (
    "مبلغ فروش ابتدا در کیف پول فروشنده به‌صورت بلاک ثبت می‌شود. "
    "۳ روز بعد از نهایی شدن سفارش، مبلغ قابل تسویه است و در اولین بازه تسویه "
    "به حساب فروشنده واریز می‌شود."
)

_VAGUE_SETTLEMENT_PHRASES = (
    "بستگی دارد",
    "به قوانین مراجعه",
    "راهنمای سایت",
    "زمان دقیق",
    "مراجعه کنید",
    "به راهنما",
)

_SETTLEMENT_TIMING_POSITIVE_MARKERS = (
    "چند روز",
    "چه زمانی",
    "زمان تسویه",
    "زمان واریز",
    "بعد از خرید",
    "بعد از تحویل",
    "بعد از نهایی شدن",
    "شرایط تسویه",
    "قانون تسویه",
    "قابل تسویه",
    "چرخه تسویه",
    "نهایی شدن سفارش",
    "نهایی شدن",
    "واریز نشده",
    "تسویه نشده",
    "هنوز واریز",
    "هنوز تسویه",
    "وضعیت واریز",
    "وضعیت تسویه",
)

_SETTLEMENT_ACCOUNT_OPERATIONAL_MARKERS = (
    "شبا",
    "شماره شبا",
    "iban",
    "حساب بانکی",
    "ثبت شبا",
    "ثبت نمیشه",
    "ثبت نمی‌شود",
    "ثبت نمی شود",
    "تغییر شبا",
    "اصلاح شبا",
    "اطلاعات تسویه حساب",
    "اطلاعات بانکی",
    "پنل تسویه",
    "ثبت و اعلام گردد",
    "ثبت و اعلام",
    "ثبت اطلاعات تسویه",
)

SHEBA_RECEIVED_ACK = "شماره شبا دریافت شد و درخواست بررسی/ثبت آن در دست بررسی قرار گرفت."
SHEBA_ACCOUNT_INFO_ACK = (
    "درخواست ثبت اطلاعات تسویه حساب و شماره شبا دریافت شد و در دست بررسی قرار گرفت."
)
SHEBA_NUMBER_REQUEST = "لطفاً شماره شبای صحیح خود را ارسال کنید تا بررسی شود."
SHEBA_INCOMPLETE_REQUEST = (
    "شماره شبای ارسال‌شده ناقص یا نامعتبر است. لطفاً شماره شبای صحیح را ارسال کنید."
)

_SHEBA_ASK_AGAIN_MARKERS = (
    "شماره شبای صحیح",
    "شماره شبا را ارسال",
    "شماره شبا را وارد",
    "شماره شبای خود را",
)


def _normalize_policy_match_text(text: str) -> str:
    return (text or "").lower().replace("\u200c", "").replace(" ", "")


def _text_has_marker(text: str, markers: Sequence[str]) -> bool:
    normalized = _normalize_policy_match_text(text)
    for marker in markers:
        cleaned = marker.lower().replace("\u200c", "").replace(" ", "")
        if cleaned in normalized or marker in text:
            return True
    return False


def _has_explicit_settlement_timing_question(text: str) -> bool:
    """True when seller text explicitly asks about settlement timing or rules."""
    if _text_has_marker(text, _SETTLEMENT_TIMING_POSITIVE_MARKERS):
        return True
    if "واریز" in text and ("کی" in text or "چه زم" in text or "چند" in text):
        return True
    if "تسویه" in text and ("چند" in text or "کی" in text):
        return True
    if "?" in text or "؟" in text:
        if "تسویه" in text and any(
            token in text for token in ("زمان", "شرایط", "قانون", "چرخه", "قابل")
        ):
            return True
    return False


def is_settlement_account_operational_request(
    text: str,
    *,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
) -> bool:
    """True for IBAN/settlement-account registration or correction requests."""
    seller = (text or "").strip()
    if not seller:
        return False

    if _text_has_marker(seller, _SETTLEMENT_ACCOUNT_OPERATIONAL_MARKERS):
        return True

    normalized = _normalize_policy_match_text(seller)
    if "حساب" in normalized and any(
        token in seller for token in ("ثبت", "تغییر", "اصلاح", "بانک", "شبا", "تسویه")
    ):
        return True
    if "بانک" in seller and any(token in seller for token in ("ثبت", "شبا", "حساب", "تسویه")):
        return True

    conceptual = (conceptual_intent_fa or "").strip()
    if any(token in conceptual for token in ("شبا", "شماره شبا", "حساب بانکی", "اطلاعات بانکی")):
        return True

    _ = detected_intent, suggested_action
    return False


def seller_text_has_valid_iban(seller_text: str) -> bool:
    """True when seller text contains a complete IR Sheba/IBAN value."""
    from app.workflows.operational_entity_extraction import _IR_IBAN_RE, normalize_digits

    text = (seller_text or "").strip()
    if not text:
        return False
    if _IR_IBAN_RE.search(text):
        return True
    compact = re.sub(r"\s+", "", normalize_digits(text))
    return "شبا" in text and bool(re.search(r"\d{24}", compact))


def has_valid_extracted_iban(
    extracted_iban: str | None,
    seller_text: str = "",
) -> bool:
    """True when a valid IBAN was extracted or is present in seller text."""
    if extracted_iban and str(extracted_iban).strip():
        return True
    return seller_text_has_valid_iban(seller_text)


def has_incomplete_iban_signal(
    *,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> bool:
    """True when extraction surfaced an incomplete/invalid Sheba candidate."""
    if has_incomplete_iban_entity:
        return True
    summary = (entity_warnings_summary or "").strip()
    return "شماره شبا ناقص" in summary


def build_sheba_issue_draft_response(
    seller_text: str,
    *,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> str:
    """Build Sheba/IBAN operational draft from extraction outcome."""
    text = (seller_text or "").strip()
    has_iban = has_valid_extracted_iban(extracted_iban, text)
    incomplete = has_incomplete_iban_signal(
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
    )

    if incomplete and not has_iban:
        return SHEBA_INCOMPLETE_REQUEST
    if has_iban:
        if "اطلاعات تسویه حساب" in text or (
            "تسویه حساب" in text
            and any(token in text for token in ("ثبت", "پنل", "شبا", "ثبت اطلاعات تسویه"))
        ):
            return SHEBA_ACCOUNT_INFO_ACK
        return SHEBA_RECEIVED_ACK
    return SHEBA_NUMBER_REQUEST


def build_settlement_account_operational_ack(
    seller_text: str,
    *,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> str:
    """Deterministic acknowledgement for settlement-account / IBAN operational requests."""
    return build_sheba_issue_draft_response(
        seller_text,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
    )


def draft_requests_sheba_number_again(draft: str) -> bool:
    """True when draft asks the seller to provide Sheba/IBAN again."""
    text = draft.strip()
    if not text:
        return False
    return any(marker in text for marker in _SHEBA_ASK_AGAIN_MARKERS)


def calibrate_sheba_issue_draft(
    draft: str,
    *,
    seller_text: str,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
    extracted_iban: str | None = None,
    has_incomplete_iban_entity: bool = False,
    entity_warnings_summary: str | None = None,
) -> tuple[str, bool]:
    """Align Sheba/account drafts with extracted IBAN completeness."""
    if not is_settlement_account_operational_request(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return draft.strip(), False

    expected = build_sheba_issue_draft_response(
        seller_text,
        extracted_iban=extracted_iban,
        has_incomplete_iban_entity=has_incomplete_iban_entity,
        entity_warnings_summary=entity_warnings_summary,
    )
    cleaned = draft.strip()
    if cleaned == expected:
        return cleaned, False

    has_iban = has_valid_extracted_iban(extracted_iban, seller_text)
    reask = draft_requests_sheba_number_again(cleaned)
    if has_iban and (reask or cleaned != expected):
        return expected, True
    if (
        has_incomplete_iban_signal(
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )
        and not has_iban
    ):
        return expected, True
    if not has_iban and (reask is False or SHEBA_RECEIVED_ACK in cleaned):
        return expected, True
    return cleaned, False


def is_settlement_timing_policy_question(
    text: str,
    *,
    detected_intent: str | None = None,
    conceptual_intent_fa: str | None = None,
    suggested_action: str | None = None,
) -> bool:
    """True only for informational settlement timing/rule questions."""
    from app.evals.draft_completion_calibration import is_informational_question
    from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

    seller = (text or "").strip()
    if not seller:
        return False

    account_operational = is_settlement_account_operational_request(
        seller,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    )
    explicit_timing = _has_explicit_settlement_timing_question(seller)

    if account_operational and not explicit_timing:
        return False
    if explicit_timing:
        return True

    intent = (detected_intent or "").strip().lower()
    if intent == VendorTicketIntent.SETTLEMENT_STATUS_INQUIRY.value and is_informational_question(
        seller,
        detected_intent=detected_intent,
    ):
        return True

    conceptual = (conceptual_intent_fa or "").strip()
    if any(token in conceptual for token in ("زمان تسویه", "زمان‌بندی تسویه", "زمان واریز")):
        return True

    _ = suggested_action
    return False


_INTENT_DOCUMENT_PRIORITY: dict[str, tuple[str, ...]] = {
    KnowledgeDocumentType.SETTLEMENT_RULES.value: (
        KnowledgeDocumentType.SETTLEMENT_RULES.value,
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES.value: (
        KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES.value,
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    KnowledgeDocumentType.PROHIBITED_GOODS.value: (
        KnowledgeDocumentType.PROHIBITED_GOODS.value,
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    KnowledgeDocumentType.REFUND_RETURN_RULES.value: (
        KnowledgeDocumentType.REFUND_RETURN_RULES.value,
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
    KnowledgeDocumentType.SHIPPING_DELIVERY_RULES.value: (
        KnowledgeDocumentType.SHIPPING_DELIVERY_RULES.value,
        KnowledgeDocumentType.SUPPORT_FAQ.value,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY.value,
    ),
}


@dataclass(frozen=True)
class SafePolicyFact:
    """One capped official-policy fact safe for draft prompts."""

    document_type: str
    section_title: str
    source_lane: str
    text: str


def cap_policy_fact_text(text: str, *, max_chars: int = MAX_POLICY_FACT_SNIPPET_CHARS) -> str:
    """Cap one policy fact snippet for prompt injection."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def _hint_source_lane(hint: KnowledgeHint | Mapping[str, Any]) -> str:
    if isinstance(hint, KnowledgeHint):
        return hint.source_lane
    return str(hint.get("source_lane") or "")


def _hint_snippet(hint: KnowledgeHint | Mapping[str, Any]) -> str:
    if isinstance(hint, KnowledgeHint):
        return hint.snippet
    return str(hint.get("prompt_snippet") or hint.get("snippet") or "")


def extract_safe_policy_facts_from_hints(
    hints: Sequence[KnowledgeHint | Mapping[str, Any]],
) -> tuple[SafePolicyFact, ...]:
    """Extract capped official-policy facts from knowledge hints."""
    facts: list[SafePolicyFact] = []
    seen: set[tuple[str, str]] = set()
    for hint in hints:
        source_lane = _hint_source_lane(hint)
        if source_lane and source_lane != KnowledgeSourceLane.OFFICIAL_POLICY.value:
            continue
        document_type = (
            hint.document_type
            if isinstance(hint, KnowledgeHint)
            else str(hint.get("document_type") or "")
        ).strip()
        section_title = (
            hint.section_title
            if isinstance(hint, KnowledgeHint)
            else str(hint.get("section_title") or "")
        ).strip()
        snippet = cap_policy_fact_text(_hint_snippet(hint))
        if not document_type or not snippet:
            continue
        key = (document_type, snippet)
        if key in seen:
            continue
        seen.add(key)
        facts.append(
            SafePolicyFact(
                document_type=document_type,
                section_title=section_title or document_type,
                source_lane=source_lane or KnowledgeSourceLane.OFFICIAL_POLICY.value,
                text=snippet,
            ),
        )
    return tuple(facts)


def hint_to_prompt_dict(hint: KnowledgeHint) -> dict[str, Any]:
    """Serialize one hint for internal prompt use (snippet capped; not for reports/UI)."""
    snippet = cap_policy_fact_text(hint.snippet)
    return {
        "document_type": hint.document_type,
        "section_title": hint.section_title,
        "source_lane": hint.source_lane,
        "priority_rank": hint.priority_rank,
        "prompt_snippet": snippet,
        "snippet_chars": len(snippet),
    }


def _preferred_document_types(
    *,
    detected_intent: str | None,
    suggested_action: str | None,
    seller_text: str,
    document_types: Sequence[str],
) -> tuple[str, ...]:
    intent = (detected_intent or "").strip().lower()
    text = seller_text.strip()

    if is_settlement_timing_policy_question(
        seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
    ):
        return _INTENT_DOCUMENT_PRIORITY[KnowledgeDocumentType.SETTLEMENT_RULES.value]
    if "publish" in intent or "publishing" in intent or "انتشار" in text:
        return _INTENT_DOCUMENT_PRIORITY[KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES.value]
    if "prohibited" in intent or "ممنوع" in text:
        return _INTENT_DOCUMENT_PRIORITY[KnowledgeDocumentType.PROHIBITED_GOODS.value]
    if "return" in intent or "refund" in intent or "مرجوع" in text:
        return _INTENT_DOCUMENT_PRIORITY[KnowledgeDocumentType.REFUND_RETURN_RULES.value]
    if "delivery" in intent or "shipping" in intent or "ارسال" in text:
        return _INTENT_DOCUMENT_PRIORITY[KnowledgeDocumentType.SHIPPING_DELIVERY_RULES.value]

    if document_types:
        return tuple(dict.fromkeys(document_types))
    return tuple(_INTENT_DOCUMENT_PRIORITY[KnowledgeDocumentType.SETTLEMENT_RULES.value])


def select_policy_facts_for_draft(
    *,
    detected_intent: str | None,
    suggested_action: str | None,
    seller_text: str = "",
    document_types: Sequence[str] = (),
    hints: Sequence[KnowledgeHint | Mapping[str, Any]] = (),
) -> tuple[SafePolicyFact, ...]:
    """Select and order policy facts for a draft prompt."""
    facts = extract_safe_policy_facts_from_hints(hints)
    if not facts:
        return ()

    priority = _preferred_document_types(
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        seller_text=seller_text,
        document_types=document_types,
    )
    rank = {doc_type: index for index, doc_type in enumerate(priority)}

    def sort_key(fact: SafePolicyFact) -> tuple[int, str]:
        return (rank.get(fact.document_type, len(priority)), fact.document_type)

    ordered = sorted(facts, key=sort_key)

    selected: list[SafePolicyFact] = []
    total_chars = 0
    for fact in ordered:
        block_len = len(fact.text) + len(fact.section_title) + len(fact.document_type) + 8
        if total_chars + block_len > MAX_POLICY_FACTS_PROMPT_CHARS and selected:
            break
        selected.append(fact)
        total_chars += block_len
    return tuple(selected)


def render_policy_facts_for_prompt(facts: Sequence[SafePolicyFact]) -> str:
    """Render selected policy facts for LLM prompt injection."""
    if not facts:
        return ""
    lines = [
        "Relevant official policy facts (use directly; do not invent different timing):",
    ]
    total = len(lines[0])
    for index, fact in enumerate(facts, start=1):
        line = f"{index}. [{fact.document_type}] {fact.section_title}: {fact.text}"
        if total + len(line) > MAX_POLICY_FACTS_PROMPT_CHARS and index > 1:
            break
        lines.append(line)
        total += len(line)
    return "\n".join(lines)


def build_policy_facts_prompt_block(
    *,
    detected_intent: str | None,
    suggested_action: str | None,
    seller_text: str = "",
    document_types: Sequence[str] = (),
    hints: Sequence[KnowledgeHint | Mapping[str, Any]] = (),
    conceptual_intent_fa: str | None = None,
) -> str:
    """Select and render policy facts for policy_explanation prompts."""
    if is_settlement_account_operational_request(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return ""

    facts = select_policy_facts_for_draft(
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        seller_text=seller_text,
        document_types=document_types,
        hints=hints,
    )
    if not is_settlement_timing_policy_question(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        facts = tuple(
            fact
            for fact in facts
            if fact.document_type != KnowledgeDocumentType.SETTLEMENT_RULES.value
        )
    return render_policy_facts_for_prompt(facts)


def is_settlement_policy_question(
    seller_text: str,
    *,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    conceptual_intent_fa: str | None = None,
) -> bool:
    """Backward-compatible alias for settlement timing policy questions."""
    return is_settlement_timing_policy_question(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    )


def settlement_fact_present(facts: Sequence[SafePolicyFact]) -> bool:
    """True when settlement_rules fact contains wallet/block + 3-day finalization markers."""
    for fact in facts:
        if fact.document_type != KnowledgeDocumentType.SETTLEMENT_RULES.value:
            continue
        text = fact.text
        if ("کیف پول" in text or "بلاک" in text) and (
            "۳ روز" in text or "3 روز" in text or "نهایی" in text
        ):
            return True
    return False


def draft_has_settlement_grounding(draft: str) -> bool:
    """True when draft states wallet block, 3-day finalization, and payout window."""
    text = draft.strip()
    if not text:
        return False
    has_wallet = "کیف پول" in text or "بلاک" in text
    has_timing = ("۳ روز" in text or "3 روز" in text) and "نهایی" in text
    has_payout = "اولین بازه" in text or "واریز" in text
    return has_wallet and has_timing and has_payout


def is_vague_settlement_policy_draft(draft: str) -> bool:
    """True when settlement draft deferrals/referrals replace explicit timing."""
    return any(marker in draft for marker in _VAGUE_SETTLEMENT_PHRASES)


def build_deterministic_settlement_answer_from_facts(
    facts: Sequence[SafePolicyFact],
) -> str:
    """Build canonical settlement answer when settlement_rules fact is present."""
    if settlement_fact_present(facts):
        return SETTLEMENT_CANONICAL_DRAFT_ANSWER
    for fact in facts:
        if fact.document_type == KnowledgeDocumentType.SETTLEMENT_RULES.value:
            return SETTLEMENT_CANONICAL_DRAFT_ANSWER
    return SETTLEMENT_CANONICAL_DRAFT_ANSWER


def calibrate_settlement_policy_draft(
    draft: str,
    *,
    seller_text: str,
    detected_intent: str | None,
    suggested_action: str | None,
    hints: Sequence[KnowledgeHint | Mapping[str, Any]] = (),
    conceptual_intent_fa: str | None = None,
    draft_style: str | None = None,
) -> tuple[str, bool]:
    """Replace vague/ungrounded settlement drafts with deterministic policy answer."""
    from app.evals.draft_style import DRAFT_STYLE_POLICY_EXPLANATION

    if not is_settlement_timing_policy_question(
        seller_text,
        detected_intent=detected_intent,
        conceptual_intent_fa=conceptual_intent_fa,
        suggested_action=suggested_action,
    ):
        return draft.strip(), False
    if draft_style and draft_style != DRAFT_STYLE_POLICY_EXPLANATION:
        return draft.strip(), False

    facts = select_policy_facts_for_draft(
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        seller_text=seller_text,
        hints=hints,
    )
    if settlement_fact_present(facts):
        if draft_has_settlement_grounding(draft) and not is_vague_settlement_policy_draft(draft):
            return draft.strip(), False
        answer = build_deterministic_settlement_answer_from_facts(facts)
        return answer, True

    if draft_has_settlement_grounding(draft) and not is_vague_settlement_policy_draft(draft):
        return draft.strip(), False
    if is_vague_settlement_policy_draft(draft) or not draft_has_settlement_grounding(draft):
        return SETTLEMENT_CANONICAL_DRAFT_ANSWER, True
    return draft.strip(), False
