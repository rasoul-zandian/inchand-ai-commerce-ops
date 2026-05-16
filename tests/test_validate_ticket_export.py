"""Tests for offline JSONL ticket export validator (no import/index)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.validate_ticket_export import (
    count_suspicious_tokens,
    format_json_report,
    main,
    validate_jsonl_content,
    validate_jsonl_file,
)


def _valid_line(*, label: str = "financial", status: str = "closed") -> str:
    payload = {
        "room_id": "ROOM_001",
        "ticket_label": label,
        "status": status,
        "seller_id": "SELLER_ID_001",
        "final_resolution": {"outcome": "resolved"},
        "messages": [
            {
                "message_id": "m1",
                "sender_type": "seller",
                "text": "مبلغ تسویه اشتباه است",
            },
            {
                "message_id": "m2",
                "sender_type": "support_agent",
                "text": "لطفاً شماره فاکتور را ارسال کنید",
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def test_valid_jsonl_passes(tmp_path: Path) -> None:
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(
        _valid_line(label="financial") + "\n" + _valid_line(label="support", status="open") + "\n",
        encoding="utf-8",
    )
    report = validate_jsonl_file(export_file)
    assert report.passed
    assert report.valid_tickets == 2
    assert report.invalid_lines == 0
    assert report.label_counts["financial"] == 1
    assert report.label_counts["support"] == 1
    assert report.sender_type_counts["seller"] == 2
    assert report.status_counts["closed"] == 1
    assert report.tickets_with_final_resolution == 2
    assert report.min_messages == 2
    assert report.max_messages == 2
    assert report.avg_messages == 2.0


def test_invalid_json_line_fails(tmp_path: Path) -> None:
    export_file = tmp_path / "bad.jsonl"
    export_file.write_text("{not json\n", encoding="utf-8")
    report = validate_jsonl_file(export_file)
    assert not report.passed
    assert report.invalid_lines == 1
    assert report.errors[0].line_number == 1


def test_validation_error_fails_without_message_text(tmp_path: Path) -> None:
    payload = json.loads(_valid_line())
    payload["messages"] = []
    export_file = tmp_path / "empty_messages.jsonl"
    export_file.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    report = validate_jsonl_file(export_file)
    assert not report.passed
    assert "at least one message" in report.errors[0].error_message
    assert "مبلغ" not in report.errors[0].error_message


def test_empty_lines_ignored_consistently() -> None:
    lines = ["", "   ", _valid_line(), ""]
    report = validate_jsonl_content(lines)
    assert report.passed
    assert report.total_lines == 1
    assert report.empty_lines_ignored == 3
    assert report.valid_tickets == 1


def test_json_output_works(tmp_path: Path) -> None:
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    report = validate_jsonl_file(export_file)
    payload = json.loads(format_json_report(report, path=str(export_file)))
    assert payload["passed"] is True
    assert payload["valid_tickets"] == 1
    assert payload["ticket_label_counts"]["financial"] == 1


def test_main_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good = tmp_path / "good.jsonl"
    good.write_text(_valid_line() + "\n", encoding="utf-8")
    assert main([str(good)]) == 0
    assert "result: passed" in capsys.readouterr().out

    bad = tmp_path / "bad.jsonl"
    bad.write_text("{bad\n", encoding="utf-8")
    capsys.readouterr()
    assert main([str(bad)]) == 1
    out = capsys.readouterr().out
    assert "FAILED" in out


def test_main_json_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    assert main([str(export_file), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True


def test_suspicious_tokens_counted_not_printed() -> None:
    text = "contact test@example.com or 09123456789 or IR120000000000000000000001"
    counts = count_suspicious_tokens(text)
    assert counts["email_like"] >= 1
    assert counts["phone_like"] >= 1
    assert counts["iban_like"] >= 1

    lines = [
        json.dumps(
            {
                "room_id": "ROOM_WARN",
                "ticket_label": "support",
                "messages": [
                    {
                        "message_id": "m1",
                        "sender_type": "seller",
                        "text": "email me at user@domain.com",
                    }
                ],
            }
        )
    ]
    report = validate_jsonl_content(lines)
    assert report.passed
    assert report.suspicious_warning_counts["email_like"] >= 1
    human = __import__(
        "scripts.validate_ticket_export", fromlist=["format_human_report"]
    ).format_human_report(report)
    assert "user@domain.com" not in human
    assert "email_like=" in human
