"""Load and classify live API feed JSONL for operator dashboard intake (read-only)."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.live_feed.ticket_feed_adapter import normalize_live_ticket
from app.live_feed.ticket_models import LiveVendorTicket
from app.live_shadow.live_first_turn_shadow_intake import classify_shadow_eligibility
from app.operator_console.first_vendor_filter import first_meaningful_sender_type
from app.workflows.multi_turn_ticket_context import (
    build_multi_turn_context,
    latest_meaningful_sender,
)

CONSOLE_DATA_SOURCE_SESSION_KEY = "operator_console_data_source"
SOURCE_HISTORICAL_REPLAY = "historical_replay"
SOURCE_LIVE_API_FEED = "live_api_feed"

LIVE_API_FEED_ENTRIES_SESSION_KEY = "live_api_feed_entries"
LIVE_API_FEED_LAST_REFRESH_SESSION_KEY = "live_api_feed_last_refresh_utc"
LIVE_API_FEED_PATH_SESSION_KEY = "live_api_feed_source_path"
LIVE_API_FEED_TICKET_LABEL_FILTER_KEY = "live_api_feed_ticket_label_filter"
LIVE_API_FEED_ELIGIBILITY_FILTER_KEY = "live_api_feed_eligibility_filter"
LIVE_API_FEED_FIRST_SENDER_FILTER_KEY = "live_api_feed_first_sender_filter"
LIVE_API_FEED_LATEST_SENDER_FILTER_KEY = "live_api_feed_latest_sender_filter"
LIVE_API_FEED_LAST_FETCH_RESULT_SESSION_KEY = "live_api_feed_last_fetch_result"
LIVE_API_FEED_LAST_FETCH_TIME_SESSION_KEY = "live_api_feed_last_fetch_time"
LIVE_API_FEED_LAST_FETCH_ERROR_SESSION_KEY = "live_api_feed_last_fetch_error"

DEFAULT_LIVE_API_FEED_PATH = Path("data/private/live_vendor_tickets.jsonl")
DEFAULT_LIVE_ROOMS_FETCH_LIMIT = 400

ELIGIBILITY_FILTER_ELIGIBLE = "eligible"
ELIGIBILITY_FILTER_OPTIONS: tuple[str, ...] = (
    ELIGIBILITY_FILTER_ELIGIBLE,
    "support_replied",
    "support_started",
    "closed_ticket",
    "empty_first_turn",
    "malformed_ticket",
)

FIRST_SENDER_FILTER_OPTIONS: tuple[str, ...] = (
    "seller",
    "support_agent",
    "finance_agent",
    "system",
    "unknown",
)

LATEST_SENDER_FILTER_OPTIONS: tuple[str, ...] = FIRST_SENDER_FILTER_OPTIONS

_DASHBOARD_SKIP_REASONS = frozenset(
    {
        "support_replied",
        "support_started",
        "closed_ticket",
        "empty_first_turn",
        "malformed_ticket",
    },
)

_SHADOW_TO_DASHBOARD_SKIP: dict[str, str] = {
    "multi_turn": "support_replied",
    "support_started": "support_started",
    "closed_ticket": "closed_ticket",
    "not_open_status": "closed_ticket",
    "missing_first_turn": "empty_first_turn",
    "internal_started": "malformed_ticket",
    "missing_snapshot": "malformed_ticket",
    "not_first_vendor": "empty_first_turn",
    "already_processed": "empty_first_turn",
}


def _parse_iso_timestamp(value: Any) -> datetime | None:
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
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _adapt_live_feed_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map live_feed_adapter_v1 rows to conversation snapshot parser shape."""
    adapted: dict[str, Any] = dict(row)
    metadata = dict(adapted.get("metadata") or {})
    if adapted.get("updated_at") is not None:
        metadata["updated_at"] = adapted["updated_at"]
    if adapted.get("source_system") is not None:
        metadata["source_system"] = adapted["source_system"]
    if adapted.get("shop_id") is not None:
        metadata["shop_id"] = adapted["shop_id"]
    if adapted.get("seller_id") is not None:
        metadata["seller_id"] = adapted["seller_id"]
    if adapted.get("shop_name") is not None:
        metadata["shop_name"] = adapted["shop_name"]
    for key in (
        "shop_identity_available",
        "shop_id_present",
        "seller_id_present",
        "shop_name_present",
        "shop_id_source",
        "seller_id_source",
        "shop_name_source",
    ):
        if adapted.get(key) is not None:
            metadata[key] = adapted[key]
    if metadata:
        adapted["metadata"] = metadata

    messages_out: list[dict[str, Any]] = []
    for message in adapted.get("messages") or []:
        if not isinstance(message, dict):
            continue
        msg = dict(message)
        if msg.get("timestamp") is None and msg.get("created_at") is not None:
            msg["timestamp"] = msg["created_at"]
        messages_out.append(msg)
    adapted["messages"] = messages_out

    label = adapted.get("ticket_label")
    if label is None or not str(label).strip():
        adapted["ticket_label"] = "unknown"
    return adapted


def _ticket_sort_key(ticket: LiveVendorTicket) -> datetime:
    payload = ticket.raw_payload if isinstance(ticket.raw_payload, dict) else {}
    for field in ("updated_at", "created_at"):
        parsed = _parse_iso_timestamp(payload.get(field))
        if parsed is not None:
            return parsed
    if ticket.updated_at is not None:
        return ticket.updated_at
    if ticket.created_at is not None:
        return ticket.created_at
    return datetime.min.replace(tzinfo=UTC)


def sort_live_feed_tickets_by_updated_at_desc(
    tickets: Sequence[LiveVendorTicket],
) -> list[LiveVendorTicket]:
    """Sort tickets newest first (updated_at DESC, else created_at DESC)."""
    return sorted(tickets, key=_ticket_sort_key, reverse=True)


def _map_shadow_skip_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    mapped = _SHADOW_TO_DASHBOARD_SKIP.get(reason, "malformed_ticket")
    if mapped not in _DASHBOARD_SKIP_REASONS:
        return "malformed_ticket"
    return mapped


def classify_live_feed_dashboard_eligibility(
    ticket: LiveVendorTicket,
    *,
    settings: AppSettings | None = None,
) -> tuple[bool, str | None]:
    """Return (eligible, dashboard_skip_reason) for operator review intake."""
    cfg = settings or get_settings()
    if cfg.multi_turn_context_enabled and ticket.snapshot is not None:
        ctx = build_multi_turn_context(ticket.snapshot, settings=cfg)
        if ctx.should_generate_draft:
            return True, None
        return False, ctx.should_skip_reason or "malformed_ticket"
    ok, shadow_reason = classify_shadow_eligibility(ticket, dedupe=False)
    if ok:
        return True, None
    return False, _map_shadow_skip_reason(shadow_reason)


@dataclass(frozen=True)
class LiveFeedTicketEntry:
    """One live feed row for the operator dashboard (eligible or skipped)."""

    ticket: LiveVendorTicket | None
    room_id: str
    eligible: bool
    skip_reason: str | None
    line_number: int | None = None
    raw_source_system: str | None = None
    parse_error: str | None = None

    @property
    def updated_at_iso(self) -> str | None:
        if self.ticket is None:
            return None
        ts = self.ticket.updated_at or self.ticket.created_at
        return ts.isoformat() if ts else None

    @property
    def created_at_iso(self) -> str | None:
        if self.ticket is None or self.ticket.created_at is None:
            return None
        return self.ticket.created_at.isoformat()

    @property
    def message_count(self) -> int:
        if self.ticket is None or self.ticket.snapshot is None:
            return 0
        return len(self.ticket.snapshot.messages)

    @property
    def first_sender(self) -> str | None:
        if self.ticket is None or self.ticket.snapshot is None:
            return None
        return first_meaningful_sender_type(self.ticket.snapshot.messages)

    @property
    def latest_sender(self) -> str | None:
        if self.ticket is None or self.ticket.snapshot is None:
            return None
        return latest_meaningful_sender(self.ticket.snapshot.messages)

    @property
    def seller_preview(self) -> str | None:
        if self.ticket is None:
            return None
        return self.ticket.user_input[:200] if self.ticket.user_input else None

    @property
    def ticket_label(self) -> str | None:
        if self.ticket is None:
            return None
        return self.ticket.ticket_label

    @property
    def source_system(self) -> str | None:
        if self.raw_source_system:
            return self.raw_source_system
        if self.ticket is None or self.ticket.raw_payload is None:
            return None
        payload = self.ticket.raw_payload
        value = payload.get("source_system")
        if value is None and isinstance(payload.get("metadata"), dict):
            value = payload["metadata"].get("source_system")
        return str(value).strip() if value is not None else None


def load_live_feed_tickets(path: Path | str) -> list[LiveVendorTicket]:
    """Load normalized live feed JSONL; skips blank lines; raises if file missing."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"live feed file not found: {source}")

    tickets: list[LiveVendorTicket] = []
    for raw_line in source.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        row = json.loads(raw_line)
        if not isinstance(row, dict):
            raise ValueError("live feed row must be a JSON object")
        tickets.append(normalize_live_ticket(_adapt_live_feed_row(row)))
    return sort_live_feed_tickets_by_updated_at_desc(tickets)


def build_live_feed_dashboard_entries(
    tickets: Sequence[LiveVendorTicket],
    *,
    settings: AppSettings | None = None,
) -> list[LiveFeedTicketEntry]:
    """Classify each loaded ticket for dashboard display."""
    cfg = settings or get_settings()
    entries: list[LiveFeedTicketEntry] = []
    for ticket in tickets:
        eligible, skip_reason = classify_live_feed_dashboard_eligibility(ticket, settings=cfg)
        source = None
        if ticket.raw_payload and isinstance(ticket.raw_payload.get("source_system"), str):
            source = ticket.raw_payload["source_system"]
        entries.append(
            LiveFeedTicketEntry(
                ticket=ticket,
                room_id=ticket.room_id,
                eligible=eligible,
                skip_reason=skip_reason,
                raw_source_system=source,
            ),
        )
    return entries


def load_live_feed_dashboard_entries(
    path: Path | str,
    *,
    settings: AppSettings | None = None,
) -> list[LiveFeedTicketEntry]:
    """Load JSONL, sort newest-first, and attach eligibility for each row."""
    tickets = load_live_feed_tickets(path)
    return build_live_feed_dashboard_entries(tickets, settings=settings)


def filter_live_feed_eligible_tickets(
    tickets: Sequence[LiveVendorTicket],
) -> list[LiveVendorTicket]:
    """Keep only seller-first open tickets without support reply (dashboard scope)."""
    eligible: list[LiveVendorTicket] = []
    for ticket in tickets:
        ok, _ = classify_live_feed_dashboard_eligibility(ticket)
        if ok:
            eligible.append(ticket)
    return eligible


def filter_live_feed_eligible_entries(
    entries: Sequence[LiveFeedTicketEntry],
) -> list[LiveFeedTicketEntry]:
    """Keep dashboard entries marked eligible."""
    return [entry for entry in entries if entry.eligible]


def entry_eligibility_reason(entry: LiveFeedTicketEntry) -> str:
    """Dashboard eligibility filter key (eligible or skip reason)."""
    if entry.eligible:
        return ELIGIBILITY_FILTER_ELIGIBLE
    return entry.skip_reason or "malformed_ticket"


def distinct_live_feed_ticket_labels(entries: Sequence[LiveFeedTicketEntry]) -> list[str]:
    labels = {entry.ticket_label for entry in entries if entry.ticket_label}
    return sorted(labels)


def distinct_live_feed_first_senders(entries: Sequence[LiveFeedTicketEntry]) -> list[str]:
    senders = {entry.first_sender for entry in entries if entry.first_sender}
    return sorted(senders)


def distinct_live_feed_latest_senders(entries: Sequence[LiveFeedTicketEntry]) -> list[str]:
    senders = {entry.latest_sender for entry in entries if entry.latest_sender}
    return sorted(senders)


def filter_live_feed_dashboard_entries(
    entries: Sequence[LiveFeedTicketEntry],
    *,
    ticket_labels: Sequence[str] | None = None,
    eligibility_reasons: Sequence[str] | None = None,
    first_senders: Sequence[str] | None = None,
    latest_senders: Sequence[str] | None = None,
) -> list[LiveFeedTicketEntry]:
    """Apply dashboard filters; preserve input order (newest-first)."""
    label_set = set(ticket_labels) if ticket_labels else None
    eligibility_set = set(eligibility_reasons) if eligibility_reasons else None
    sender_set = set(first_senders) if first_senders else None
    latest_sender_set = set(latest_senders) if latest_senders else None

    filtered: list[LiveFeedTicketEntry] = []
    for entry in entries:
        if label_set is not None:
            label = entry.ticket_label or "unknown"
            if label not in label_set:
                continue
        if eligibility_set is not None:
            if entry_eligibility_reason(entry) not in eligibility_set:
                continue
        if sender_set is not None:
            sender = entry.first_sender or "unknown"
            if sender not in sender_set:
                continue
        if latest_sender_set is not None:
            latest = entry.latest_sender or "unknown"
            if latest not in latest_sender_set:
                continue
        filtered.append(entry)
    return filtered


def live_feed_detail_row_number(selected_index: int) -> int:
    """Convert 0-based filtered-list index to 1-based detail row number."""
    return max(1, selected_index + 1)


def resolve_live_feed_list_selection(
    row_labels: Sequence[str],
    selected_label: str | None,
) -> tuple[int, str] | None:
    """Resolve selectbox label to (0-based index, label); fallback to first row.

    Returns None when ``row_labels`` is empty (caller must skip detail render).
    """
    if not row_labels:
        return None
    labels = list(row_labels)
    if selected_label in labels:
        index = labels.index(selected_label)
        return index, labels[index]
    return 0, labels[0]


def resolve_live_feed_filter_selection(
    selected: Sequence[str] | None,
    *,
    all_options: Sequence[str],
) -> list[str] | None:
    """None means no filter (show all); empty selection means show none."""
    if selected is None:
        return None
    chosen = [value for value in selected if value in all_options]
    if not chosen:
        return []
    if len(chosen) >= len(all_options):
        return None
    return chosen


def load_live_feed_entries_from_lines(
    lines: Sequence[str],
) -> list[LiveFeedTicketEntry]:
    """Parse JSONL lines (for tests); malformed lines become skipped entries."""
    entries: list[LiveFeedTicketEntry] = []
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
            if not isinstance(row, dict):
                raise ValueError("row must be object")
            adapted = _adapt_live_feed_row(row)
            ticket = normalize_live_ticket(adapted)
            eligible, skip_reason = classify_live_feed_dashboard_eligibility(ticket)
            source = adapted.get("source_system")
            entries.append(
                LiveFeedTicketEntry(
                    ticket=ticket,
                    room_id=ticket.room_id,
                    eligible=eligible,
                    skip_reason=skip_reason,
                    line_number=line_number,
                    raw_source_system=str(source).strip() if source else None,
                ),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            room_hint = "unknown"
            try:
                parsed = json.loads(raw_line)
                if isinstance(parsed, dict) and parsed.get("room_id") is not None:
                    room_hint = str(parsed["room_id"])
                elif isinstance(parsed, dict) and parsed.get("id") is not None:
                    room_hint = str(parsed["id"])
            except json.JSONDecodeError:
                pass
            entries.append(
                LiveFeedTicketEntry(
                    ticket=None,
                    room_id=room_hint,
                    eligible=False,
                    skip_reason="malformed_ticket",
                    line_number=line_number,
                    parse_error=str(exc)[:200],
                ),
            )

    def _entry_sort_key(entry: LiveFeedTicketEntry) -> datetime:
        if entry.ticket is not None:
            return _ticket_sort_key(entry.ticket)
        return datetime.min.replace(tzinfo=UTC)

    entries.sort(key=_entry_sort_key, reverse=True)
    return entries
