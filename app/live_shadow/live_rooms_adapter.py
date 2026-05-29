"""Normalize Inchand internal rooms API payloads to live feed contract rows (no redaction)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.live_shadow.live_feed_contract import normalize_sender_type

logger = logging.getLogger(__name__)

SOURCE_SYSTEM = "inchand_internal_rooms_api"
_DEFAULT_STATUS = "open"

_SHOP_ID_FIELDS: tuple[tuple[str, ...], ...] = (
    ("shop_id",),
    ("shopId",),
    ("store_id",),
    ("storeId",),
    ("shop", "id"),
    ("store", "id"),
    ("vendor", "shop_id"),
    ("vendor", "shopId"),
    ("seller", "shop_id"),
    ("seller", "shopId"),
)
_SELLER_ID_FIELDS: tuple[tuple[str, ...], ...] = (
    ("seller_id",),
    ("sellerId",),
    ("vendor_id",),
    ("vendorId",),
    ("provider_id",),
    ("providerId",),
    ("seller", "id"),
    ("vendor", "id"),
    ("provider", "id"),
)
_SHOP_NAME_FIELDS: tuple[tuple[str, ...], ...] = (
    ("shop_name",),
    ("shopName",),
    ("store_name",),
    ("storeName",),
    ("shop", "name"),
    ("store", "name"),
    ("vendor", "shop_name"),
    ("vendor", "shopName"),
    ("seller", "shop_name"),
)


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _parse_iso_timestamp(value: Any, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            logger.warning("invalid ISO timestamp for %s: %r", field_name, value)
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def normalize_inbound_sender_type(value: Any) -> str:
    """Map API sender types to contract sender_type; unknown values become unknown."""
    if value is None:
        return "unknown"
    raw = str(value).strip()
    if not raw:
        return "unknown"
    try:
        return normalize_sender_type(raw)
    except ValueError:
        return "unknown"


def _resolve_timestamp(
    value: Any,
    *,
    field_name: str,
    fallback_iso: str,
    used_fallbacks: list[str],
) -> str:
    parsed = _parse_iso_timestamp(value, field_name=field_name)
    if parsed is not None:
        return parsed.isoformat()
    used_fallbacks.append(field_name)
    return fallback_iso


def _nested_get(mapping: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = mapping
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value.get(key)
    return value


def _resolve_identity_field(
    row: Mapping[str, Any],
    candidates: tuple[tuple[str, ...], ...],
) -> tuple[str | None, str | None]:
    for path in candidates:
        value = _nested_get(row, path)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text, ".".join(path)
    return None, None


def extract_shop_identity_from_room(raw_room: Mapping[str, Any]) -> dict[str, Any]:
    """Extract safe shop/seller identity presence metadata from raw room payload."""
    shop_id, shop_src = _resolve_identity_field(raw_room, _SHOP_ID_FIELDS)
    seller_id, seller_src = _resolve_identity_field(raw_room, _SELLER_ID_FIELDS)
    shop_name, shop_name_src = _resolve_identity_field(raw_room, _SHOP_NAME_FIELDS)
    return {
        "shop_id": shop_id,
        "shop_id_present": bool(shop_id),
        "shop_id_source": shop_src,
        "seller_id": seller_id,
        "seller_id_present": bool(seller_id),
        "seller_id_source": seller_src,
        "shop_name": shop_name,
        "shop_name_present": bool(shop_name),
        "shop_name_source": shop_name_src,
        "shop_identity_available": bool(shop_id or seller_id or shop_name),
    }


def normalize_room_to_live_ticket(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map one Inchand rooms API row to live_feed_adapter_v1 JSONL shape (raw text preserved)."""
    warnings: list[str] = []
    timestamp_fallback_fields: list[str] = []
    fallback_now = _utc_now_iso()

    room_id_raw = row.get("id", row.get("room_id"))
    room_id = str(room_id_raw).strip() if room_id_raw is not None else ""
    if not room_id:
        raise ValueError("room row requires id or room_id")

    category = row.get("category", row.get("ticket_label"))
    ticket_label = str(category).strip() if category is not None else "unknown"
    if not ticket_label:
        ticket_label = "unknown"

    identity = extract_shop_identity_from_room(row)

    status_raw = row.get("status")
    status_fallback_used = False
    if status_raw is None or not str(status_raw).strip():
        status = _DEFAULT_STATUS
        status_fallback_used = True
    else:
        status = str(status_raw).strip().lower()

    created_at = _resolve_timestamp(
        row.get("created_at"),
        field_name="created_at",
        fallback_iso=fallback_now,
        used_fallbacks=timestamp_fallback_fields,
    )
    updated_at = _resolve_timestamp(
        row.get("updated_at"),
        field_name="updated_at",
        fallback_iso=created_at,
        used_fallbacks=timestamp_fallback_fields,
    )

    raw_messages = row.get("messages")
    if not isinstance(raw_messages, list):
        raw_messages = []

    normalized_messages: list[dict[str, Any]] = []
    for index, message in enumerate(raw_messages, start=1):
        if not isinstance(message, dict):
            warnings.append(f"messages[{index - 1}]_not_object")
            continue
        content = message.get("content", message.get("text"))
        if content is None:
            warnings.append(f"messages[{index - 1}]_missing_content")
            continue
        text = str(content)
        if not text.strip():
            warnings.append(f"messages[{index - 1}]_empty_content_skipped")
            continue

        sender_type = normalize_inbound_sender_type(message.get("type", message.get("sender_type")))
        message_time = _resolve_timestamp(
            message.get("created_at", message.get("timestamp")),
            field_name=f"messages[{index - 1}].created_at",
            fallback_iso=created_at,
            used_fallbacks=timestamp_fallback_fields,
        )
        message_id_raw = message.get("message_id") or message.get("id")
        message_id = (
            str(message_id_raw).strip()
            if message_id_raw is not None and str(message_id_raw).strip()
            else f"{room_id}-{index}"
        )
        normalized_messages.append(
            {
                "message_id": message_id,
                "sender_type": sender_type,
                "text": text,
                "created_at": message_time,
            },
        )

    if not normalized_messages:
        raise ValueError(f"room {room_id}: no non-empty messages after normalization")

    if normalized_messages:
        last_message_time = normalized_messages[-1]["created_at"]
        if _parse_iso_timestamp(row.get("updated_at"), field_name="updated_at") is None:
            updated_at = str(last_message_time)

    ticket: dict[str, Any] = {
        "room_id": room_id,
        "ticket_label": ticket_label,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "source_system": SOURCE_SYSTEM,
        "messages": normalized_messages,
        "metadata": {
            "source_system": SOURCE_SYSTEM,
            "status": status,
            "shop_identity_available": bool(identity["shop_identity_available"]),
            "shop_id_present": bool(identity["shop_id_present"]),
            "seller_id_present": bool(identity["seller_id_present"]),
            "shop_name_present": bool(identity["shop_name_present"]),
        },
    }
    if identity["shop_id"]:
        ticket["shop_id"] = identity["shop_id"]
        ticket["metadata"]["shop_id"] = identity["shop_id"]
    if identity["seller_id"]:
        ticket["seller_id"] = identity["seller_id"]
        ticket["metadata"]["seller_id"] = identity["seller_id"]
    if identity["shop_name"]:
        ticket["shop_name"] = identity["shop_name"]
        ticket["metadata"]["shop_name"] = identity["shop_name"]
    ticket["shop_identity_available"] = bool(identity["shop_identity_available"])
    ticket["shop_id_present"] = bool(identity["shop_id_present"])
    ticket["seller_id_present"] = bool(identity["seller_id_present"])
    ticket["shop_name_present"] = bool(identity["shop_name_present"])
    if identity["shop_id_source"]:
        ticket["shop_id_source"] = identity["shop_id_source"]
        ticket["metadata"]["shop_id_source"] = identity["shop_id_source"]
    if identity["seller_id_source"]:
        ticket["seller_id_source"] = identity["seller_id_source"]
        ticket["metadata"]["seller_id_source"] = identity["seller_id_source"]
    if identity["shop_name_source"]:
        ticket["shop_name_source"] = identity["shop_name_source"]
        ticket["metadata"]["shop_name_source"] = identity["shop_name_source"]
    if status_fallback_used:
        ticket["status_fallback_used"] = True
    if timestamp_fallback_fields:
        ticket["timestamp_fallback_used"] = True
        ticket["timestamp_fallback_reason"] = "missing_from_api"
    if warnings:
        ticket["normalization_warnings"] = warnings

    return ticket


def normalize_rooms_to_live_tickets(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Normalize many API room rows; return (tickets, row_level_errors)."""
    tickets: list[dict[str, Any]] = []
    errors: list[str] = []
    for row in rows:
        room_key = str(row.get("id") or row.get("room_id") or "?")
        try:
            tickets.append(normalize_room_to_live_ticket(row))
        except ValueError as exc:
            errors.append(f"room_{room_key}:{exc}")
    return tickets, errors


def _is_under_data_private(path: Path) -> bool:
    resolved = path.resolve()
    for parent in (resolved, *resolved.parents):
        if parent.name == "private" and parent.parent.name == "data":
            return True
    return False


def assert_private_output_path(path: Path, *, allow_non_private: bool = False) -> Path:
    """Ensure output stays under data/private/ unless explicitly overridden."""
    resolved = path.resolve()
    if allow_non_private:
        return resolved
    if not _is_under_data_private(resolved):
        raise ValueError(
            f"output path must be under data/private/: {resolved} "
            "(use --allow-non-private-output to override)",
        )
    return resolved


def write_json_file(
    payload: Any,
    output_path: Path,
    *,
    overwrite: bool = False,
    allow_non_private: bool = False,
) -> Path:
    """Write JSON payload to path (private guard applied)."""
    target = assert_private_output_path(output_path, allow_non_private=allow_non_private)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(f"output exists: {target} (use --overwrite)")
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def write_normalized_live_tickets_jsonl(
    rows: Sequence[Mapping[str, Any]],
    output_path: Path,
    *,
    overwrite: bool = False,
    allow_non_private: bool = False,
) -> Path:
    """Write one normalized live ticket JSON object per line (UTF-8)."""
    target = assert_private_output_path(output_path, allow_non_private=allow_non_private)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise FileExistsError(f"output exists: {target} (use --overwrite)")

    lines: list[str] = []
    for row in rows:
        lines.append(json.dumps(dict(row), ensure_ascii=False, separators=(",", ":")))

    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target
