"""Build read-only HITL panel payloads from sanitized state or replay rows (no UI)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.hitl.hitl_visibility_contract import (
    AI_ASSIST_VISIBLE_FIELDS,
    ALLOWED_HITL_VISIBLE_FIELDS,
    FORBIDDEN_HITL_VISIBLE_FIELDS,
    OPEN_TICKET_SNAPSHOT_VISIBLE_FIELDS,
    RETRIEVAL_METADATA_VISIBLE_FIELDS,
    TICKET_METADATA_VISIBLE_FIELDS,
    TICKET_TEXT_PREVIEW_VISIBLE_FIELDS,
    assert_hitl_visible_payload_safe,
)
from app.hitl.ticket_text_preview import assert_ticket_text_preview_safe

_METADATA_FILTER_ALLOWLIST = frozenset({"ticket_label", "route_label"})


def _assert_source_has_no_forbidden_keys(source: Mapping[str, Any], *, label: str) -> None:
    keys = {str(key).lower() for key in source.keys()}
    forbidden = keys.intersection(FORBIDDEN_HITL_VISIBLE_FIELDS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"{label} contains forbidden keys: {joined}")


def _sanitize_retrieval_metadata_filter(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    sanitized: dict[str, str] = {}
    for key in _METADATA_FILTER_ALLOWLIST:
        raw = value.get(key)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            sanitized[key] = text
    return sanitized or None


def _coerce_retrieval_result_count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        msg = "retrieval_result_count must be an integer or null"
        raise ValueError(msg) from exc


def extract_hitl_retrieval_fields_from_source(source: Mapping[str, Any]) -> dict[str, Any]:
    """Extract HITL-allowlisted retrieval aggregate fields (no query hash or hit bodies)."""
    extracted: dict[str, Any] = {}
    for field in RETRIEVAL_METADATA_VISIBLE_FIELDS:
        if field == "retrieval_metadata_filter":
            if "retrieval_metadata_filter" in source:
                extracted[field] = _sanitize_retrieval_metadata_filter(
                    source["retrieval_metadata_filter"],
                )
            continue
        if field == "retrieval_result_count":
            if "retrieval_result_count" in source:
                extracted[field] = _coerce_retrieval_result_count(source["retrieval_result_count"])
            continue
        if field in source:
            extracted[field] = source[field]
    extracted["retrieval_activated"] = False
    return extracted


def _build_hitl_read_only_payload(source: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    """Extract allowlisted fields only; fail closed on forbidden source keys."""
    _assert_source_has_no_forbidden_keys(source, label=label)

    if source.get("retrieval_activated") is True:
        raise ValueError("retrieval_activated must be false for HITL read-only payloads")

    shadow_only = source.get("ai_assist_shadow_only")
    if shadow_only is False:
        raise ValueError("ai_assist_shadow_only must not be false for HITL read-only payloads")

    payload: dict[str, Any] = {}

    for field in TICKET_METADATA_VISIBLE_FIELDS:
        if field in source:
            payload[field] = source[field]

    for field in AI_ASSIST_VISIBLE_FIELDS:
        if field in source:
            payload[field] = source[field]

    for field in TICKET_TEXT_PREVIEW_VISIBLE_FIELDS:
        if field in source:
            preview = source[field]
            if preview is not None:
                if not isinstance(preview, str):
                    raise ValueError("ticket_text_preview must be a string")
                assert_ticket_text_preview_safe(preview.strip())
                payload[field] = preview.strip()

    open_fields: dict[str, str | None] = {}
    for field in OPEN_TICKET_SNAPSHOT_VISIBLE_FIELDS:
        if field in source:
            value = source[field]
            if value is not None:
                if not isinstance(value, str):
                    raise ValueError(f"{field} must be a string")
                open_fields[field] = value.strip()
    if open_fields:
        from app.live_feed.open_ticket_snapshot import assert_open_ticket_snapshot_safe

        assert_open_ticket_snapshot_safe(
            {
                "original_vendor_issue_preview": open_fields.get("original_vendor_issue_preview"),
                "latest_vendor_message": open_fields.get("latest_vendor_message"),
                "recent_context_preview": open_fields.get("recent_context_preview"),
                "open_ticket_preview": open_fields.get("open_ticket_preview"),
            },
        )
        payload.update(open_fields)

    for field in RETRIEVAL_METADATA_VISIBLE_FIELDS:
        if field == "retrieval_metadata_filter":
            if "retrieval_metadata_filter" in source:
                payload[field] = _sanitize_retrieval_metadata_filter(
                    source["retrieval_metadata_filter"],
                )
            continue
        if field == "retrieval_result_count":
            if "retrieval_result_count" in source:
                payload[field] = _coerce_retrieval_result_count(source["retrieval_result_count"])
            continue
        if field in source:
            payload[field] = source[field]

    if "retrieval_activated" not in payload:
        payload["retrieval_activated"] = False
    elif payload["retrieval_activated"] is not False:
        raise ValueError("retrieval_activated must be false for HITL read-only payloads")

    if "ai_assist_human_review_required" not in payload and any(
        key in source for key in AI_ASSIST_VISIBLE_FIELDS
    ):
        payload["ai_assist_human_review_required"] = True

    has_assist = any(key in source for key in AI_ASSIST_VISIBLE_FIELDS)
    if "ai_assist_shadow_only" not in payload and has_assist:
        payload["ai_assist_shadow_only"] = True

    extra = set(payload.keys()) - ALLOWED_HITL_VISIBLE_FIELDS
    if extra:
        joined = ", ".join(sorted(extra))
        raise ValueError(f"built HITL payload contains unsupported keys: {joined}")

    return payload


def build_hitl_read_only_payload_from_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build a HITL-visible payload from workflow state (allowlisted fields only)."""
    return _build_hitl_read_only_payload(state, label="workflow state")


def build_hitl_read_only_payload_from_replay_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Build a HITL-visible payload from a sanitized AI assist shadow replay row."""
    return _build_hitl_read_only_payload(row, label="replay row")


def assert_hitl_payload_ready(payload: dict[str, Any]) -> None:
    """Validate payload against Step 150 read-only HITL visibility contract."""
    assert_hitl_visible_payload_safe(payload)
    if payload.get("retrieval_activated") is True:
        raise ValueError("retrieval_activated must be false for HITL read-only payloads")
    if payload.get("ai_assist_shadow_only") is False:
        raise ValueError("ai_assist_shadow_only must be true for HITL read-only payloads")
    if payload.get("ai_assist_human_review_required") is False:
        raise ValueError("ai_assist_human_review_required must be true for HITL read-only payloads")
