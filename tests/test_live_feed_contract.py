"""Tests for live feed adapter contract validation."""

from __future__ import annotations

import json
from pathlib import Path

from app.live_shadow.live_feed_contract import (
    assert_live_feed_validation_report_safe,
    normalize_live_ticket_row,
    normalize_sender_type,
    render_live_feed_contract_validation_markdown,
    summarize_live_feed_contract_validation,
    validate_live_ticket_row,
    write_live_feed_contract_validation_reports,
)


def _valid_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "room_id": "7743",
        "ticket_label": "support",
        "status": "open",
        "created_at": "2026-05-19T09:00:00+00:00",
        "updated_at": "2026-05-19T10:00:00+00:00",
        "messages": [
            {
                "message_id": "m1",
                "sender_type": "seller",
                "text": "Need help with payout",
                "created_at": "2026-05-19T10:00:00+00:00",
            },
        ],
    }
    row.update(overrides)
    return row


def test_valid_row_passes() -> None:
    result = validate_live_ticket_row(_valid_row())
    assert result.valid
    assert not result.errors


def test_missing_required_fields_fail() -> None:
    row = _valid_row()
    del row["status"]
    result = validate_live_ticket_row(row)
    assert not result.valid
    assert any("missing_required" in error for error in result.errors)


def test_sender_type_normalization() -> None:
    assert normalize_sender_type("vendor") == "seller"
    assert normalize_sender_type("admin") == "support_agent"
    assert normalize_sender_type("finance") == "finance_agent"
    normalized = normalize_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "vendor",
                    "text": "hello",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
    )
    assert normalized["messages"][0]["sender_type"] == "seller"


def test_empty_messages_fail() -> None:
    result = validate_live_ticket_row(_valid_row(messages=[]))
    assert not result.valid
    assert any("messages_empty" in error for error in result.errors)


def test_invalid_timestamp_fails() -> None:
    result = validate_live_ticket_row(_valid_row(created_at="not-a-date"))
    assert not result.valid
    assert any("invalid_timestamp" in error for error in result.errors)


def test_forbidden_key_rejected() -> None:
    result = validate_live_ticket_row(_valid_row(api_key="secret-value"))
    assert not result.valid
    assert any("forbidden_key" in error for error in result.errors)


def test_raw_email_allowed_in_internal_pilot_mode() -> None:
    result = validate_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "call me at test@example.com please",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
        allow_raw_pii_internal_pilot=True,
    )
    assert result.valid
    assert not any("raw_identifiers" in error for error in result.errors)
    assert any("raw_identifiers_detected" in note for note in result.info)


def test_raw_iban_allowed_in_internal_pilot_mode() -> None:
    result = validate_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "IBAN: IR120170000000123456789001",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
        allow_raw_pii_internal_pilot=True,
    )
    assert result.valid
    assert any("iban" in note for note in result.info)


def test_raw_phone_allowed_in_internal_pilot_mode() -> None:
    result = validate_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "تماس: 09121234567",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
        allow_raw_pii_internal_pilot=True,
    )
    assert result.valid
    assert any("phone" in note for note in result.info)


def test_raw_card_allowed_in_internal_pilot_mode() -> None:
    result = validate_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "card 4111 1111 1111 1111",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
        allow_raw_pii_internal_pilot=True,
    )
    assert result.valid
    assert any("card" in note for note in result.info)


def test_raw_identifiers_rejected_in_strict_mode() -> None:
    result = validate_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "call me at test@example.com please",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
        allow_raw_pii_internal_pilot=False,
    )
    assert not result.valid
    assert any("raw_identifiers_detected" in error for error in result.errors)


def test_secrets_still_rejected() -> None:
    result = validate_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": "token sk-abcdefghijklmnopqrstuvwxyz123456",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
        allow_raw_pii_internal_pilot=True,
    )
    assert not result.valid
    assert any("forbidden_secret_pattern" in error for error in result.errors)


def test_jwt_still_rejected() -> None:
    jwt = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    )
    result = validate_live_ticket_row(
        _valid_row(
            messages=[
                {
                    "message_id": "m1",
                    "sender_type": "seller",
                    "text": f"auth {jwt}",
                    "created_at": "2026-05-19T10:00:00+00:00",
                },
            ],
        ),
        allow_raw_pii_internal_pilot=True,
    )
    assert not result.valid
    assert any("jwt" in error for error in result.errors)


def test_summary_report_renders_safely(tmp_path: Path) -> None:
    feed = tmp_path / "live.jsonl"
    feed.write_text(json.dumps(_valid_row()) + "\n", encoding="utf-8")
    summary = summarize_live_feed_contract_validation(feed)
    markdown = render_live_feed_contract_validation_markdown(summary)
    assert "draft_reply" not in markdown.lower()
    assert "conversation transcript" not in markdown.lower()
    assert "Unredacted PII detected" not in markdown
    assert "allowed in internal pilot mode" in markdown
    assert_live_feed_validation_report_safe(markdown)
    json_path, md_path = write_live_feed_contract_validation_reports(
        summary,
        summary_json=tmp_path / "summary.json",
        report_md=tmp_path / "report.md",
    )
    assert json_path.is_file()
    assert md_path.is_file()
    assert_live_feed_validation_report_safe(json_path.read_text(encoding="utf-8"))


def test_validate_jsonl_file(tmp_path: Path) -> None:
    feed = tmp_path / "live.jsonl"
    feed.write_text(
        json.dumps(_valid_row()) + "\n" + json.dumps(_valid_row(room_id="7744")) + "\n",
        encoding="utf-8",
    )
    summary = summarize_live_feed_contract_validation(feed)
    assert summary.valid_rows == 2
    assert summary.passed
