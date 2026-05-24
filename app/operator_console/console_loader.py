"""Load sanitized AI assist replay JSONL into HITL-safe operator ticket views."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.corpus_planning.ai_assist_shadow_replay_row_contract import (
    assert_ai_assist_shadow_replay_row_safe,
)
from app.corpus_planning.shadow_replay_row_contract import assert_shadow_replay_row_safe
from app.hitl.hitl_payload_builder import (
    assert_hitl_payload_ready,
    build_hitl_read_only_payload_from_replay_row,
    extract_hitl_retrieval_fields_from_source,
)
from app.hitl.hitl_visibility_contract import RETRIEVAL_METADATA_VISIBLE_FIELDS
from app.hitl.ticket_text_preview import build_ticket_text_preview_from_snapshot
from app.live_feed.open_ticket_snapshot import (
    build_open_ticket_snapshot,
    extract_full_first_vendor_message,
    open_ticket_snapshot_to_payload,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.intent_enrichment import enrich_ai_assist_row_intent_fields
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)

DEFAULT_REPLAY_PATH = Path("reports/ai_assist_shadow_replay_v1.jsonl")
DEFAULT_SHADOW_REPLAY_PATH = Path("reports/shadow_replay_balanced_v1.jsonl")
DEFAULT_REDACTED_TICKETS_PATH = Path("data/private/vendor_tickets_400.redacted.jsonl")

OPERATOR_CONSOLE_DISPLAY_LIMIT_LABELS: tuple[str, ...] = ("25", "50", "100", "All")
DEFAULT_OPERATOR_CONSOLE_DISPLAY_LIMIT_LABEL = "All"


def parse_operator_console_display_limit(label: str) -> int | None:
    """Parse sidebar display limit; ``All`` means no cap (``None``)."""
    normalized = label.strip()
    if normalized.lower() == "all":
        return None
    try:
        value = int(normalized)
    except ValueError as exc:
        msg = f"invalid display limit label: {label!r}"
        raise ValueError(msg) from exc
    if value < 1:
        raise ValueError("display limit must be at least 1")
    return value


def apply_operator_console_display_limit(
    tickets: Sequence[OperatorTicket],
    *,
    limit: int | None,
) -> list[OperatorTicket]:
    """Apply UI display cap after filters; does not change loader behavior."""
    if limit is None:
        return list(tickets)
    return list(tickets[:limit])


def load_replay_rows(path: Path | str) -> list[dict[str, Any]]:
    """Load JSONL replay rows; reject rows that fail replay safety checks."""
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        if not isinstance(row, dict):
            msg = f"line {line_number}: row must be a JSON object"
            raise ValueError(msg)
        assert_ai_assist_shadow_replay_row_safe(row)
        rows.append(row)
    return rows


def load_retrieval_aggregate_index(path: Path | str) -> dict[str, dict[str, Any]]:
    """Index HITL-safe retrieval fields from shadow replay JSONL by room_id."""
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    index: dict[str, dict[str, Any]] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        if not isinstance(row, dict):
            continue
        try:
            assert_shadow_replay_row_safe(row)
        except ValueError:
            continue
        room_id = row.get("room_id")
        if not isinstance(room_id, str) or not room_id.strip():
            continue
        retrieval = extract_hitl_retrieval_fields_from_source(row)
        if retrieval.get("retrieval_gate_decision") is not None:
            index[room_id] = {
                key: retrieval[key] for key in RETRIEVAL_METADATA_VISIBLE_FIELDS if key in retrieval
            }
    return index


def load_ticket_text_preview_index(path: Path | str) -> dict[str, str]:
    """Build safe ticket_text_preview values from redacted ticket export JSONL."""
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    index: dict[str, str] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except (ValueError, json.JSONDecodeError):
            continue
        try:
            preview = build_ticket_text_preview_from_snapshot(snapshot)
        except ValueError:
            continue
        if preview:
            index[snapshot.room_id] = preview
    return index


def load_full_first_vendor_message_index(path: Path | str) -> dict[str, str]:
    """Map room_id → full redacted first vendor message (internal extraction input only)."""
    return {
        room_id: full
        for room_id, snapshot in load_conversation_snapshot_index(path).items()
        if (full := extract_full_first_vendor_message(snapshot))
    }


def attach_full_first_vendor_messages(
    tickets: list[OperatorTicket],
    *,
    full_message_index: Mapping[str, str],
) -> list[OperatorTicket]:
    """Attach internal full first-turn text from redacted export (never shown in UI)."""
    if not full_message_index:
        return tickets
    enriched: list[OperatorTicket] = []
    for ticket in tickets:
        full = full_message_index.get(ticket.room_id)
        if full:
            enriched.append(replace(ticket, full_first_vendor_message_text=full))
        else:
            enriched.append(ticket)
    return enriched


def load_conversation_snapshot_index(
    path: Path | str,
) -> dict[str, ConversationTicketSnapshot]:
    """Load full redacted conversation snapshots by room_id (operator console only)."""
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    index: dict[str, ConversationTicketSnapshot] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except (ValueError, json.JSONDecodeError):
            continue
        index[snapshot.room_id] = snapshot
    return index


def load_open_ticket_snapshot_index(path: Path | str) -> dict[str, dict[str, str | None]]:
    """Build open ticket snapshot fields from redacted ticket export JSONL."""
    file_path = Path(path)
    if not file_path.is_file():
        return {}
    index: dict[str, dict[str, str | None]] = {}
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except (ValueError, json.JSONDecodeError):
            continue
        try:
            built = build_open_ticket_snapshot(snapshot)
        except ValueError:
            continue
        if any(
            (
                built.original_vendor_issue_preview,
                built.latest_vendor_message,
                built.recent_context_preview,
                built.open_ticket_preview,
            ),
        ):
            index[snapshot.room_id] = open_ticket_snapshot_to_payload(built)
    return index


def enrich_ai_assist_replay_row(
    row: Mapping[str, Any],
    retrieval_index: Mapping[str, Mapping[str, Any]],
    *,
    preview_index: Mapping[str, str] | None = None,
    open_snapshot_index: Mapping[str, Mapping[str, str | None]] | None = None,
) -> dict[str, Any]:
    """Merge retrieval aggregate fields and preview when missing from replay rows."""
    merged = dict(row)
    room_id = row.get("room_id")
    if row.get("retrieval_gate_decision") is None and isinstance(room_id, str):
        extra = retrieval_index.get(room_id)
        if extra:
            merged.update(extra)
            merged["retrieval_activated"] = False
    previews = preview_index or {}
    if merged.get("ticket_text_preview") is None and isinstance(room_id, str):
        preview = previews.get(room_id)
        if preview:
            merged["ticket_text_preview"] = preview
    snapshots = open_snapshot_index or {}
    if merged.get("open_ticket_preview") is None and isinstance(room_id, str):
        snap_fields = snapshots.get(room_id)
        if snap_fields:
            merged.update(snap_fields)
    return enrich_ai_assist_row_intent_fields(merged)


def build_operator_tickets_from_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    retrieval_index: Mapping[str, Mapping[str, Any]] | None = None,
    preview_index: Mapping[str, str] | None = None,
    open_snapshot_index: Mapping[str, Mapping[str, str | None]] | None = None,
) -> list[OperatorTicket]:
    """Build operator tickets via HITL read-only payload builder (fail closed)."""
    tickets: list[OperatorTicket] = []
    retrieval = retrieval_index or {}
    previews = preview_index or {}
    snapshots = open_snapshot_index or {}
    for index_pos, row in enumerate(rows):
        try:
            enriched = enrich_ai_assist_replay_row(
                row,
                retrieval,
                preview_index=previews,
                open_snapshot_index=snapshots,
            )
            payload = build_hitl_read_only_payload_from_replay_row(enriched)
            assert_hitl_payload_ready(payload)
            tickets.append(OperatorTicket.from_hitl_payload(payload))
        except ValueError as exc:
            room_id = row.get("room_id", f"row_{index_pos}")
            msg = f"row {index_pos} ({room_id}): {exc}"
            raise ValueError(msg) from exc
    return tickets


def load_operator_tickets(
    path: Path | str = DEFAULT_REPLAY_PATH,
    *,
    shadow_replay_path: Path | str | None = DEFAULT_SHADOW_REPLAY_PATH,
    redacted_tickets_path: Path | str | None = DEFAULT_REDACTED_TICKETS_PATH,
) -> list[OperatorTicket]:
    """Load replay JSONL and return HITL-safe operator tickets."""
    rows = load_replay_rows(path)
    retrieval_index = (
        load_retrieval_aggregate_index(shadow_replay_path) if shadow_replay_path is not None else {}
    )
    preview_index = (
        load_ticket_text_preview_index(redacted_tickets_path)
        if redacted_tickets_path is not None
        else {}
    )
    open_snapshot_index = (
        load_open_ticket_snapshot_index(redacted_tickets_path)
        if redacted_tickets_path is not None
        else {}
    )
    full_message_index = (
        load_full_first_vendor_message_index(redacted_tickets_path)
        if redacted_tickets_path is not None
        else {}
    )
    tickets = build_operator_tickets_from_rows(
        rows,
        retrieval_index=retrieval_index,
        preview_index=preview_index,
        open_snapshot_index=open_snapshot_index,
    )
    return attach_full_first_vendor_messages(tickets, full_message_index=full_message_index)


def filter_operator_tickets(
    tickets: Sequence[OperatorTicket],
    *,
    ticket_label: str | None = None,
    suggested_action: str | None = None,
    escalation_only: bool = False,
    duplicate_only: bool = False,
) -> list[OperatorTicket]:
    """Apply sidebar filters to the ticket list."""
    filtered = list(tickets)
    if ticket_label:
        filtered = [ticket for ticket in filtered if ticket.ticket_label == ticket_label]
    if suggested_action:
        filtered = [ticket for ticket in filtered if ticket.suggested_action == suggested_action]
    if escalation_only:
        filtered = [ticket for ticket in filtered if ticket.escalation_recommended is True]
    if duplicate_only:
        filtered = [ticket for ticket in filtered if ticket.duplicate_possible is True]
    return filtered


def distinct_ticket_labels(tickets: Sequence[OperatorTicket]) -> list[str]:
    labels = {ticket.ticket_label for ticket in tickets if ticket.ticket_label}
    return sorted(labels)


def distinct_suggested_actions(tickets: Sequence[OperatorTicket]) -> list[str]:
    actions = {ticket.suggested_action for ticket in tickets if ticket.suggested_action}
    return sorted(actions)


def operator_tickets_from_hitl_payloads(
    payloads: Iterable[Mapping[str, Any]],
) -> list[OperatorTicket]:
    """Build operator tickets from HITL-safe payloads (live feed or replay)."""
    tickets: list[OperatorTicket] = []
    for index, payload in enumerate(payloads):
        ready = enrich_ai_assist_row_intent_fields(payload)
        assert_hitl_payload_ready(ready)
        try:
            tickets.append(OperatorTicket.from_hitl_payload(ready))
        except ValueError as exc:
            room_id = ready.get("room_id", f"payload_{index}")
            msg = f"payload {index} ({room_id}): {exc}"
            raise ValueError(msg) from exc
    return tickets
