"""Deterministic extraction of operational entities from seller ticket text (shadow/HITL only)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

_PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

_MAX_ORDER_IDS = 8
_CONTEXT_RADIUS = 48

_ORDER_KEYWORDS = (
    "سفارش",
    "تحویل",
    "پیگیری",
    "رسیده",
    "برگشت",
    "ارسال",
    "لغو",
    "کنسل",
    "رهگیری",
    "شکایت",
    "order",
)

_PRODUCT_KEYWORDS = (
    "کالا",
    "شناسه کالا",
    "محصول",
    "کد کالا",
)

_POST_TRACKING_KEYWORDS = (
    "کد رهگیری",
    "شماره رهگیری",
    "رهگیری پست",
    "کد رهگیری پست",
    "مرسوله",
    "پست",
    "کد پیگیری",
    "بارکد پستی",
)

_IBAN_KEYWORDS = (
    "شبا",
    "شماره شبا",
    "حساب",
    "واریز",
    "تسویه",
    "بانکی",
    "مالی",
)

_CARRIER_TIPAX = "تیپاکس"
_CARRIER_CHAPAR = "چاپار"

_INC_ORDER_RE = re.compile(r"\bINC\s*[-_:\s]*(\d{7})(?!\d)", re.IGNORECASE)
_STANDALONE_ORDER_7_RE = re.compile(r"(?<!\d)(\d{7})(?!\d)")
_SAFARESH_COLON_ORDER_RE = re.compile(r"سفارش\s*:\s*(\d{7})\b", re.IGNORECASE)
_IR_IBAN_RE = re.compile(r"\bIR\s*(\d{24})\b", re.IGNORECASE)
_STANDALONE_24_DIGIT_RE = re.compile(r"\b(\d{24})\b")
_DIGIT_SPAN_RE = re.compile(r"\d+")
_ORDER_LIST_PATTERN = re.compile(
    r"شماره\s*سفارش\s*:?\s*([0-9,\sو]+)",
    re.IGNORECASE,
)
_ORDER_PATTERN = re.compile(
    r"سفارش(?:‌های?|‌ی)?\s*(?:شماره)?\s*(\d{7})\b",
    re.IGNORECASE,
)
_MULTI_ORDER_JOINER = re.compile(r"(?:و|,)\s*(\d{7})\b")
_ORDER_ID_TOKEN = re.compile(r"\d{7}")

_WARNING_INCOMPLETE_ORDER = "شماره سفارش ناقص احتمالی"
_WARNING_INCOMPLETE_IBAN = "شماره شبا ناقص احتمالی"
_WARNING_AMBIGUOUS = "شماره نامشخص"


class EntityType(StrEnum):
    ORDER_ID = "order_id"
    PRODUCT_ID = "product_id"
    TRACKING_CODE = "tracking_code"
    IBAN = "iban"
    INCOMPLETE_ORDER_ID_CANDIDATE = "incomplete_order_id_candidate"
    INCOMPLETE_IBAN_CANDIDATE = "incomplete_iban_candidate"
    AMBIGUOUS_NUMBER = "ambiguous_number"


class TrackingCarrier(StrEnum):
    IRAN_POST = "iran_post"
    TIPAX = "tipax"
    CHAPAR = "chapar"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ExtractedOperationalEntity:
    entity_type: EntityType
    value: str
    normalized_value: str
    confidence_band: str
    context_keyword: str | None = None
    carrier: TrackingCarrier | None = None
    warning: str | None = None


@dataclass(frozen=True)
class OperationalEntityExtractionResult:
    entities: tuple[ExtractedOperationalEntity, ...] = ()

    @property
    def order_ids(self) -> tuple[str, ...]:
        return tuple(
            e.normalized_value for e in self.entities if e.entity_type == EntityType.ORDER_ID
        )[:_MAX_ORDER_IDS]

    @property
    def product_ids(self) -> tuple[str, ...]:
        return tuple(
            e.normalized_value for e in self.entities if e.entity_type == EntityType.PRODUCT_ID
        )

    @property
    def primary_tracking_code(self) -> str | None:
        for entity in self.entities:
            if entity.entity_type == EntityType.TRACKING_CODE:
                return entity.normalized_value
        return None

    @property
    def primary_tracking_carrier(self) -> TrackingCarrier | None:
        for entity in self.entities:
            if entity.entity_type == EntityType.TRACKING_CODE:
                return entity.carrier
        return None

    @property
    def primary_iban(self) -> str | None:
        for entity in self.entities:
            if entity.entity_type == EntityType.IBAN:
                return entity.normalized_value
        return None

    @property
    def primary_iban_masked(self) -> str | None:
        iban = self.primary_iban
        if iban is None:
            return None
        return mask_sensitive_entity(iban)

    @property
    def has_incomplete_iban_candidate(self) -> bool:
        return any(
            entity.entity_type == EntityType.INCOMPLETE_IBAN_CANDIDATE for entity in self.entities
        )

    @property
    def warnings(self) -> tuple[str, ...]:
        seen: list[str] = []
        for entity in self.entities:
            if entity.warning and entity.warning not in seen:
                seen.append(entity.warning)
        return tuple(seen)

    @property
    def entity_warnings_summary(self) -> str | None:
        if not self.warnings:
            return None
        return "; ".join(self.warnings)


def normalize_digits(text: str) -> str:
    """Map Persian/Arabic numerals to ASCII digits for pattern matching."""
    return text.translate(_PERSIAN_DIGITS).translate(_ARABIC_DIGITS)


def mask_sensitive_entity(value: str) -> str:
    """Mask IBAN/Sheba and similar sensitive numeric tokens for operator UI."""
    cleaned = normalize_digits(value).upper().replace(" ", "")
    if cleaned.startswith("IR") and len(cleaned) > 2:
        body = cleaned[2:]
        if len(body) >= 4:
            hidden = max(len(body) - 4, 1)
            return f"IR{body[:2]}{'*' * hidden}{body[-4:]}"
        return "IR****"
    digits = "".join(ch for ch in cleaned if ch.isdigit())
    if len(digits) >= 4:
        hidden = max(len(digits) - 4, 1)
        return f"{'*' * hidden}{digits[-4:]}"
    return "****"


def _context_slice(text: str, start: int, end: int) -> str:
    lo = max(0, start - _CONTEXT_RADIUS)
    hi = min(len(text), end + _CONTEXT_RADIUS)
    return text[lo:hi]


def _first_matching_keyword(context: str, keywords: tuple[str, ...]) -> str | None:
    for keyword in keywords:
        if keyword in context:
            return keyword
    return None


def _is_mobile_phone(digits: str) -> bool:
    return len(digits) == 11 and digits.startswith("09")


def _canonical_order_id(seven_digits: str) -> str:
    return f"INC-{seven_digits}"


def _span_fully_inside_claimed(span: tuple[int, int], claimed_spans: set[tuple[int, int]]) -> bool:
    start, end = span
    return any(start >= cs and end <= ce for cs, ce in claimed_spans)


def _normalize_inc_raw_value(raw: str) -> str:
    cleaned = raw.upper().replace("_", "-").replace(":", "-")
    cleaned = re.sub(r"\s+", "", cleaned)
    if cleaned.startswith("INC-") and len(cleaned) > 4:
        return cleaned
    match = re.search(r"(\d{7})(?!\d)", cleaned)
    if match:
        return _canonical_order_id(match.group(1))
    return cleaned


def dedupe_entities_by_type_and_normalized_value_preserve_order(
    entities: list[ExtractedOperationalEntity],
) -> list[ExtractedOperationalEntity]:
    """Drop duplicate entity types by normalized value; keep first occurrence."""
    seen: set[tuple[EntityType, str]] = set()
    deduped: list[ExtractedOperationalEntity] = []
    for entity in entities:
        key = (entity.entity_type, entity.normalized_value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entity)
    return deduped


def _append_order_entity(
    entities: list[ExtractedOperationalEntity],
    *,
    seven_digits: str,
    confidence_band: str,
    context_keyword: str | None,
    raw_value: str | None = None,
) -> None:
    if len(seven_digits) != 7 or not seven_digits.isdigit():
        return
    if any(
        e.entity_type == EntityType.ORDER_ID and e.normalized_value == seven_digits
        for e in entities
    ):
        return
    if sum(1 for e in entities if e.entity_type == EntityType.ORDER_ID) >= _MAX_ORDER_IDS:
        return
    entities.append(
        ExtractedOperationalEntity(
            entity_type=EntityType.ORDER_ID,
            value=raw_value or _canonical_order_id(seven_digits),
            normalized_value=seven_digits,
            confidence_band=confidence_band,
            context_keyword=context_keyword,
        ),
    )


def extract_order_ids(text: str) -> tuple[str, ...]:
    """Extract normalized 7-digit order IDs (and INC-prefixed forms)."""
    return extract_operational_entities(text).order_ids


def extract_product_ids(text: str) -> tuple[str, ...]:
    """Extract 8-digit product IDs near product keywords."""
    return extract_operational_entities(text).product_ids


def extract_tracking_codes(text: str) -> tuple[ExtractedOperationalEntity, ...]:
    """Extract tracking-code entities with carrier hints."""
    return tuple(
        e
        for e in extract_operational_entities(text).entities
        if e.entity_type == EntityType.TRACKING_CODE
    )


def _append_iban_entity(
    entities: list[ExtractedOperationalEntity],
    *,
    normalized_value: str,
    raw_value: str,
    confidence_band: str,
    context_keyword: str | None,
) -> None:
    if any(
        e.entity_type == EntityType.IBAN and e.normalized_value == normalized_value
        for e in entities
    ):
        return
    entities.append(
        ExtractedOperationalEntity(
            entity_type=EntityType.IBAN,
            value=raw_value,
            normalized_value=normalized_value,
            confidence_band=confidence_band,
            context_keyword=context_keyword,
        ),
    )


def _extract_iban_entities(
    normalized: str,
    entities: list[ExtractedOperationalEntity],
    claimed_spans: set[tuple[int, int]],
) -> None:
    for match in _IR_IBAN_RE.finditer(normalized):
        digits = match.group(1)
        span = match.span()
        claimed_spans.add(span)
        _append_iban_entity(
            entities,
            normalized_value=f"IR{digits}",
            raw_value=match.group(0).upper().replace(" ", ""),
            confidence_band="high",
            context_keyword="IR",
        )

    for match in _STANDALONE_24_DIGIT_RE.finditer(normalized):
        start, end = match.span()
        if any(start >= cs and end <= ce for cs, ce in claimed_spans):
            continue
        digits = match.group(1)
        context = _context_slice(normalized, start, end)
        post_kw = _first_matching_keyword(context, _POST_TRACKING_KEYWORDS)
        iban_kw = _first_matching_keyword(context, _IBAN_KEYWORDS)
        if post_kw:
            continue
        if iban_kw:
            claimed_spans.add((start, end))
            _append_iban_entity(
                entities,
                normalized_value=digits,
                raw_value=digits,
                confidence_band="high",
                context_keyword=iban_kw,
            )


def _extract_orders_from_patterns(
    normalized: str,
    entities: list[ExtractedOperationalEntity],
) -> None:
    for list_match in _ORDER_LIST_PATTERN.finditer(normalized):
        chunk = normalize_digits(list_match.group(1))
        for token in _ORDER_ID_TOKEN.findall(chunk):
            _append_order_entity(
                entities,
                seven_digits=token,
                confidence_band="high",
                context_keyword="شماره سفارش",
            )

    for match in _ORDER_PATTERN.finditer(normalized):
        _append_order_entity(
            entities,
            seven_digits=match.group(1),
            confidence_band="high",
            context_keyword="سفارش",
            raw_value=match.group(0),
        )

    for match in _SAFARESH_COLON_ORDER_RE.finditer(normalized):
        _append_order_entity(
            entities,
            seven_digits=match.group(1),
            confidence_band="high",
            context_keyword="سفارش",
            raw_value=match.group(0),
        )

    if "سفارش" in normalized:
        for match in _MULTI_ORDER_JOINER.finditer(normalized):
            _append_order_entity(
                entities,
                seven_digits=match.group(1),
                confidence_band="medium",
                context_keyword="سفارش",
            )


def _extract_order_id_entities(
    normalized: str,
    entities: list[ExtractedOperationalEntity],
    claimed_spans: set[tuple[int, int]],
) -> None:
    """Extract all unique order IDs (INC variants + exact 7-digit spans)."""
    for match in _INC_ORDER_RE.finditer(normalized):
        seven = match.group(1)
        digit_span = match.span(1)
        if _span_fully_inside_claimed(digit_span, claimed_spans):
            continue
        claimed_spans.add(digit_span)
        _append_order_entity(
            entities,
            seven_digits=seven,
            confidence_band="high",
            context_keyword="INC",
            raw_value=_normalize_inc_raw_value(match.group(0)),
        )

    _extract_orders_from_patterns(normalized, entities)

    for match in _STANDALONE_ORDER_7_RE.finditer(normalized):
        seven = match.group(1)
        span = match.span(1)
        if _span_fully_inside_claimed(span, claimed_spans):
            continue
        claimed_spans.add(span)
        order_kw = _first_matching_keyword(
            _context_slice(normalized, span[0], span[1]),
            _ORDER_KEYWORDS,
        )
        _append_order_entity(
            entities,
            seven_digits=seven,
            confidence_band="high" if order_kw else "medium",
            context_keyword=order_kw,
            raw_value=seven,
        )


def _classify_digit_span(
    normalized: str,
    *,
    start: int,
    end: int,
    digits: str,
    entities: list[ExtractedOperationalEntity],
    claimed_spans: set[tuple[int, int]],
) -> None:
    if _span_fully_inside_claimed((start, end), claimed_spans):
        return
    if _is_mobile_phone(digits):
        return

    context = _context_slice(normalized, start, end)
    order_kw = _first_matching_keyword(context, _ORDER_KEYWORDS)
    product_kw = _first_matching_keyword(context, _PRODUCT_KEYWORDS)
    post_kw = _first_matching_keyword(context, _POST_TRACKING_KEYWORDS)
    iban_kw = _first_matching_keyword(context, _IBAN_KEYWORDS)
    has_tipax = _CARRIER_TIPAX in context
    has_chapar = _CARRIER_CHAPAR in context
    length = len(digits)

    if has_tipax and 15 <= length <= 25:
        claimed_spans.add((start, end))
        entities.append(
            ExtractedOperationalEntity(
                entity_type=EntityType.TRACKING_CODE,
                value=digits,
                normalized_value=digits,
                confidence_band="high",
                context_keyword=_CARRIER_TIPAX,
                carrier=TrackingCarrier.TIPAX,
            ),
        )
        return

    if has_chapar and length == 17:
        claimed_spans.add((start, end))
        entities.append(
            ExtractedOperationalEntity(
                entity_type=EntityType.TRACKING_CODE,
                value=digits,
                normalized_value=digits,
                confidence_band="high",
                context_keyword=_CARRIER_CHAPAR,
                carrier=TrackingCarrier.CHAPAR,
            ),
        )
        return

    if length == 24:
        if post_kw and not has_tipax and not has_chapar:
            claimed_spans.add((start, end))
            entities.append(
                ExtractedOperationalEntity(
                    entity_type=EntityType.TRACKING_CODE,
                    value=digits,
                    normalized_value=digits,
                    confidence_band="high",
                    context_keyword=post_kw,
                    carrier=TrackingCarrier.IRAN_POST,
                ),
            )
            return
        if iban_kw:
            claimed_spans.add((start, end))
            _append_iban_entity(
                entities,
                normalized_value=digits,
                raw_value=digits,
                confidence_band="high",
                context_keyword=iban_kw,
            )
            return
        return

    if length in (23, 25) and iban_kw:
        claimed_spans.add((start, end))
        entities.append(
            ExtractedOperationalEntity(
                entity_type=EntityType.INCOMPLETE_IBAN_CANDIDATE,
                value=digits,
                normalized_value=digits,
                confidence_band="medium",
                context_keyword=iban_kw,
                warning=_WARNING_INCOMPLETE_IBAN,
            ),
        )
        return

    if length == 8 and product_kw:
        claimed_spans.add((start, end))
        entities.append(
            ExtractedOperationalEntity(
                entity_type=EntityType.PRODUCT_ID,
                value=digits,
                normalized_value=digits,
                confidence_band="high" if product_kw else "medium",
                context_keyword=product_kw,
            ),
        )
        return

    if length == 7:
        return

    if length == 6 and order_kw:
        claimed_spans.add((start, end))
        entities.append(
            ExtractedOperationalEntity(
                entity_type=EntityType.INCOMPLETE_ORDER_ID_CANDIDATE,
                value=digits,
                normalized_value=digits,
                confidence_band="medium",
                context_keyword=order_kw,
                warning=_WARNING_INCOMPLETE_ORDER,
            ),
        )
        return

    mismatch_warning: str | None = None
    if order_kw and length not in (6, 7):
        mismatch_warning = _WARNING_AMBIGUOUS
    elif product_kw and length != 8:
        mismatch_warning = _WARNING_AMBIGUOUS
    elif post_kw and length != 24 and not has_tipax and not has_chapar:
        mismatch_warning = _WARNING_AMBIGUOUS

    if mismatch_warning:
        claimed_spans.add((start, end))
        entities.append(
            ExtractedOperationalEntity(
                entity_type=EntityType.AMBIGUOUS_NUMBER,
                value=digits,
                normalized_value=digits,
                confidence_band="low",
                context_keyword=order_kw or product_kw or post_kw,
                warning=mismatch_warning,
            ),
        )


def extract_operational_entities(text: str) -> OperationalEntityExtractionResult:
    """Extract order/product/tracking entities and warnings from seller message text."""
    cleaned = text.strip()
    if not cleaned:
        return OperationalEntityExtractionResult()

    normalized = normalize_digits(cleaned)
    entities: list[ExtractedOperationalEntity] = []
    claimed_spans: set[tuple[int, int]] = set()

    _extract_iban_entities(normalized, entities, claimed_spans)

    digit_spans = sorted(
        _DIGIT_SPAN_RE.finditer(normalized),
        key=lambda m: len(m.group(0)),
        reverse=True,
    )
    for match in digit_spans:
        digits = match.group(0)
        start, end = match.span()
        if _span_fully_inside_claimed((start, end), claimed_spans):
            continue
        if len(digits) == 7:
            continue
        _classify_digit_span(
            normalized,
            start=start,
            end=end,
            digits=digits,
            entities=entities,
            claimed_spans=claimed_spans,
        )

    _extract_order_id_entities(normalized, entities, claimed_spans)
    entities = dedupe_entities_by_type_and_normalized_value_preserve_order(entities)

    return OperationalEntityExtractionResult(entities=tuple(entities))
