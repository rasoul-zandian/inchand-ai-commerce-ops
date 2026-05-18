"""Tests for offline PII redaction (synthetic fixtures only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.privacy_review.redaction import (
    PIIRedactionType,
    redact_conversation_snapshot,
    redact_pii_text,
)
from app.tickets.conversation_models import parse_conversation_ticket_snapshot
from scripts.redact_ticket_export import main, redact_jsonl_file


def test_phone_redaction() -> None:
    result = redact_pii_text("تماس بگیرید 09123456789")
    assert result.changed is True
    assert "09123456789" not in result.redacted_text
    assert "[PHONE_NUMBER]" in result.redacted_text
    assert result.redaction_counts.get(PIIRedactionType.PHONE_NUMBER.value, 0) >= 1


def test_card_redaction_with_separators() -> None:
    result = redact_pii_text("کارت 1234-5678-9012-3456")
    assert result.changed is True
    assert "1234-5678-9012-3456" not in result.redacted_text
    assert "[CARD_NUMBER]" in result.redacted_text
    assert result.redaction_counts.get(PIIRedactionType.CARD_NUMBER.value, 0) >= 1


def test_iban_redaction() -> None:
    iban = "IR123456789012345678901234"
    result = redact_pii_text(f"شبا {iban}")
    assert iban not in result.redacted_text
    assert "[IBAN]" in result.redacted_text
    assert result.redaction_counts.get(PIIRedactionType.IBAN.value, 0) >= 1


def test_email_redaction() -> None:
    result = redact_pii_text("ایمیل seller@example.com")
    assert "seller@example.com" not in result.redacted_text
    assert "[EMAIL]" in result.redacted_text
    assert result.redaction_counts.get(PIIRedactionType.EMAIL.value, 0) >= 1


def test_snapshot_preserves_message_order() -> None:
    line = json.dumps(
        {
            "room_id": "ROOM_1",
            "ticket_label": "support",
            "messages": [
                {"message_id": "m1", "sender_type": "seller", "text": "اول"},
                {
                    "message_id": "m2",
                    "sender_type": "support_agent",
                    "text": "تماس 09111111111",
                },
            ],
        },
        ensure_ascii=False,
    )
    snapshot = parse_conversation_ticket_snapshot(line)
    redacted, counts = redact_conversation_snapshot(snapshot)
    assert redacted.messages[0].message_id == "m1"
    assert redacted.messages[1].message_id == "m2"
    assert redacted.messages[0].text == "اول"
    assert "[PHONE_NUMBER]" in redacted.messages[1].text
    assert counts.get(PIIRedactionType.PHONE_NUMBER.value, 0) >= 1


def test_cli_writes_valid_jsonl(tmp_path: Path) -> None:
    export = tmp_path / "in.jsonl"
    out = tmp_path / "out.jsonl"
    payload = {
        "room_id": "ROOM_A",
        "ticket_label": "support",
        "messages": [
            {"message_id": "m1", "sender_type": "seller", "text": "seller@test.com"},
        ],
    }
    export.write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")

    code = main([str(export), "-o", str(out)])
    assert code == 0
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["messages"][0]["text"] == "[EMAIL]"
    assert "seller@test.com" not in out.read_text(encoding="utf-8")


def test_summary_counts_replacements(tmp_path: Path) -> None:
    export = tmp_path / "in.jsonl"
    out = tmp_path / "out.jsonl"
    export.write_text(
        json.dumps(
            {
                "room_id": "R1",
                "ticket_label": "fund",
                "messages": [
                    {
                        "message_id": "m1",
                        "sender_type": "seller",
                        "text": "09112223344 و seller@x.com",
                    },
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    report = redact_jsonl_file(export, out, overwrite=True)
    assert report.output_records == 1
    assert report.records_changed == 1
    assert report.redaction_counts.get(PIIRedactionType.PHONE_NUMBER.value, 0) >= 1
    assert report.redaction_counts.get(PIIRedactionType.EMAIL.value, 0) >= 1


def test_output_exists_without_overwrite_fails(tmp_path: Path) -> None:
    export = tmp_path / "in.jsonl"
    out = tmp_path / "out.jsonl"
    export.write_text(
        json.dumps(
            {
                "room_id": "R1",
                "ticket_label": "support",
                "messages": [
                    {"message_id": "m1", "sender_type": "seller", "text": "سلام"},
                ],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    redact_jsonl_file(export, out, overwrite=True)
    with pytest.raises(ValueError, match="already exists"):
        redact_jsonl_file(export, out, overwrite=False)


def test_no_external_calls_in_redaction_module() -> None:
    source = (Path(__file__).resolve().parents[1] / "app/privacy_review/redaction.py").read_text(
        encoding="utf-8",
    )
    assert "import openai" not in source
    assert "pgvector" not in source
    assert "requests" not in source
