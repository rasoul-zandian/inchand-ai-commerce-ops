"""Read-only Inchand internal order lookup (manual/HITL only; no mutations)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.workflows.operational_entity_extraction import extract_order_ids, normalize_digits

_INC_ORDER_RE = re.compile(r"\bINC\s*[-_:\s]*(\d{7})(?!\d)", re.IGNORECASE)
_STANDALONE_ORDER_7_RE = re.compile(r"(?<!\d)(\d{7})(?!\d)")
_LONG_DIGIT_ONLY_RE = re.compile(r"^\d{10,}$")

_DELIVERED_STATUS_MARKERS = (
    "تحویل شده",
    "تحویل مشتری",
    "تحویل گیرنده",
)
_PARCEL_DELIVERED_STATUS_CODE = 1

_PII_FORBIDDEN_KEYS = frozenset(
    {
        "user_id",
        "receiver_name",
        "sender_name",
        "ReceiverName",
        "SenderName",
        "raw_response",
        "Identity",
        "Token",
    },
)

HttpGetJsonFn = Callable[[str, Mapping[str, str], float], Mapping[str, Any]]


@dataclass(frozen=True)
class InchandOrderLookupRequest:
    """Outbound order lookup request."""

    order_id: str


@dataclass(frozen=True)
class InchandOrderItem:
    product_id: int | None
    quantity: int | None


@dataclass(frozen=True)
class InchandOrderParcel:
    tracking_code: str | None
    status: int | None
    status_name: str | None
    shamsi_created_at: str | None


@dataclass(frozen=True)
class InchandOrderProvider:
    shop_name: str | None
    provider_status: str | None
    delivered_at: str | None
    min_delivery_date: str | None
    max_delivery_date: str | None
    parcel: InchandOrderParcel | None
    item_count: int
    items_summary: tuple[InchandOrderItem, ...]


class InchandOrderLookupError(Exception):
    error_type: str
    error_message: str

    def __init__(self, *, error_type: str, error_message: str) -> None:
        self.error_type = error_type
        self.error_message = error_message
        super().__init__(error_message)

    def __str__(self) -> str:
        return f"{self.error_type}: {self.error_message}"


@dataclass(frozen=True)
class InchandOrderLookupResult:
    order_id: str = ""
    found: bool = False
    order_status: str | None = None
    payment_status: str | None = None
    created_at: str | None = None
    provider_count: int = 0
    providers: tuple[InchandOrderProvider, ...] = ()
    has_parcel_tracking_code: bool = False
    primary_parcel_tracking_code: str | None = None
    primary_provider_status: str | None = None
    primary_parcel_status_name: str | None = None
    is_delivered_in_inchand: bool = False
    delivery_source: str | None = None
    code_validation_warning: str | None = None
    safe_summary_fa: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "found": self.found,
            "order_status": self.order_status,
            "payment_status": self.payment_status,
            "created_at": self.created_at,
            "provider_count": self.provider_count,
            "providers": [
                {
                    "shop_name": provider.shop_name,
                    "provider_status": provider.provider_status,
                    "delivered_at": provider.delivered_at,
                    "min_delivery_date": provider.min_delivery_date,
                    "max_delivery_date": provider.max_delivery_date,
                    "parcel": (
                        {
                            "tracking_code": provider.parcel.tracking_code,
                            "status": provider.parcel.status,
                            "status_name": provider.parcel.status_name,
                            "shamsi_created_at": provider.parcel.shamsi_created_at,
                        }
                        if provider.parcel is not None
                        else None
                    ),
                    "item_count": provider.item_count,
                    "items_summary": [
                        {
                            "product_id": item.product_id,
                            "quantity": item.quantity,
                        }
                        for item in provider.items_summary
                    ],
                }
                for provider in self.providers
            ],
            "has_parcel_tracking_code": self.has_parcel_tracking_code,
            "primary_parcel_tracking_code": self.primary_parcel_tracking_code,
            "primary_provider_status": self.primary_provider_status,
            "primary_parcel_status_name": self.primary_parcel_status_name,
            "is_delivered_in_inchand": self.is_delivered_in_inchand,
            "delivery_source": self.delivery_source,
            "code_validation_warning": self.code_validation_warning,
            "safe_summary_fa": self.safe_summary_fa,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_inchand_order_id(seven_digits: str) -> str:
    return f"INC-{seven_digits}"


def _extract_seven_digit_candidates(text: str) -> tuple[str, ...]:
    normalized = normalize_digits(text or "")
    if not normalized.strip():
        return ()
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _INC_ORDER_RE.finditer(normalized):
        digits = match.group(1)
        if digits not in seen:
            seen.add(digits)
            ordered.append(digits)
    for match in _STANDALONE_ORDER_7_RE.finditer(normalized):
        digits = match.group(1)
        if digits not in seen:
            seen.add(digits)
            ordered.append(digits)
    return tuple(ordered)


def normalize_inchand_order_id(value: str) -> str:
    """Normalize free text or order token to INC-#######; empty if not a valid order id."""
    text = (value or "").strip()
    if not text:
        return ""
    normalized = normalize_digits(text)
    compact = re.sub(r"\s+", "", normalized)
    if _LONG_DIGIT_ONLY_RE.match(compact) and not _INC_ORDER_RE.search(normalized):
        return ""
    candidates = _extract_seven_digit_candidates(text)
    if not candidates:
        return ""
    return _canonical_inchand_order_id(candidates[0])


def resolve_inchand_order_id_from_text(
    text: str,
) -> tuple[str | None, str | None]:
    """Return (INC-order-id, warning) from text; warn when multiple 7-digit ids found."""
    candidates = _extract_seven_digit_candidates(text)
    if not candidates:
        return None, None
    if len(candidates) > 1:
        return _canonical_inchand_order_id(candidates[0]), "multiple_order_ids_found"
    return _canonical_inchand_order_id(candidates[0]), None


def looks_like_inchand_order_id(value: str) -> bool:
    """True for 7-digit or INC-prefixed Inchand order codes (not parcel tracking codes)."""
    return bool(normalize_inchand_order_id(value))


def resolve_inchand_api_token(settings: AppSettings | None = None) -> str | None:
    """API token from INCHAND_API_KEY_VALUE, else LIVE_ROOMS_API_TOKEN."""
    cfg = settings or get_settings()
    primary = (cfg.inchand_api_key_value or "").strip()
    if primary:
        return primary
    fallback = (cfg.live_rooms_api_token or "").strip()
    return fallback or None


def build_order_lookup_url(order_id: str, settings: AppSettings | None = None) -> str:
    cfg = settings or get_settings()
    base = (cfg.inchand_api_base_url or "").strip().rstrip("/")
    normalized = normalize_inchand_order_id(order_id)
    if not normalized:
        raise ValueError(f"invalid order id for lookup: {order_id!r}")
    return f"{base}/orders/{normalized}"


def build_order_lookup_headers(settings: AppSettings | None = None) -> dict[str, str]:
    cfg = settings or get_settings()
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    token = resolve_inchand_api_token(cfg)
    if token:
        key_name = (cfg.inchand_api_key_name or "Authorization").strip() or "Authorization"
        headers[key_name] = token
    return headers


def _text_indicates_delivered(text: str | None) -> bool:
    if not text:
        return False
    lowered = text.strip().lower()
    return any(marker in lowered for marker in _DELIVERED_STATUS_MARKERS)


def _detect_delivery_source(result: InchandOrderLookupResult) -> str | None:
    if not result.is_delivered_in_inchand:
        return None
    primary = result.providers[0] if result.providers else None
    if primary and primary.parcel and _text_indicates_delivered(primary.parcel.status_name):
        return "parcel_status_detail"
    if primary and primary.parcel and primary.parcel.status == _PARCEL_DELIVERED_STATUS_CODE:
        return "parcel_status_code"
    if primary and _text_indicates_delivered(primary.provider_status):
        return "provider_status"
    if _text_indicates_delivered(result.order_status):
        return "order_status"
    return "order_status"


def is_delivered_order_state(result: InchandOrderLookupResult) -> bool:
    """True when Inchand marks the order or parcel as delivered to customer."""
    if not result.found:
        return False
    if _text_indicates_delivered(result.order_status):
        return True
    for provider in result.providers:
        if _text_indicates_delivered(provider.provider_status):
            return True
        if provider.parcel is None:
            continue
        if _text_indicates_delivered(provider.parcel.status_name):
            return True
        if provider.parcel.status == _PARCEL_DELIVERED_STATUS_CODE:
            return True
    return False


def _parse_parcel(raw: Mapping[str, Any] | None) -> InchandOrderParcel | None:
    if not isinstance(raw, dict):
        return None
    status_detail = raw.get("status_detail")
    status_name: str | None = None
    if isinstance(status_detail, dict):
        status_name = _optional_str(status_detail.get("name"))
    status_raw = raw.get("status")
    status_value: int | None = None
    if status_raw is not None and str(status_raw).strip().isdigit():
        status_value = int(str(status_raw).strip())
    return InchandOrderParcel(
        tracking_code=_optional_str(raw.get("tracking_code")),
        status=status_value,
        status_name=status_name,
        shamsi_created_at=_optional_str(raw.get("shamsi_created_at")),
    )


def _parse_items(raw_items: object) -> tuple[InchandOrderItem, ...]:
    if not isinstance(raw_items, list):
        return ()
    items: list[InchandOrderItem] = []
    for entry in raw_items:
        if not isinstance(entry, dict):
            continue
        product_raw = entry.get("product_id")
        product_id: int | None = None
        if product_raw is not None and str(product_raw).strip().isdigit():
            product_id = int(str(product_raw).strip())
        quantity_raw = entry.get("quantity")
        quantity: int | None = None
        if quantity_raw is not None and str(quantity_raw).strip().isdigit():
            quantity = int(str(quantity_raw).strip())
        items.append(InchandOrderItem(product_id=product_id, quantity=quantity))
    return tuple(items)


def _parse_providers(raw_providers: object) -> tuple[InchandOrderProvider, ...]:
    if not isinstance(raw_providers, list):
        return ()
    providers: list[InchandOrderProvider] = []
    for entry in raw_providers:
        if not isinstance(entry, dict):
            continue
        items = _parse_items(entry.get("items"))
        providers.append(
            InchandOrderProvider(
                shop_name=_optional_str(entry.get("shop_name")),
                provider_status=_optional_str(entry.get("status")),
                delivered_at=_optional_str(entry.get("delivered_at")),
                min_delivery_date=_optional_str(entry.get("min_delivery_date")),
                max_delivery_date=_optional_str(entry.get("max_delivery_date")),
                parcel=_parse_parcel(
                    entry.get("parcel") if isinstance(entry.get("parcel"), dict) else None,
                ),
                item_count=len(items),
                items_summary=items,
            ),
        )
    return tuple(providers)


def _build_safe_summary_fa(result: InchandOrderLookupResult) -> str:
    if not result.found:
        if result.error_message:
            return f"استعلام سفارش {result.order_id}: {result.error_message}"
        return f"استعلام سفارش {result.order_id}: سفارش یافت نشد."
    parts = [f"وضعیت سفارش {result.order_id} در اینچند"]
    if result.order_status:
        parts.append(f": {result.order_status}")
    parts.append(".")
    if result.primary_parcel_status_name:
        parts.append(f" وضعیت مرسوله: {result.primary_parcel_status_name}.")
    elif result.primary_provider_status:
        parts.append(f" وضعیت ارسال: {result.primary_provider_status}.")
    if result.primary_parcel_tracking_code:
        parts.append(f" کد رهگیری مرسوله: {result.primary_parcel_tracking_code}.")
    return "".join(parts)


def parse_inchand_order_response(
    response_json: Mapping[str, Any],
    order_id: str,
    *,
    code_validation_warning: str | None = None,
) -> InchandOrderLookupResult:
    """Parse Inchand order API JSON into a privacy-safe normalized result."""
    normalized_order_id = normalize_inchand_order_id(order_id)
    data: Mapping[str, Any] | None = None
    wrapped = response_json.get("data")
    if isinstance(wrapped, dict):
        data = wrapped
    else:
        # Some observed Inchand environments return the order object directly (no wrapper).
        direct_keys = {"id", "order_status", "providers", "tracking_code", "created_at"}
        if any(key in response_json for key in direct_keys):
            data = response_json
    if not isinstance(data, dict):
        return InchandOrderLookupResult(
            order_id=normalized_order_id,
            found=False,
            error_type="not_found",
            error_message="order_not_found",
            code_validation_warning=code_validation_warning,
            safe_summary_fa=f"سفارش {normalized_order_id} در اینچند یافت نشد.",
        )

    providers = _parse_providers(data.get("providers"))
    primary = providers[0] if providers else None
    primary_parcel = primary.parcel if primary else None
    primary_tracking = primary_parcel.tracking_code if primary_parcel else None

    base = InchandOrderLookupResult(
        order_id=normalized_order_id,
        found=True,
        order_status=_optional_str(data.get("order_status")),
        payment_status=_optional_str(data.get("payment_status")),
        created_at=_optional_str(data.get("created_at")),
        provider_count=len(providers),
        providers=providers,
        has_parcel_tracking_code=bool(primary_tracking),
        primary_parcel_tracking_code=primary_tracking,
        primary_provider_status=primary.provider_status if primary else None,
        primary_parcel_status_name=primary_parcel.status_name if primary_parcel else None,
        code_validation_warning=code_validation_warning,
    )
    delivered = is_delivered_order_state(base)
    with_delivery = replace(
        base,
        is_delivered_in_inchand=delivered,
        delivery_source=_detect_delivery_source(replace(base, is_delivered_in_inchand=delivered)),
    )
    return replace(with_delivery, safe_summary_fa=_build_safe_summary_fa(with_delivery))


def http_get_order_json(
    url: str,
    headers: Mapping[str, str],
    timeout: float,
) -> Mapping[str, Any]:
    """Perform GET request for order lookup (override in tests/CLI capture)."""
    return _default_get_json(url, headers, timeout)


def _default_get_json(url: str, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any]:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"data": None, "_http_status": 404}
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise InchandOrderLookupError(
            error_type="http_error",
            error_message=f"HTTP {exc.code}: {detail}",
        ) from exc
    except urllib.error.URLError as exc:
        if "timed out" in str(exc).lower():
            raise InchandOrderLookupError(
                error_type="timeout",
                error_message=str(exc),
            ) from exc
        raise InchandOrderLookupError(
            error_type="http_error",
            error_message=str(exc),
        ) from exc

    if not raw.strip():
        raise InchandOrderLookupError(
            error_type="parse_error",
            error_message="empty_response_body",
        )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise InchandOrderLookupError(
            error_type="parse_error",
            error_message="response_not_json_object",
        )
    return parsed


def lookup_inchand_order(
    order_id: str,
    *,
    settings: AppSettings | None = None,
    http_client: HttpGetJsonFn | None = None,
) -> InchandOrderLookupResult:
    """Look up an Inchand order by id (read-only; no side effects)."""
    cfg = settings or get_settings()
    selected_id, warning = resolve_inchand_order_id_from_text(order_id)
    normalized = selected_id or normalize_inchand_order_id(order_id)

    if not cfg.inchand_order_lookup_enabled:
        return InchandOrderLookupResult(
            order_id=normalized,
            found=False,
            error_type="disabled",
            error_message="inchand_order_lookup_disabled",
            safe_summary_fa="استعلام سفارش اینچند غیرفعال است.",
            code_validation_warning=warning,
        )

    if not resolve_inchand_api_token(cfg):
        return InchandOrderLookupResult(
            order_id=normalized,
            found=False,
            error_type="missing_token",
            error_message="INCHAND_API_KEY_VALUE or LIVE_ROOMS_API_TOKEN not configured",
            safe_summary_fa="توکن API اینچند تنظیم نشده است.",
            code_validation_warning=warning,
        )

    if not normalized or not looks_like_inchand_order_id(normalized):
        return InchandOrderLookupResult(
            order_id=normalized,
            found=False,
            error_type="invalid_order_id",
            error_message="invalid_inchand_order_id",
            safe_summary_fa="شناسه سفارش برای استعلام اینچند معتبر نیست.",
            code_validation_warning=warning,
        )

    url = build_order_lookup_url(normalized, cfg)
    headers = build_order_lookup_headers(cfg)
    get_fn = http_client or http_get_order_json
    timeout = float(cfg.inchand_order_lookup_timeout_seconds)

    try:
        response_json = get_fn(url, headers, timeout)
    except InchandOrderLookupError as exc:
        return InchandOrderLookupResult(
            order_id=normalized,
            found=False,
            error_type=exc.error_type,
            error_message=exc.error_message,
            safe_summary_fa=f"استعلام ناموفق: {exc.error_message[:120]}",
            code_validation_warning=warning,
        )

    if response_json.get("_http_status") == 404:
        return InchandOrderLookupResult(
            order_id=normalized,
            found=False,
            error_type="not_found",
            error_message="order_not_found",
            safe_summary_fa=f"سفارش {normalized} در اینچند یافت نشد.",
            code_validation_warning=warning,
        )

    return parse_inchand_order_response(response_json, normalized, code_validation_warning=warning)


def build_inchand_order_lookup_recommendation_metadata(
    order_ids: Sequence[str] | None = None,
    *,
    seller_text: str | None = None,
) -> dict[str, Any]:
    """Safe metadata for graph/UI (advisory only; no API call)."""
    candidates: list[str] = []
    for raw in order_ids or ():
        normalized = normalize_inchand_order_id(str(raw))
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    if seller_text:
        resolved, _ = resolve_inchand_order_id_from_text(seller_text)
        if resolved and resolved not in candidates:
            candidates.append(resolved)
        for oid in extract_order_ids(seller_text):
            normalized = normalize_inchand_order_id(oid)
            if normalized and normalized not in candidates:
                candidates.append(normalized)
    primary = candidates[-1] if candidates else None
    if not primary:
        return {
            "inchand_order_lookup_recommended": False,
            "inchand_order_id_candidate": None,
        }
    return {
        "inchand_order_lookup_recommended": True,
        "inchand_order_id_candidate": primary,
    }


def _path_has_data_private_segment(resolved: Path) -> bool:
    parts = resolved.parts
    for index, part in enumerate(parts[:-1]):
        if part == "data" and parts[index + 1] == "private":
            return True
    return False


def assert_private_order_raw_output_path(path: Path) -> Path:
    """Raw API archives must live under a data/private/ path segment."""
    resolved = path.expanduser().resolve()
    if not _path_has_data_private_segment(resolved):
        raise ValueError(f"raw output must be under data/private/, got {path}")
    return resolved


def assert_safe_order_lookup_payload(payload: Mapping[str, Any]) -> None:
    """Reject PII or prompt-like keys from persisted/session payloads."""
    forbidden = _PII_FORBIDDEN_KEYS | frozenset(
        {
            "raw_prompt",
            "transcript",
            "product_name",
        },
    )

    def _walk(value: object, key: str | None = None) -> None:
        if key and key in forbidden:
            raise ValueError(f"forbidden order lookup payload key: {key}")
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                _walk(child_value, str(child_key))
        elif isinstance(value, list):
            for item in value:
                _walk(item, key)

    _walk(payload)
