"""Tests for offline privacy-warning review workflow (no raw text in outputs)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.privacy_review.models import (
    PrivacyWarningRecord,
    PrivacyWarningType,
)
from app.privacy_review.review_builders import (
    build_privacy_review_summary,
    build_privacy_warning_record,
    build_privacy_warning_records_from_export_lines,
    corpus_eligible_for_warning_types,
    summary_to_json_dict,
    warning_types_for_snapshot,
)
from app.tickets.conversation_models import parse_conversation_ticket_snapshot
from pydantic import ValidationError
from scripts.build_privacy_review_report import (
    assert_privacy_output_safe,
    build_privacy_review_report,
    main,
    write_privacy_review_report,
)


def _export_line(
    *,
    room_id: str = "ROOM_WARN",
    text: str = "سلام",
) -> str:
    payload = {
        "room_id": room_id,
        "ticket_label": "support",
        "messages": [
            {"message_id": "m1", "sender_type": "seller", "text": text},
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _replay_row(*, room_id: str = "ROOM_WARN") -> dict[str, object]:
    return {
        "room_id": room_id,
        "ticket_label": "support",
        "assigned_department": "support",
        "review_priority": "LOW",
        "route_label": "general_vendor_support",
        "errors": [],
    }


def test_privacy_warning_record_validation() -> None:
    record = build_privacy_warning_record(
        "ROOM_1",
        [PrivacyWarningType.PHONE_LIKE, PrivacyWarningType.IBAN_LIKE],
    )
    assert record.warning_count == 2
    assert record.requires_manual_review is True
    assert record.corpus_eligible is False

    with pytest.raises(ValidationError):
        PrivacyWarningRecord(
            room_id="",
            warning_types=[PrivacyWarningType.PHONE_LIKE],
            warning_count=1,
        )

    with pytest.raises(ValidationError):
        PrivacyWarningRecord(
            room_id="ROOM_1",
            warning_types=[],
            warning_count=1,
        )

    with pytest.raises(ValidationError):
        PrivacyWarningRecord(
            room_id="ROOM_1",
            warning_types=[PrivacyWarningType.PHONE_LIKE],
            warning_count=0,
        )


def test_privacy_review_summary_aggregation() -> None:
    records = [
        build_privacy_warning_record("R1", [PrivacyWarningType.PHONE_LIKE]),
        build_privacy_warning_record(
            "R2",
            [PrivacyWarningType.IBAN_LIKE, PrivacyWarningType.CARD_LIKE_LONG_DIGITS],
        ),
    ]
    summary = build_privacy_review_summary(
        total_tickets_reviewed=5,
        warning_records=records,
        warning_type_counts={
            "phone_like": 1,
            "iban_like": 1,
            "card_like_long_digits": 1,
        },
    )
    assert summary.total_tickets_reviewed == 5
    assert summary.tickets_with_warnings == 2
    assert summary.corpus_eligible_count == 3
    assert summary.corpus_blocked_count == 2
    assert summary.manual_review_required_count == 2


def test_corpus_eligibility_logic() -> None:
    assert corpus_eligible_for_warning_types([]) is True
    assert corpus_eligible_for_warning_types([PrivacyWarningType.PHONE_LIKE]) is False


def test_warning_types_for_snapshot_detects_patterns() -> None:
    snapshot = parse_conversation_ticket_snapshot(
        _export_line(text="تماس 09123456789 و IR123456789012345678901234 و 1234567890123456")
    )
    types = warning_types_for_snapshot(snapshot)
    assert PrivacyWarningType.PHONE_LIKE in types
    assert PrivacyWarningType.IBAN_LIKE in types
    assert PrivacyWarningType.CARD_LIKE_LONG_DIGITS in types


def test_build_records_from_export_lines() -> None:
    lines = [
        _export_line(room_id="CLEAN"),
        _export_line(room_id="WARN", text="شماره 09111111111"),
    ]
    records, counts = build_privacy_warning_records_from_export_lines(lines)
    assert len(records) == 1
    assert records[0].room_id == "WARN"
    assert counts["phone_like"] == 1


def test_markdown_and_json_report_generation(tmp_path: Path) -> None:
    replay_file = tmp_path / "replay.jsonl"
    export_file = tmp_path / "export.jsonl"
    replay_file.write_text(
        json.dumps(_replay_row(room_id="CLEAN"))
        + "\n"
        + json.dumps(_replay_row(room_id="WARN"))
        + "\n",
        encoding="utf-8",
    )
    export_file.write_text(
        _export_line(room_id="CLEAN")
        + "\n"
        + _export_line(room_id="WARN", text="09112223333")
        + "\n",
        encoding="utf-8",
    )

    md_path = tmp_path / "privacy.md"
    json_path = tmp_path / "privacy.json"
    summary = write_privacy_review_report(
        replay_file,
        markdown_output=md_path,
        json_output=json_path,
        export_path=export_file,
    )

    assert summary.total_tickets_reviewed == 2
    assert summary.tickets_with_warnings == 1

    markdown = md_path.read_text(encoding="utf-8")
    assert "# Privacy Warning Review Report" in markdown
    assert "WARN" in markdown
    assert "09112223333" not in markdown
    assert_privacy_output_safe(markdown)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["corpus_blocked_count"] == 1
    assert payload["tickets_with_warnings"][0]["room_id"] == "WARN"
    assert "messages" not in json.dumps(payload)
    assert_privacy_output_safe(json.dumps(payload))


def test_forbidden_keys_rejected_in_replay_input(tmp_path: Path) -> None:
    replay_file = tmp_path / "bad_replay.jsonl"
    row = _replay_row()
    row["draft_response"] = "secret draft"
    replay_file.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden key"):
        build_privacy_review_report(replay_file)


def test_safety_assertion_rejects_forbidden_tokens() -> None:
    with pytest.raises(ValueError, match="forbidden token"):
        assert_privacy_output_safe('{"note": "sk-abc123"}')


def test_cli_success_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    replay_file = tmp_path / "replay.jsonl"
    export_file = tmp_path / "export.jsonl"
    replay_file.write_text(json.dumps(_replay_row()) + "\n", encoding="utf-8")
    export_file.write_text(_export_line() + "\n", encoding="utf-8")
    md_path = tmp_path / "out.md"

    code = main(
        [
            str(replay_file),
            "--export-path",
            str(export_file),
            "-o",
            str(md_path),
        ]
    )
    assert code == 0
    assert md_path.is_file()

    missing = main([str(tmp_path / "missing.jsonl"), "-o", str(md_path)])
    assert missing == 1


def test_summary_to_json_dict_shape() -> None:
    record = build_privacy_warning_record("R1", [PrivacyWarningType.PHONE_LIKE])
    summary = build_privacy_review_summary(
        total_tickets_reviewed=1,
        warning_records=[record],
    )
    payload = summary_to_json_dict(
        summary,
        warning_records=[record],
        replay_path="reports/replay.jsonl",
        export_path="data/private/export.jsonl",
        generated_at="2026-05-16T00:00:00Z",
    )
    assert payload["summary"]["total_tickets_reviewed"] == 1
    assert payload["tickets_with_warnings"][0]["corpus_eligible"] is False
