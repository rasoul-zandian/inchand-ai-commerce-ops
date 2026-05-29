"""Read-only Iran Post tracking verification via Ayantech Core API (manual/HITL only)."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.workflows.operational_entity_extraction import normalize_digits

logger = logging.getLogger(__name__)

_CARRIER = "iran_post"
_PROVIDER = "ayantech"
_PRIVATE_RAW_ROOT = Path("data/private")

_DIGITS_ONLY_RE = re.compile(r"^\d+$")
_DIGIT_CHAR_CLASS = r"0-9\u06f0-\u06f9\u0660-\u0669"
_DIGIT_LIKE_RUN_RE = re.compile(
    rf"[{_DIGIT_CHAR_CLASS}]"
    rf"(?:[\s\-–—_\u200c\u200d\u200e\u200f\ufeff.:،,;]*[{_DIGIT_CHAR_CLASS}]){{6,}}"
    rf"[{_DIGIT_CHAR_CLASS}]",
)
_ZWNJ_AND_BOM_RE = re.compile(r"[\u200c\u200d\u200e\u200f\ufeff]")
_SEPARATOR_COLLAPSE_RE = re.compile(r"[\s\-–—_\u200c\u200d.:،,;]+")
_IRAN_POST_MIN_LEN = 20
_IRAN_POST_MAX_LEN = 26
_IRAN_POST_PREFERRED_LEN = 24
_ORDER_ID_REJECT_MAX_LEN = 10
_PHONE_LEN = 11

_SUCCESS_STATUS_CODES = frozenset({"0", "00", "200", "success", "ok", "g00000"})
_FAILURE_STATUS_CODES = frozenset({"1", "2", "error", "failed", "fail", "notfound", "not_found"})

_TRACKING_KEYWORDS = (
    "کد رهگیری",
    "کد پیگیری",
    "رهگیری",
    "بارکد پستی",
    "مرسوله",
    "پست",
)
_ORDER_KEYWORDS = ("سفارش", "شماره سفارش", "order", "inc-")
_IBAN_KEYWORDS = ("شبا", "iban", "حساب", "واریز")

_PII_PARAMETER_KEYS = frozenset(
    {
        "ReceiverName",
        "ReceiverZip",
        "SenderName",
        "SenderZip",
    },
)


class IranPostTrackingCodeField(StrEnum):
    TRACE_NUMBER = "TraceNumber"
    PACKAGE_NUMBER = "PackageNumber"
    BOTH = "both"


@dataclass(frozen=True)
class IranPostTrackingRequest:
    """Outbound API request shape (token from settings only)."""

    trace_number: str
    package_number: str = ""


@dataclass(frozen=True)
class IranPostTrackingStatus:
    code: str | None
    description: str | None


@dataclass(frozen=True)
class IranPostTrackingEvent:
    datetime: str | None
    event_number: str | None
    description: str | None
    province: str | None


@dataclass(frozen=True)
class IranPostTrackingError(Exception):
    error_type: str
    error_message: str

    def __str__(self) -> str:
        return f"{self.error_type}: {self.error_message}"


@dataclass(frozen=True)
class TrackingCandidate:
    original_text_fragment: str
    normalized_code: str
    length: int
    plausible: bool
    reason: str
    start_offset: int = 0


@dataclass(frozen=True)
class TrackingExtractionDiagnostics:
    original_seller_text_length: int
    numeric_candidates_found: int
    normalized_candidates: tuple[str, ...]
    selected_tracking_code: str | None
    selected_candidate_reason: str | None
    rejected_candidates: tuple[tuple[str, str], ...] = ()
    extraction_source_message_id: str | None = None
    extraction_source_sender_type: str | None = None
    api_code_field: str | None = None
    payload_trace_number: str | None = None
    payload_package_number: str | None = None
    input_normalized_whole_text: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "original_seller_text_length": self.original_seller_text_length,
            "numeric_candidates_found": self.numeric_candidates_found,
            "normalized_candidates": list(self.normalized_candidates),
            "selected_tracking_code": self.selected_tracking_code,
            "selected_candidate_reason": self.selected_candidate_reason,
            "rejected_candidates": [
                {"code": code, "reason": reason} for code, reason in self.rejected_candidates
            ],
            "extraction_source_message_id": self.extraction_source_message_id,
            "extraction_source_sender_type": self.extraction_source_sender_type,
            "api_code_field": self.api_code_field,
            "payload_trace_number": self.payload_trace_number,
            "payload_package_number": self.payload_package_number,
            "input_normalized_whole_text": self.input_normalized_whole_text,
        }


@dataclass(frozen=True)
class IranPostTrackingResult:
    carrier: str = _CARRIER
    provider: str = _PROVIDER
    tracking_code: str = ""
    is_plausible_code: bool = False
    code_validation_warning: str | None = None
    verified: bool = False
    status_code: str | None = None
    status_description: str | None = None
    acceptance_datetime: str | None = None
    source: str | None = None
    destination: str | None = None
    service_type: str | None = None
    weight: str | None = None
    last_event_datetime: str | None = None
    last_event_province: str | None = None
    last_event_description: str | None = None
    event_count: int = 0
    events: tuple[IranPostTrackingEvent, ...] = ()
    safe_summary_fa: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    extraction_diagnostics: TrackingExtractionDiagnostics | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "carrier": self.carrier,
            "provider": self.provider,
            "tracking_code": self.tracking_code,
            "is_plausible_code": self.is_plausible_code,
            "code_validation_warning": self.code_validation_warning,
            "verified": self.verified,
            "status_code": self.status_code,
            "status_description": self.status_description,
            "acceptance_datetime": self.acceptance_datetime,
            "source": self.source,
            "destination": self.destination,
            "service_type": self.service_type,
            "weight": self.weight,
            "last_event_datetime": self.last_event_datetime,
            "last_event_province": self.last_event_province,
            "last_event_description": self.last_event_description,
            "event_count": self.event_count,
            "events": [
                {
                    "datetime": event.datetime,
                    "event_number": event.event_number,
                    "description": event.description,
                    "province": event.province,
                }
                for event in self.events
            ],
            "safe_summary_fa": self.safe_summary_fa,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }
        if self.extraction_diagnostics is not None:
            payload["extraction_diagnostics"] = self.extraction_diagnostics.to_safe_dict()
        return payload


HttpPostJsonFn = Callable[[str, Mapping[str, Any], float], Mapping[str, Any]]


def normalize_tracking_code(code: str) -> str:
    """Strip separators and normalize Persian/Arabic digits to ASCII digits only."""
    stripped = (code or "").strip()
    if not stripped:
        return ""
    text = normalize_digits(stripped)
    text = _ZWNJ_AND_BOM_RE.sub("", text)
    text = _SEPARATOR_COLLAPSE_RE.sub("", text)
    return "".join(character for character in text if character.isdigit())


_EXTRA_INFO_DESCRIPTION_KEY = "شرح"


def _collapse_whitespace(text: str) -> str:
    return " ".join((text or "").split())


def parse_iran_post_event_description(extra_info: str) -> str:
    """Parse Ayantech ExtraInfo into a safe event description (شرح only; no mail carrier name)."""
    stripped = (extra_info or "").strip()
    if not stripped:
        return ""
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return _collapse_whitespace(stripped)
        if isinstance(parsed, dict):
            description = parsed.get(_EXTRA_INFO_DESCRIPTION_KEY)
            if description is not None:
                return _collapse_whitespace(str(description))
    return _collapse_whitespace(stripped)


def normalize_iran_post_tracking_code_field(value: str | None) -> str:
    if not value:
        return IranPostTrackingCodeField.PACKAGE_NUMBER.value
    normalized = str(value).strip()
    lowered = normalized.lower().replace("_", "").replace(" ", "")
    if lowered in {"tracenumber", "trace"}:
        return IranPostTrackingCodeField.TRACE_NUMBER.value
    if lowered in {"packagenumber", "package"}:
        return IranPostTrackingCodeField.PACKAGE_NUMBER.value
    if lowered == "both":
        return IranPostTrackingCodeField.BOTH.value
    raise ValueError(
        f"invalid iran_post_tracking_code_field {value!r}; "
        "allowed: TraceNumber, PackageNumber, both",
    )


def _context_window(text: str, start: int, end: int, *, radius: int = 40) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return text[lo:hi]


def _has_tracking_keyword(context: str) -> bool:
    return any(keyword in context for keyword in _TRACKING_KEYWORDS)


def _looks_like_order_id(context: str, normalized: str) -> bool:
    if len(normalized) == 7:
        return True
    if 8 <= len(normalized) <= 10 and any(keyword in context for keyword in _ORDER_KEYWORDS):
        return True
    if "inc-" in context.lower() and normalized in context.replace("-", ""):
        return True
    return False


def _looks_like_iban(context: str, normalized: str) -> bool:
    if len(normalized) not in {23, 24, 25, 26}:
        return False
    if any(keyword in context for keyword in _IBAN_KEYWORDS):
        return True
    if re.search(r"\bIR\b", context, flags=re.IGNORECASE):
        return True
    return False


def _looks_like_phone(normalized: str) -> bool:
    return len(normalized) == _PHONE_LEN and normalized.startswith("09")


def _classify_digit_run(
    fragment: str,
    normalized: str,
    *,
    full_text: str,
    start_offset: int,
) -> TrackingCandidate:
    length = len(normalized)
    context = _context_window(full_text, start_offset, start_offset + len(fragment))

    if not normalized:
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code="",
            length=0,
            plausible=False,
            reason="empty_after_normalization",
            start_offset=start_offset,
        )
    if not _DIGITS_ONLY_RE.match(normalized):
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code=normalized,
            length=length,
            plausible=False,
            reason="contains_non_digit_after_normalization",
            start_offset=start_offset,
        )
    if _looks_like_phone(normalized):
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code=normalized,
            length=length,
            plausible=False,
            reason="looks_like_phone",
            start_offset=start_offset,
        )
    if _looks_like_iban(context, normalized):
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code=normalized,
            length=length,
            plausible=False,
            reason="looks_like_iban",
            start_offset=start_offset,
        )
    if _looks_like_order_id(context, normalized):
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code=normalized,
            length=length,
            plausible=False,
            reason="looks_like_order_id",
            start_offset=start_offset,
        )
    if length <= _ORDER_ID_REJECT_MAX_LEN:
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code=normalized,
            length=length,
            plausible=False,
            reason="too_short",
            start_offset=start_offset,
        )
    if length > _IRAN_POST_MAX_LEN:
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code=normalized,
            length=length,
            plausible=False,
            reason="too_long",
            start_offset=start_offset,
        )
    if length < _IRAN_POST_MIN_LEN:
        return TrackingCandidate(
            original_text_fragment=fragment,
            normalized_code=normalized,
            length=length,
            plausible=False,
            reason="length_outside_iran_post_range",
            start_offset=start_offset,
        )

    reason = "plausible_exact_24" if length == _IRAN_POST_PREFERRED_LEN else "plausible_length"
    return TrackingCandidate(
        original_text_fragment=fragment,
        normalized_code=normalized,
        length=length,
        plausible=True,
        reason=reason,
        start_offset=start_offset,
    )


def extract_iran_post_tracking_candidates(text: str) -> list[TrackingCandidate]:
    """Find and classify digit-like runs that may be Iran Post tracking codes."""
    source = text or ""
    if not source.strip():
        return []

    seen_normalized: set[str] = set()
    candidates: list[TrackingCandidate] = []

    for match in _DIGIT_LIKE_RUN_RE.finditer(source):
        fragment = match.group(0)
        normalized = normalize_tracking_code(fragment)
        if not normalized or normalized in seen_normalized:
            if normalized:
                candidates.append(
                    TrackingCandidate(
                        original_text_fragment=fragment,
                        normalized_code=normalized,
                        length=len(normalized),
                        plausible=False,
                        reason="duplicate",
                        start_offset=match.start(),
                    ),
                )
            continue
        seen_normalized.add(normalized)
        candidates.append(
            _classify_digit_run(
                fragment,
                normalized,
                full_text=source,
                start_offset=match.start(),
            ),
        )

    whole_normalized = normalize_tracking_code(source)
    if whole_normalized and whole_normalized not in seen_normalized:
        plausible_whole, _ = looks_like_iran_post_tracking_code(whole_normalized)
        if plausible_whole:
            candidates.append(
                TrackingCandidate(
                    original_text_fragment=source.strip(),
                    normalized_code=whole_normalized,
                    length=len(whole_normalized),
                    plausible=True,
                    reason="plausible_whole_message",
                    start_offset=0,
                ),
            )

    return candidates


def _candidate_selection_score(candidate: TrackingCandidate, full_text: str) -> int:
    if not candidate.plausible:
        return -1
    score = candidate.length
    if candidate.length == _IRAN_POST_PREFERRED_LEN:
        score += 1000
    context = _context_window(
        full_text,
        candidate.start_offset,
        candidate.start_offset + len(candidate.original_text_fragment),
    )
    if _has_tracking_keyword(context):
        score += 500
    return score


def select_iran_post_tracking_candidate(
    candidates: Sequence[TrackingCandidate],
    full_text: str,
) -> tuple[TrackingCandidate | None, str]:
    """Pick the best plausible candidate with a deterministic reason string."""
    plausible = [candidate for candidate in candidates if candidate.plausible]
    if not plausible:
        return None, "no_plausible_candidate"

    ranked = sorted(
        plausible,
        key=lambda candidate: (
            -_candidate_selection_score(candidate, full_text),
            -candidate.length,
            candidate.start_offset,
        ),
    )
    selected = ranked[0]
    if selected.length == _IRAN_POST_PREFERRED_LEN:
        context = _context_window(
            full_text,
            selected.start_offset,
            selected.start_offset + len(selected.original_text_fragment),
        )
        if _has_tracking_keyword(context):
            reason = "exact_24_near_tracking_keyword"
        else:
            reason = "exact_24_digit"
    elif _has_tracking_keyword(
        _context_window(
            full_text,
            selected.start_offset,
            selected.start_offset + len(selected.original_text_fragment),
        ),
    ):
        reason = "keyword_proximity"
    elif len(plausible) > 1:
        reason = "longest_plausible_among_multiple"
    else:
        reason = selected.reason

    return selected, reason


def build_tracking_extraction_diagnostics(
    text: str,
    *,
    message_id: str | None = None,
    sender_type: str | None = None,
    code_field: str | None = None,
    payload_trace_number: str | None = None,
    payload_package_number: str | None = None,
) -> TrackingExtractionDiagnostics:
    candidates = extract_iran_post_tracking_candidates(text)
    selected, reason = select_iran_post_tracking_candidate(candidates, text)
    normalized_all = tuple(
        dict.fromkeys(
            candidate.normalized_code for candidate in candidates if candidate.normalized_code
        ),
    )
    rejected = tuple(
        (candidate.normalized_code, candidate.reason)
        for candidate in candidates
        if not candidate.plausible and candidate.normalized_code
    )
    return TrackingExtractionDiagnostics(
        original_seller_text_length=len(text or ""),
        numeric_candidates_found=len(candidates),
        normalized_candidates=normalized_all,
        selected_tracking_code=selected.normalized_code if selected else None,
        selected_candidate_reason=reason if selected else reason,
        rejected_candidates=rejected,
        extraction_source_message_id=message_id,
        extraction_source_sender_type=sender_type,
        api_code_field=code_field,
        payload_trace_number=payload_trace_number,
        payload_package_number=payload_package_number,
        input_normalized_whole_text=normalize_tracking_code(text) or None,
    )


def resolve_tracking_code_from_text(
    text: str,
    *,
    message_id: str | None = None,
    sender_type: str | None = None,
    code_field: str | None = None,
) -> tuple[str | None, TrackingExtractionDiagnostics]:
    """Select tracking code from free text and return safe diagnostics."""
    candidates = extract_iran_post_tracking_candidates(text)
    selected, reason = select_iran_post_tracking_candidate(candidates, text)
    payload_trace: str | None = None
    payload_package: str | None = None
    if selected is not None:
        _, params = build_iran_post_request_payload(
            selected.normalized_code,
            token="",
            code_field=code_field,
        )
        payload_trace = params.get("TraceNumber") or None
        payload_package = params.get("PackageNumber") or None
        if payload_trace == "":
            payload_trace = None
        if payload_package == "":
            payload_package = None

    diagnostics = build_tracking_extraction_diagnostics(
        text,
        message_id=message_id,
        sender_type=sender_type,
        code_field=code_field,
        payload_trace_number=payload_trace,
        payload_package_number=payload_package,
    )
    diagnostics = TrackingExtractionDiagnostics(
        original_seller_text_length=diagnostics.original_seller_text_length,
        numeric_candidates_found=diagnostics.numeric_candidates_found,
        normalized_candidates=diagnostics.normalized_candidates,
        selected_tracking_code=selected.normalized_code if selected else None,
        selected_candidate_reason=reason,
        rejected_candidates=diagnostics.rejected_candidates,
        extraction_source_message_id=message_id,
        extraction_source_sender_type=sender_type,
        api_code_field=code_field,
        payload_trace_number=payload_trace,
        payload_package_number=payload_package,
        input_normalized_whole_text=diagnostics.input_normalized_whole_text,
    )
    return (selected.normalized_code if selected else None), diagnostics


def looks_like_iran_post_tracking_code(code: str) -> tuple[bool, str | None]:
    """Heuristic plausibility check for Iran Post numeric tracking codes."""
    normalized = normalize_tracking_code(code)
    if not normalized:
        return False, "empty_tracking_code"
    if not _DIGITS_ONLY_RE.match(normalized):
        return False, "non_numeric_tracking_code"
    length = len(normalized)
    if length <= _ORDER_ID_REJECT_MAX_LEN:
        return False, "too_short_for_iran_post"
    if length < _IRAN_POST_MIN_LEN or length > _IRAN_POST_MAX_LEN:
        return False, "length_outside_iran_post_range"
    warning: str | None = None
    if length != _IRAN_POST_PREFERRED_LEN:
        warning = f"unusual_length_{length}"
    return True, warning


def build_iran_post_request_payload(
    code: str,
    token: str,
    *,
    code_field: str | None = None,
    package_number: str = "",
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build Ayantech PostTrackingInquiry JSON body and safe parameter summary."""
    trace = normalize_tracking_code(code)
    field_name = normalize_iran_post_tracking_code_field(code_field)
    params = {"PackageNumber": "", "TraceNumber": ""}
    if field_name == IranPostTrackingCodeField.PACKAGE_NUMBER.value:
        params["PackageNumber"] = trace
    elif field_name == IranPostTrackingCodeField.BOTH.value:
        params["PackageNumber"] = trace
        params["TraceNumber"] = trace
    else:
        params["TraceNumber"] = trace
    if package_number:
        params["PackageNumber"] = normalize_tracking_code(package_number)
    payload = {
        "Identity": {"Token": token},
        "Parameters": params,
    }
    return payload, dict(params)


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_events(raw_events: object) -> tuple[IranPostTrackingEvent, ...]:
    if not isinstance(raw_events, list):
        return ()
    events: list[IranPostTrackingEvent] = []
    for item in raw_events:
        if not isinstance(item, dict):
            continue
        raw_extra = item.get("ExtraInfo")
        extra_text = str(raw_extra).strip() if raw_extra is not None else ""
        parsed_description = parse_iran_post_event_description(extra_text) if extra_text else None
        events.append(
            IranPostTrackingEvent(
                datetime=_optional_str(item.get("DateTime")),
                event_number=_optional_str(item.get("EventNumber")),
                description=parsed_description or None,
                province=_optional_str(item.get("Province")),
            ),
        )
    return tuple(events)


def _status_indicates_success(code: str | None) -> bool:
    if not code:
        return False
    normalized = code.strip().lower()
    return normalized in _SUCCESS_STATUS_CODES


def _status_indicates_failure(code: str | None) -> bool:
    if not code:
        return False
    normalized = code.strip().lower()
    return normalized in _FAILURE_STATUS_CODES


def _build_safe_summary_fa(
    *,
    verified: bool,
    tracking_code: str,
    status_description: str | None,
    last_event_description: str | None,
    last_event_province: str | None,
    event_count: int,
) -> str:
    if not verified:
        if status_description:
            return f"استعلام کد رهگیری {tracking_code}: تأیید نشد ({status_description})."
        return f"استعلام کد رهگیری {tracking_code}: نتیجه تأییدشده‌ای دریافت نشد."
    parts = [f"کد رهگیری {tracking_code} در سامانه پست بررسی شد."]
    if last_event_description:
        detail = last_event_description
        if last_event_province:
            detail = f"{detail} ({last_event_province})"
        parts.append(f"آخرین وضعیت: {detail}.")
    elif status_description:
        parts.append(f"وضعیت: {status_description}.")
    if event_count > 0:
        parts.append(f"تعداد رویداد: {event_count}.")
    return " ".join(parts)


def parse_iran_post_response(
    response_json: Mapping[str, Any],
    tracking_code: str,
) -> IranPostTrackingResult:
    """Parse API JSON into a privacy-safe normalized result."""
    normalized_code = normalize_tracking_code(tracking_code)
    plausible, warning = looks_like_iran_post_tracking_code(normalized_code)

    status_block = response_json.get("Status")
    status = IranPostTrackingStatus(code=None, description=None)
    if isinstance(status_block, dict):
        status = IranPostTrackingStatus(
            code=_optional_str(status_block.get("Code")),
            description=_optional_str(status_block.get("Description")),
        )

    params = response_json.get("Parameters")
    params_dict: dict[str, Any] = params if isinstance(params, dict) else {}

    for key in _PII_PARAMETER_KEYS:
        params_dict.pop(key, None)

    events = _parse_events(params_dict.get("PostPackageStatusDetail"))
    acceptance = _optional_str(params_dict.get("AcceptanceDateTime"))
    source = _optional_str(params_dict.get("Source"))
    destination = _optional_str(params_dict.get("Destination"))
    service_type = _optional_str(params_dict.get("ServiceType"))
    weight = _optional_str(params_dict.get("Weight"))

    last_event = events[-1] if events else None
    has_operational_payload = bool(events or acceptance or source or destination)

    verified = False
    if _status_indicates_failure(status.code) and not has_operational_payload:
        verified = False
    elif has_operational_payload:
        verified = True
    elif _status_indicates_success(status.code):
        verified = True

    safe_summary = _build_safe_summary_fa(
        verified=verified,
        tracking_code=normalized_code,
        status_description=status.description,
        last_event_description=last_event.description if last_event else None,
        last_event_province=last_event.province if last_event else None,
        event_count=len(events),
    )

    return IranPostTrackingResult(
        tracking_code=normalized_code,
        is_plausible_code=plausible,
        code_validation_warning=warning,
        verified=verified,
        status_code=status.code,
        status_description=status.description,
        acceptance_datetime=acceptance,
        source=source,
        destination=destination,
        service_type=service_type,
        weight=weight,
        last_event_datetime=last_event.datetime if last_event else None,
        last_event_province=last_event.province if last_event else None,
        last_event_description=last_event.description if last_event else None,
        event_count=len(events),
        events=events,
        safe_summary_fa=safe_summary,
    )


def _default_post_json(url: str, payload: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise IranPostTrackingError(
            error_type="http_error",
            error_message=f"HTTP {exc.code}: {detail}",
        ) from exc
    except urllib.error.URLError as exc:
        if "timed out" in str(exc).lower():
            raise IranPostTrackingError(
                error_type="timeout",
                error_message=str(exc),
            ) from exc
        raise IranPostTrackingError(
            error_type="http_error",
            error_message=str(exc),
        ) from exc

    if not raw.strip():
        raise IranPostTrackingError(
            error_type="parse_error",
            error_message="empty_response_body",
        )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise IranPostTrackingError(
            error_type="parse_error",
            error_message="response_not_json_object",
        )
    return parsed


def verify_iran_post_tracking_code(
    code: str,
    *,
    settings: AppSettings | None = None,
    http_client: HttpPostJsonFn | None = None,
    code_field_override: str | None = None,
    extraction_source_message_id: str | None = None,
    extraction_source_sender_type: str | None = None,
) -> IranPostTrackingResult:
    """Verify a tracking code via Ayantech (read-only; no side effects)."""
    cfg = settings or get_settings()
    code_field = normalize_iran_post_tracking_code_field(
        code_field_override or cfg.iran_post_tracking_code_field,
    )
    selected_code, diagnostics = resolve_tracking_code_from_text(
        code,
        message_id=extraction_source_message_id,
        sender_type=extraction_source_sender_type,
        code_field=code_field,
    )
    normalized = selected_code or normalize_tracking_code(code)
    plausible, warning = looks_like_iran_post_tracking_code(normalized)

    if not cfg.iran_post_tracking_enabled:
        return IranPostTrackingResult(
            tracking_code=normalized,
            is_plausible_code=plausible,
            code_validation_warning=warning,
            verified=False,
            error_type="disabled",
            error_message="iran_post_tracking_disabled",
            safe_summary_fa="استعلام پست ایران غیرفعال است.",
            extraction_diagnostics=diagnostics,
        )

    token = (cfg.iran_post_tracking_token or "").strip()
    if not token:
        return IranPostTrackingResult(
            tracking_code=normalized,
            is_plausible_code=plausible,
            code_validation_warning=warning,
            verified=False,
            error_type="missing_token",
            error_message="IRAN_POST_TRACKING_TOKEN not configured",
            safe_summary_fa="توکن استعلام پست تنظیم نشده است.",
            extraction_diagnostics=diagnostics,
        )

    if not plausible:
        return IranPostTrackingResult(
            tracking_code=normalized,
            is_plausible_code=False,
            code_validation_warning=warning,
            verified=False,
            error_type="invalid_code",
            error_message=(
                warning or diagnostics.selected_candidate_reason or "invalid_tracking_code"
            ),
            safe_summary_fa="کد رهگیری برای استعلام پست ایران مناسب به نظر نمی‌رسد.",
            extraction_diagnostics=diagnostics,
        )

    url = (cfg.iran_post_tracking_api_url or "").strip()
    if not url:
        return IranPostTrackingResult(
            tracking_code=normalized,
            is_plausible_code=plausible,
            code_validation_warning=warning,
            verified=False,
            error_type="misconfigured",
            error_message="iran_post_tracking_api_url_missing",
            extraction_diagnostics=diagnostics,
        )

    payload, param_summary = build_iran_post_request_payload(
        normalized,
        token,
        code_field=code_field,
    )
    diagnostics = TrackingExtractionDiagnostics(
        original_seller_text_length=diagnostics.original_seller_text_length,
        numeric_candidates_found=diagnostics.numeric_candidates_found,
        normalized_candidates=diagnostics.normalized_candidates,
        selected_tracking_code=normalized,
        selected_candidate_reason=diagnostics.selected_candidate_reason,
        rejected_candidates=diagnostics.rejected_candidates,
        extraction_source_message_id=diagnostics.extraction_source_message_id,
        extraction_source_sender_type=diagnostics.extraction_source_sender_type,
        api_code_field=code_field,
        payload_trace_number=param_summary.get("TraceNumber") or None,
        payload_package_number=param_summary.get("PackageNumber") or None,
        input_normalized_whole_text=diagnostics.input_normalized_whole_text,
    )

    post_fn = http_client or _default_post_json
    timeout = float(cfg.iran_post_tracking_timeout_seconds)

    try:
        response_json = post_fn(url, payload, timeout)
    except IranPostTrackingError as exc:
        return IranPostTrackingResult(
            tracking_code=normalized,
            is_plausible_code=plausible,
            code_validation_warning=warning,
            verified=False,
            error_type=exc.error_type,
            error_message=exc.error_message,
            safe_summary_fa=f"استعلام ناموفق: {exc.error_message[:120]}",
            extraction_diagnostics=diagnostics,
        )

    result = parse_iran_post_response(response_json, normalized)
    result = IranPostTrackingResult(
        carrier=result.carrier,
        provider=result.provider,
        tracking_code=result.tracking_code,
        is_plausible_code=result.is_plausible_code,
        code_validation_warning=result.code_validation_warning,
        verified=result.verified,
        status_code=result.status_code,
        status_description=result.status_description,
        acceptance_datetime=result.acceptance_datetime,
        source=result.source,
        destination=result.destination,
        service_type=result.service_type,
        weight=result.weight,
        last_event_datetime=result.last_event_datetime,
        last_event_province=result.last_event_province,
        last_event_description=result.last_event_description,
        event_count=result.event_count,
        events=result.events,
        safe_summary_fa=result.safe_summary_fa,
        error_type=result.error_type,
        error_message=result.error_message,
        extraction_diagnostics=diagnostics,
    )
    if cfg.iran_post_tracking_log_raw:
        logger.info(
            "iran_post_tracking_response tracking_code=%s verified=%s status_code=%s field=%s",
            normalized,
            result.verified,
            result.status_code,
            code_field,
        )
    return result


def _path_has_data_private_segment(resolved: Path) -> bool:
    parts = resolved.parts
    for index, part in enumerate(parts[:-1]):
        if part == "data" and parts[index + 1] == "private":
            return True
    return False


def assert_private_raw_output_path(path: Path) -> Path:
    """Raw API archives must live under a data/private/ path segment."""
    resolved = path.expanduser().resolve()
    if not _path_has_data_private_segment(resolved):
        raise ValueError(f"raw output must be under data/private/, got {path}")
    return resolved


def extract_plausible_iran_post_tracking_candidates_from_text(text: str) -> tuple[str, ...]:
    """Backward-compatible: plausible normalized codes in selection order."""
    candidates = extract_iran_post_tracking_candidates(text)
    selected, _ = select_iran_post_tracking_candidate(candidates, text)
    ordered: list[str] = []
    if selected is not None:
        ordered.append(selected.normalized_code)
    for candidate in candidates:
        if candidate.plausible and candidate.normalized_code not in ordered:
            ordered.append(candidate.normalized_code)
    return tuple(ordered)


def infer_plausible_iran_post_tracking_code_from_text(text: str) -> str | None:
    """Return the selected Iran Post code from free text, if any."""
    candidates = extract_iran_post_tracking_candidates(text)
    selected, _ = select_iran_post_tracking_candidate(candidates, text)
    return selected.normalized_code if selected else None


def compute_tracking_verification_recommendation(
    *,
    pending_request_type: str | None,
    pending_request_fulfilled: bool,
    tracking_code: str | None,
) -> bool:
    """True when manual Iran Post verification is recommended (no API call)."""
    if pending_request_type != "requested_tracking_code":
        return False
    if not pending_request_fulfilled:
        return False
    if not tracking_code:
        return False
    plausible, _ = looks_like_iran_post_tracking_code(tracking_code)
    return plausible


def build_tracking_verification_recommendation_metadata(
    *,
    pending_request_type: str | None,
    pending_request_fulfilled: bool,
    tracking_codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Safe metadata for graph/UI (advisory only)."""
    codes = [normalize_tracking_code(code) for code in (tracking_codes or ()) if code]
    primary = codes[-1] if codes else None
    recommended = compute_tracking_verification_recommendation(
        pending_request_type=pending_request_type,
        pending_request_fulfilled=pending_request_fulfilled,
        tracking_code=primary,
    )
    if not recommended:
        return {
            "tracking_verification_recommended": False,
            "tracking_verification_carrier_candidate": None,
        }
    return {
        "tracking_verification_recommended": True,
        "tracking_verification_carrier_candidate": _CARRIER,
    }


def build_tracking_verification_chat_reply(result: IranPostTrackingResult) -> str:
    """Concise Persian support reply for manual sandbox chat (not auto-sent live)."""
    if result.error_type in {"timeout", "http_error"}:
        return (
            "کد رهگیری دریافت شد، اما در حال حاضر امکان استعلام از سامانه پست وجود ندارد. "
            "درخواست شما برای بررسی ثبت شد."
        )
    if result.verified and result.last_event_description:
        province = (result.last_event_province or "").strip() or "—"
        return (
            f"کد رهگیری دریافت و با موفقیت استعلام شد. "
            f"آخرین وضعیت مرسوله: {result.last_event_description} در {province}. "
            "درخواست شما در دست بررسی قرار گرفت."
        )
    if result.verified:
        return (
            "کد رهگیری دریافت و با موفقیت استعلام شد. "
            "اطلاعات مرسوله در سامانه پست ثبت شده است و درخواست شما در دست بررسی قرار گرفت."
        )
    if result.is_plausible_code:
        return "کد رهگیری ارسال‌شده در سامانه پست تأیید نشد. لطفاً کد رهگیری صحیح را ارسال کنید."
    return "کد رهگیری ارسال‌شده در سامانه پست تأیید نشد. لطفاً کد رهگیری صحیح را ارسال کنید."


def assert_safe_tracking_result_payload(payload: Mapping[str, Any]) -> None:
    """Reject PII or prompt-like keys from persisted/session payloads."""
    forbidden = frozenset(
        {
            "ReceiverName",
            "ReceiverZip",
            "SenderName",
            "SenderZip",
            "Identity",
            "Token",
            "raw_prompt",
            "transcript",
        },
    )
    for key in payload:
        if key in forbidden:
            raise ValueError(f"forbidden tracking payload key: {key}")
