"""Backfill Step 170 intent fields on HITL/replay rows when export predates taxonomy v1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.workflows.vendor_ticket_ai_assist_shadow import evaluate_vendor_ticket_ai_assist_shadow

_INTENT_BACKFILL_KEYS = (
    "detected_intent",
    "intent_confidence_band",
    "intent_reasons_summary",
    "intent_related_document_types",
    "extracted_order_id",
    "extracted_order_ids",
    "extracted_tracking_code",
    "extracted_product_ids",
    "extracted_tracking_carrier",
    "extracted_iban",
    "extracted_iban_masked",
    "entity_warnings_summary",
)

_SELLER_BACKFILL_KEYS = (
    "seller_notification_detected",
    "seller_intent_type",
    "seller_notification_type",
    "seller_operational_request_type",
    "seller_notification_shipment_status",
)

_PREVIEW_KEYS = (
    "latest_vendor_message",
    "original_vendor_issue_preview",
    "ticket_text_preview",
)


def _preview_text_available(row: Mapping[str, Any]) -> bool:
    for key in _PREVIEW_KEYS:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _needs_intent_backfill(row: Mapping[str, Any]) -> bool:
    if row.get("detected_intent"):
        return False
    if not row.get("ai_assist_shadow_generated"):
        return False
    return _preview_text_available(row)


def _build_assist_payload_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
    }
    for key in (
        "ticket_label",
        "route_label",
        "review_priority",
        "retrieval_gate_decision",
        "retrieval_result_count",
        "latest_vendor_message",
        "original_vendor_issue_preview",
    ):
        if key in row and row[key] is not None:
            payload[key] = row[key]
    if not payload.get("latest_vendor_message"):
        preview = row.get("ticket_text_preview")
        if isinstance(preview, str) and preview.strip():
            payload["latest_vendor_message"] = preview.strip()
    return payload


def enrich_ai_assist_row_intent_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Fill missing intent/entity fields using shadow assist evaluator (preview text only)."""
    merged = dict(row)
    if not _needs_intent_backfill(merged):
        return merged
    try:
        result = evaluate_vendor_ticket_ai_assist_shadow(_build_assist_payload_from_row(merged))
    except ValueError:
        return merged
    if merged.get("ai_assist_suggested_action") is None:
        merged["ai_assist_suggested_action"] = result.suggested_action.value
    if merged.get("ai_assist_suggested_action_reason") is None:
        merged["ai_assist_suggested_action_reason"] = result.suggested_action_reason
    for key in _INTENT_BACKFILL_KEYS:
        if merged.get(key) is None:
            value = getattr(result, key, None)
            if value is not None:
                merged[key] = value
    for key in _SELLER_BACKFILL_KEYS:
        if merged.get(key) is None:
            value = getattr(result, key, None)
            if value is not None:
                merged[key] = value
    return merged
