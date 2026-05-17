"""Tests for real JSON export → ConversationTicketSnapshot JSONL normalizer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.normalize_ticket_export import (
    format_human_report,
    load_export_array,
    main,
    normalize_export_file,
    normalize_export_records,
    normalize_record,
    normalize_sender_type,
)
from scripts.validate_ticket_export import validate_jsonl_file


def _sample_export() -> list[dict[str, object]]:
    return [
        {
            "id": "ROOM_REAL_001",
            "category": "financial",
            "shop_id": "SHOP_001",
            "messages": [
                {"type": "seller", "content": "مبلغ تسویه اشتباه است"},
                {"type": "support", "content": "لطفاً شماره فاکتور را ارسال کنید"},
                {"type": "bot", "content": "پیام سیستمی"},
            ],
        },
        {
            "id": "ROOM_REAL_002",
            "category": "complaint",
            "shop_id": "SHOP_002",
            "messages": [{"type": "vendor", "content": "سلام"}],
        },
    ]


def test_normalizes_sample_json_array() -> None:
    normalized, report = normalize_export_records(_sample_export())
    assert report.normalized_records == 2
    assert report.invalid_records == 0
    assert normalized[0]["room_id"] == "ROOM_REAL_001"
    assert normalized[0]["ticket_label"] == "financial"
    assert normalized[0]["seller_id"] == "SHOP_001"
    assert normalized[0]["ticket_subtype"] is None
    assert normalized[0]["final_resolution"] == {}


def test_generates_message_ids() -> None:
    payload, _ = normalize_record(_sample_export()[0])
    assert payload["messages"][0]["message_id"] == "ROOM_REAL_001_MSG_000"
    assert payload["messages"][1]["message_id"] == "ROOM_REAL_001_MSG_001"


def test_maps_sender_types() -> None:
    assert normalize_sender_type("seller") == ("seller", "seller")
    assert normalize_sender_type("vendor") == ("seller", "vendor")
    assert normalize_sender_type("support") == ("support_agent", "support")
    assert normalize_sender_type("admin") == ("support_agent", "admin")
    assert normalize_sender_type("financial") == ("finance_agent", "financial")
    assert normalize_sender_type("system") == ("system", "system")


def test_unknown_sender_type_maps_to_unknown() -> None:
    canonical, raw = normalize_sender_type("bot")
    assert canonical == "unknown"
    payload, _ = normalize_record(
        {
            "id": "ROOM_BOT",
            "category": "support",
            "messages": [{"type": "bot", "content": "test message"}],
        }
    )
    assert payload["messages"][0]["sender_type"] == "unknown"
    assert payload["messages"][0]["metadata"]["source_type"] == "bot"


def test_output_validates_as_jsonl(tmp_path: Path) -> None:
    input_path = tmp_path / "export.json"
    output_path = tmp_path / "normalized.jsonl"
    input_path.write_text(json.dumps(_sample_export(), ensure_ascii=False), encoding="utf-8")
    report = normalize_export_file(input_path, output_path)
    assert report.passed
    validation = validate_jsonl_file(output_path)
    assert validation.passed
    assert validation.valid_tickets == 2


def test_errors_exclude_raw_message_text() -> None:
    export = [
        {
            "id": "ROOM_BAD",
            "category": "support",
            "messages": [{"type": "seller", "content": "secret phrase xyz"}],
        },
        {"category": "support", "messages": []},
    ]
    _, report = normalize_export_records(export)
    assert report.invalid_records >= 1
    human = format_human_report(report)
    assert "secret phrase xyz" not in human
    assert "missing required field: id" in human


def test_missing_required_source_keys() -> None:
    with pytest.raises(ValueError, match="missing required field: id"):
        normalize_record({"category": "x", "messages": [{"type": "seller", "content": "hi"}]})
    with pytest.raises(ValueError, match="messages must contain at least one"):
        normalize_record({"id": "R1", "category": "x", "messages": []})


def test_cli_writes_output(tmp_path: Path) -> None:
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.jsonl"
    input_path.write_text(json.dumps(_sample_export(), ensure_ascii=False), encoding="utf-8")
    code = main([str(input_path), "--output", str(output_path)])
    assert code == 0
    assert output_path.is_file()
    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_cli_fails_on_invalid_records(tmp_path: Path) -> None:
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.jsonl"
    input_path.write_text(
        json.dumps([{"id": "R", "category": "x", "messages": []}], ensure_ascii=False),
        encoding="utf-8",
    )
    code = main([str(input_path), "--output", str(output_path)])
    assert code == 1


def test_load_export_array_rejects_non_array() -> None:
    with pytest.raises(ValueError, match="JSON array"):
        load_export_array('{"id": "x"}')


def _ticket_with_empty_message() -> dict[str, object]:
    return {
        "id": "ROOM_EMPTY_MSG",
        "category": "support",
        "messages": [
            {"type": "seller", "content": "valid line"},
            {"type": "support", "content": "   "},
            {"type": "seller", "content": "another valid"},
        ],
    }


def test_default_empty_message_fails() -> None:
    _, report = normalize_export_records([_ticket_with_empty_message()])
    assert report.invalid_records == 1
    assert report.normalized_records == 0
    assert report.skipped_empty_messages == 0


def test_skip_empty_messages_drops_empty_and_passes() -> None:
    normalized, report = normalize_export_records(
        [_ticket_with_empty_message()],
        skip_empty_messages=True,
    )
    assert report.passed
    assert report.normalized_records == 1
    assert report.skipped_empty_messages == 1
    assert len(normalized[0]["messages"]) == 2
    assert normalized[0]["messages"][0]["message_id"] == "ROOM_EMPTY_MSG_MSG_000"
    assert normalized[0]["messages"][1]["message_id"] == "ROOM_EMPTY_MSG_MSG_001"


def test_skip_empty_messages_all_empty_ticket_still_fails() -> None:
    export = [
        {
            "id": "ROOM_ALL_EMPTY",
            "category": "support",
            "messages": [
                {"type": "seller", "content": ""},
                {"type": "support", "content": "  "},
            ],
        }
    ]
    _, report = normalize_export_records(export, skip_empty_messages=True)
    assert report.invalid_records == 1
    assert report.normalized_records == 0
    assert report.skipped_empty_messages == 2
    assert "at least one message" in report.errors[0].error_message


def test_skip_empty_messages_summary_count(tmp_path: Path) -> None:
    input_path = tmp_path / "in.json"
    output_path = tmp_path / "out.jsonl"
    input_path.write_text(
        json.dumps([_ticket_with_empty_message()], ensure_ascii=False),
        encoding="utf-8",
    )
    report = normalize_export_file(
        input_path,
        output_path,
        skip_empty_messages=True,
    )
    human = format_human_report(report)
    assert "skipped_empty_messages=1" in human
    code = main([str(input_path), "--output", str(output_path), "--skip-empty-messages"])
    assert code == 0
