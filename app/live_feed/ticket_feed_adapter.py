"""Read-only live vendor ticket feed adapter (JSONL polling; no production writes)."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.corpus_planning.ai_assist_shadow_replay_export import (
    configure_mock_workflow_runtime,
    export_ai_assist_shadow_replay_row_for_snapshot,
)
from app.corpus_planning.shadow_replay_jsonl_export import (
    ShadowReplayExportConfig,
    export_shadow_replay_row_for_snapshot,
)
from app.hitl.hitl_payload_builder import (
    assert_hitl_payload_ready,
    build_hitl_read_only_payload_from_replay_row,
)
from app.hitl.hitl_visibility_contract import RETRIEVAL_METADATA_VISIBLE_FIELDS
from app.hitl.ticket_text_preview import attach_ticket_text_preview_to_row
from app.live_feed.open_ticket_snapshot import attach_open_ticket_snapshot_to_row
from app.live_feed.ticket_models import LiveFeedCheckpoint, LiveVendorTicket
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)
from app.tickets.workflow_mapping import conversation_snapshot_to_workflow_input

_DEFAULT_EXPORT_CONFIG = ShadowReplayExportConfig(
    namespace="vendor_ticket_real_pilot_balanced",
    index_version="pilot_balanced_v1",
    profile="semantic_pgvector",
    top_k=5,
    confirm_sandbox=True,
)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _snapshot_updated_at(snapshot: ConversationTicketSnapshot) -> datetime | None:
    if snapshot.closed_at:
        return _parse_timestamp(snapshot.closed_at)
    if snapshot.created_at:
        return _parse_timestamp(snapshot.created_at)
    latest: datetime | None = None
    for message in snapshot.messages:
        ts = _parse_timestamp(message.timestamp)
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def normalize_live_ticket(
    raw: Mapping[str, Any] | ConversationTicketSnapshot | str,
) -> LiveVendorTicket:
    """Normalize export JSON into a live ticket (user_input kept internal-only)."""
    if isinstance(raw, str):
        snapshot = parse_conversation_ticket_snapshot(raw)
        raw_payload = json.loads(raw)
    elif isinstance(raw, ConversationTicketSnapshot):
        snapshot = raw
        raw_payload = None
    else:
        snapshot = parse_conversation_ticket_snapshot(json.dumps(raw, ensure_ascii=False))
        raw_payload = dict(raw)

    workflow = conversation_snapshot_to_workflow_input(snapshot)
    user_input = str(workflow.get("user_input") or "")
    if not user_input.strip():
        raise ValueError(f"live ticket {snapshot.room_id}: user_input is required for routing")

    created_at = _parse_timestamp(snapshot.created_at)
    updated_at = _snapshot_updated_at(snapshot) or created_at or _utc_now()

    return LiveVendorTicket(
        room_id=snapshot.room_id,
        created_at=created_at,
        updated_at=updated_at,
        ticket_label=snapshot.ticket_label,
        user_input=user_input,
        assigned_department=None,
        review_priority=None,
        raw_payload=raw_payload,
        snapshot=snapshot,
    )


def _load_tickets_from_path(path: Path) -> list[LiveVendorTicket]:
    if not path.is_file():
        return []
    tickets: list[LiveVendorTicket] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        tickets.append(normalize_live_ticket(raw_line))
    tickets.sort(key=lambda ticket: ticket.sort_key(), reverse=True)
    return tickets


def fetch_recent_vendor_tickets(
    source_path: Path | str,
    *,
    limit: int = 50,
) -> list[LiveVendorTicket]:
    """Return the most recently updated tickets from the live feed source file."""
    tickets = _load_tickets_from_path(Path(source_path))
    return tickets[:limit]


def fetch_new_vendor_tickets_since(
    source_path: Path | str,
    checkpoint: LiveFeedCheckpoint,
    *,
    max_batch: int,
) -> list[LiveVendorTicket]:
    """Return tickets not yet seen or newer than checkpoint last_seen_updated_at."""
    tickets = _load_tickets_from_path(Path(source_path))
    seen = set(checkpoint.seen_room_ids)
    last_seen_dt = _parse_timestamp(checkpoint.last_seen_updated_at)
    new_tickets: list[LiveVendorTicket] = []
    for ticket in tickets:
        if ticket.room_id in seen:
            if last_seen_dt is None or ticket.updated_at is None:
                continue
            if ticket.updated_at <= last_seen_dt:
                continue
        new_tickets.append(ticket)
        if len(new_tickets) >= max_batch:
            break
    return new_tickets


def _merge_retrieval_fields(
    assist_row: Mapping[str, Any],
    retrieval_row: Mapping[str, Any],
) -> dict[str, Any]:
    merged = dict(assist_row)
    for field in RETRIEVAL_METADATA_VISIBLE_FIELDS:
        if field in retrieval_row:
            merged[field] = retrieval_row[field]
    return merged


def build_operator_payload_from_live_ticket(
    ticket: LiveVendorTicket,
    *,
    export_config: ShadowReplayExportConfig | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Run routing + shadow retrieval + AI assist; return HITL-safe operator payload."""
    if ticket.snapshot is None:
        raise ValueError(f"live ticket {ticket.room_id}: snapshot is required for processing")

    settings = settings or get_settings()
    export_config = export_config or _DEFAULT_EXPORT_CONFIG
    configure_mock_workflow_runtime()

    snapshot = ticket.snapshot
    retrieval_row = export_shadow_replay_row_for_snapshot(
        snapshot,
        export_config,
        settings=settings,
    )
    assist_row = export_ai_assist_shadow_replay_row_for_snapshot(
        snapshot,
        export_config,
        settings=settings,
    )
    merged = _merge_retrieval_fields(assist_row, retrieval_row)
    merged = attach_ticket_text_preview_to_row(merged, snapshot=snapshot)
    merged = attach_open_ticket_snapshot_to_row(merged, snapshot=snapshot)
    payload = build_hitl_read_only_payload_from_replay_row(merged)
    assert_hitl_payload_ready(payload)
    return payload


def build_operator_payloads_from_live_tickets(
    tickets: Iterable[LiveVendorTicket],
    *,
    export_config: ShadowReplayExportConfig | None = None,
    settings: AppSettings | None = None,
) -> list[dict[str, Any]]:
    """Process multiple live tickets into HITL-safe operator payloads."""
    return [
        build_operator_payload_from_live_ticket(
            ticket,
            export_config=export_config,
            settings=settings,
        )
        for ticket in tickets
    ]


def advance_checkpoint(
    checkpoint: LiveFeedCheckpoint,
    tickets: Sequence[LiveVendorTicket],
) -> LiveFeedCheckpoint:
    """Update checkpoint after successfully processing tickets."""
    seen = list(checkpoint.seen_room_ids)
    seen_set = set(seen)
    last_seen_dt = _parse_timestamp(checkpoint.last_seen_updated_at)
    for ticket in tickets:
        if ticket.room_id not in seen_set:
            seen.append(ticket.room_id)
            seen_set.add(ticket.room_id)
        if ticket.updated_at and (last_seen_dt is None or ticket.updated_at > last_seen_dt):
            last_seen_dt = ticket.updated_at
    return LiveFeedCheckpoint(
        last_seen_updated_at=last_seen_dt.isoformat()
        if last_seen_dt
        else checkpoint.last_seen_updated_at,
        seen_room_ids=seen,
        last_poll_at=_utc_now().isoformat(),
    )
