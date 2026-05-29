"""Tests for live API feed dashboard filters and datetime display."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.config import AppSettings
from app.operator_console.console_models import OperatorTicket, ticket_row_display_label
from app.operator_console.datetime_display import (
    format_datetime_for_console,
    format_gregorian_datetime,
    format_jalali_datetime,
)
from app.operator_console.i18n import LANG_EN, LANG_FA
from app.operator_console.live_feed_loader import (
    DEFAULT_LIVE_ROOMS_FETCH_LIMIT,
    ELIGIBILITY_FILTER_ELIGIBLE,
    LIVE_API_FEED_ELIGIBILITY_FILTER_KEY,
    LIVE_API_FEED_FIRST_SENDER_FILTER_KEY,
    LIVE_API_FEED_TICKET_LABEL_FILTER_KEY,
    entry_eligibility_reason,
    filter_live_feed_dashboard_entries,
    live_feed_detail_row_number,
    load_live_feed_entries_from_lines,
    resolve_live_feed_filter_selection,
    resolve_live_feed_list_selection,
)
from app.operator_console.live_feed_loader import (
    _ticket_sort_key as entry_sort_key,
)

from tests.test_live_feed_loader import _row


def _entries_from_rows(*rows: dict[str, object]) -> list:
    lines = [json.dumps(row) for row in rows]
    return load_live_feed_entries_from_lines(lines)


def test_ticket_label_filtering() -> None:
    entries = _entries_from_rows(
        _row(room_id="1", ticket_label="complaint"),
        _row(room_id="2", ticket_label="support"),
    )
    filtered = filter_live_feed_dashboard_entries(
        entries,
        ticket_labels=["complaint"],
    )
    assert len(filtered) == 1
    assert filtered[0].room_id == "1"


def test_eligibility_filtering() -> None:
    entries = _entries_from_rows(
        _row(room_id="ok"),
        _row(
            room_id="closed",
            status="closed",
            messages=[
                {
                    "message_id": "c-1",
                    "sender_type": "seller",
                    "text": "x",
                    "created_at": "2026-05-20T09:00:00+00:00",
                },
            ],
        ),
    )
    filtered = filter_live_feed_dashboard_entries(
        entries,
        eligibility_reasons=[ELIGIBILITY_FILTER_ELIGIBLE],
    )
    assert all(entry.eligible for entry in filtered)
    assert len(filtered) == 1
    assert filtered[0].room_id == "ok"


def test_first_sender_filtering() -> None:
    entries = _entries_from_rows(
        _row(room_id="seller_first"),
        _row(
            room_id="support_first",
            messages=[
                {
                    "message_id": "s-1",
                    "sender_type": "support_agent",
                    "text": "hi",
                    "created_at": "2026-05-20T09:00:00+00:00",
                },
            ],
        ),
    )
    filtered = filter_live_feed_dashboard_entries(entries, first_senders=["seller"])
    assert len(filtered) == 1
    assert filtered[0].room_id == "seller_first"


def test_filters_preserve_newest_first_order() -> None:
    entries = _entries_from_rows(
        _row(room_id="old", updated_at="2026-05-19T10:00:00+00:00", ticket_label="a"),
        _row(room_id="new", updated_at="2026-05-20T12:00:00+00:00", ticket_label="a"),
    )
    filtered = filter_live_feed_dashboard_entries(entries, ticket_labels=["a"])
    assert [entry.room_id for entry in filtered] == ["new", "old"]
    keys = [entry_sort_key(entry.ticket) for entry in filtered if entry.ticket]
    assert keys == sorted(keys, reverse=True)


def test_jalali_formatting() -> None:
    pytest.importorskip("jdatetime")
    dt = datetime(2026, 5, 26, 14, 37, tzinfo=UTC)
    formatted = format_jalali_datetime(dt)
    assert formatted.startswith("140")
    assert "/" in formatted
    assert ":" in formatted
    assert formatted.count(":") == 1
    assert len(formatted.split()[-1]) == 5


def test_en_mode_remains_gregorian() -> None:
    dt = datetime(2026, 5, 26, 14, 37, 45, tzinfo=UTC)
    assert format_datetime_for_console(dt, LANG_EN) == "2026-05-26 14:37"
    assert format_gregorian_datetime(dt) == "2026-05-26 14:37"


def test_fa_mode_uses_jalali() -> None:
    pytest.importorskip("jdatetime")
    dt = datetime(2026, 5, 26, 14, 37, tzinfo=UTC)
    fa_text = format_datetime_for_console(dt, LANG_FA)
    en_text = format_datetime_for_console(dt, LANG_EN)
    assert fa_text != en_text
    assert fa_text.startswith("140")


def test_default_fetch_limit_400() -> None:
    assert DEFAULT_LIVE_ROOMS_FETCH_LIMIT == 400
    settings = AppSettings()
    assert settings.live_rooms_api_fetch_limit == 400


def test_filter_session_keys_and_resolve_all() -> None:
    assert LIVE_API_FEED_TICKET_LABEL_FILTER_KEY == "live_api_feed_ticket_label_filter"
    assert LIVE_API_FEED_ELIGIBILITY_FILTER_KEY == "live_api_feed_eligibility_filter"
    assert LIVE_API_FEED_FIRST_SENDER_FILTER_KEY == "live_api_feed_first_sender_filter"
    options = ["a", "b"]
    assert resolve_live_feed_filter_selection(["a", "b"], all_options=options) is None
    assert resolve_live_feed_filter_selection(["a"], all_options=options) == ["a"]


def test_entry_eligibility_reason() -> None:
    entries = _entries_from_rows(_row(room_id="1"))
    assert entry_eligibility_reason(entries[0]) == ELIGIBILITY_FILTER_ELIGIBLE


def test_live_feed_first_row_row_number_is_one() -> None:
    assert live_feed_detail_row_number(0) == 1


def test_live_feed_detail_row_number_never_below_one() -> None:
    assert live_feed_detail_row_number(-1) == 1


def test_resolve_live_feed_list_selection_first_row() -> None:
    labels = ["#1 — a", "#2 — b"]
    resolved = resolve_live_feed_list_selection(labels, "#1 — a")
    assert resolved == (0, "#1 — a")


def test_resolve_live_feed_list_selection_stale_label_falls_back() -> None:
    labels = ["#1 — a", "#2 — b"]
    resolved = resolve_live_feed_list_selection(labels, "#99 — missing")
    assert resolved == (0, "#1 — a")


def test_resolve_live_feed_list_selection_empty_returns_none() -> None:
    assert resolve_live_feed_list_selection([], None) is None


def test_filter_change_preserves_valid_selection_index() -> None:
    entries = _entries_from_rows(
        _row(room_id="1", ticket_label="complaint"),
        _row(room_id="2", ticket_label="support"),
    )
    all_labels = [f"#{i} — {e.room_id}" for i, e in enumerate(entries, start=1)]
    filtered = filter_live_feed_dashboard_entries(entries, ticket_labels=["complaint"])
    filtered_labels = [f"#{i} — {e.room_id}" for i, e in enumerate(filtered, start=1)]
    assert len(filtered_labels) == 1
    stale = resolve_live_feed_list_selection(filtered_labels, all_labels[1])
    assert stale == (0, filtered_labels[0])


def test_ticket_row_display_label_accepts_live_feed_row_number() -> None:
    ticket = OperatorTicket(
        room_id="100",
        ticket_label="complaint",
        route_label=None,
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=None,
        latest_vendor_message=None,
        recent_context_preview=None,
    )
    label = ticket_row_display_label(live_feed_detail_row_number(0), ticket)
    assert label.startswith("#1 —")


def test_fetch_cli_default_limit_from_settings(monkeypatch) -> None:
    from scripts import fetch_live_rooms_api as cli

    monkeypatch.delenv("LIVE_ROOMS_API_TOKEN", raising=False)
    assert cli.DEFAULT_LIVE_ROOMS_FETCH_LIMIT == 400
