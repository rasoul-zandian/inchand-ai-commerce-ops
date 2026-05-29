"""Tests for operator console live API feed loader (Step 218)."""

from __future__ import annotations

import json
from pathlib import Path

from app.operator_console.live_feed_loader import (
    CONSOLE_DATA_SOURCE_SESSION_KEY,
    LIVE_API_FEED_ENTRIES_SESSION_KEY,
    SOURCE_HISTORICAL_REPLAY,
    SOURCE_LIVE_API_FEED,
    build_live_feed_dashboard_entries,
    classify_live_feed_dashboard_eligibility,
    filter_live_feed_eligible_tickets,
    load_live_feed_dashboard_entries,
    load_live_feed_entries_from_lines,
    load_live_feed_tickets,
    sort_live_feed_tickets_by_updated_at_desc,
)


def _row(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "room_id": "100",
        "ticket_label": "complaint",
        "status": "open",
        "created_at": "2026-05-20T09:00:00+00:00",
        "updated_at": "2026-05-20T10:00:00+00:00",
        "source_system": "inchand_internal_rooms_api",
        "messages": [
            {
                "message_id": "100-1",
                "sender_type": "seller",
                "text": "سلام، مشکل تسویه",
                "created_at": "2026-05-20T09:00:00+00:00",
            },
        ],
    }
    base.update(overrides)
    return base


def test_load_live_feed_tickets(tmp_path: Path) -> None:
    path = tmp_path / "data" / "private" / "live.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_row(room_id="A")) + "\n", encoding="utf-8")
    tickets = load_live_feed_tickets(path)
    assert len(tickets) == 1
    assert tickets[0].room_id == "A"


def test_sort_newest_first_by_updated_at() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    older = normalize_live_ticket(_row(room_id="1", updated_at="2026-05-19T10:00:00+00:00"))
    newer = normalize_live_ticket(_row(room_id="2", updated_at="2026-05-20T10:00:00+00:00"))
    sorted_tickets = sort_live_feed_tickets_by_updated_at_desc([older, newer])
    assert [ticket.room_id for ticket in sorted_tickets] == ["2", "1"]


def test_sort_fallback_created_at_when_updated_missing() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    row_old = _row(room_id="1", updated_at="2026-05-19T10:00:00+00:00")
    del row_old["updated_at"]
    row_old["created_at"] = "2026-05-18T09:00:00+00:00"
    row_new = _row(room_id="2", updated_at="2026-05-20T10:00:00+00:00")
    del row_new["updated_at"]
    row_new["created_at"] = "2026-05-20T11:00:00+00:00"
    older = normalize_live_ticket(row_old)
    newer = normalize_live_ticket(row_new)
    sorted_tickets = sort_live_feed_tickets_by_updated_at_desc([older, newer])
    assert sorted_tickets[0].room_id == "2"


def test_seller_first_eligibility() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    ticket = normalize_live_ticket(_row())
    eligible, reason = classify_live_feed_dashboard_eligibility(ticket)
    assert eligible
    assert reason is None


def test_support_reply_skip() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    ticket = normalize_live_ticket(
        _row(
            messages=[
                {
                    "message_id": "100-1",
                    "sender_type": "seller",
                    "text": "help",
                    "created_at": "2026-05-20T09:00:00+00:00",
                },
                {
                    "message_id": "100-2",
                    "sender_type": "support_agent",
                    "text": "reply",
                    "created_at": "2026-05-20T10:00:00+00:00",
                },
            ],
        ),
    )
    eligible, reason = classify_live_feed_dashboard_eligibility(ticket)
    assert not eligible
    assert reason == "support_replied"


def test_support_started_skip() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    ticket = normalize_live_ticket(
        _row(
            messages=[
                {
                    "message_id": "100-1",
                    "sender_type": "support_agent",
                    "text": "hello",
                    "created_at": "2026-05-20T09:00:00+00:00",
                },
            ],
        ),
    )
    eligible, reason = classify_live_feed_dashboard_eligibility(ticket)
    assert not eligible
    assert reason == "support_started"


def test_closed_ticket_skip() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    ticket = normalize_live_ticket(_row(status="closed"))
    eligible, reason = classify_live_feed_dashboard_eligibility(ticket)
    assert not eligible
    assert reason == "closed_ticket"


def test_malformed_row_handling() -> None:
    entries = load_live_feed_entries_from_lines(['{"room_id":', json.dumps(_row())])
    assert len(entries) == 2
    malformed = [entry for entry in entries if entry.skip_reason == "malformed_ticket"]
    assert len(malformed) == 1
    assert malformed[0].ticket is None


def test_filter_live_feed_eligible_tickets() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    eligible_ticket = normalize_live_ticket(_row(room_id="ok"))
    closed_ticket = normalize_live_ticket(_row(room_id="closed", status="closed"))
    filtered = filter_live_feed_eligible_tickets([eligible_ticket, closed_ticket])
    assert len(filtered) == 1
    assert filtered[0].room_id == "ok"


def test_load_dashboard_entries_sorted(tmp_path: Path) -> None:
    path = tmp_path / "data" / "private" / "feed.jsonl"
    path.parent.mkdir(parents=True)
    lines = [
        json.dumps(_row(room_id="old", updated_at="2026-05-19T10:00:00+00:00")),
        json.dumps(_row(room_id="new", updated_at="2026-05-20T12:00:00+00:00")),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    entries = load_live_feed_dashboard_entries(path)
    assert entries[0].room_id == "new"
    assert entries[1].room_id == "old"


def test_refresh_reload_picks_up_new_rows(tmp_path: Path) -> None:
    path = tmp_path / "data" / "private" / "feed.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_row(room_id="1")) + "\n", encoding="utf-8")
    first = load_live_feed_dashboard_entries(path)
    assert len(first) == 1
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_row(room_id="2")) + "\n")
    second = load_live_feed_dashboard_entries(path)
    assert len(second) == 2


def test_source_selector_session_keys_isolated() -> None:
    assert CONSOLE_DATA_SOURCE_SESSION_KEY == "operator_console_data_source"
    assert SOURCE_HISTORICAL_REPLAY == "historical_replay"
    assert SOURCE_LIVE_API_FEED == "live_api_feed"
    assert LIVE_API_FEED_ENTRIES_SESSION_KEY.startswith("live_api_feed_")
    assert "replay" not in LIVE_API_FEED_ENTRIES_SESSION_KEY


def test_build_entries_eligible_count() -> None:
    from app.live_feed.ticket_feed_adapter import normalize_live_ticket

    tickets = [
        normalize_live_ticket(_row(room_id="a")),
        normalize_live_ticket(_row(room_id="b", status="closed")),
    ]
    entries = build_live_feed_dashboard_entries(tickets)
    assert sum(1 for entry in entries if entry.eligible) == 1
