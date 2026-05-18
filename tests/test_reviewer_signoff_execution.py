"""Tests for local reviewer sign-off and approved room ID selection scripts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.reviewer_models import ReviewerDecision, ReviewerRole
from app.corpus_planning.room_selection import (
    RoomSelectionCriteria,
    format_approved_room_ids_file,
    select_approved_room_ids_from_rows,
    validate_approved_room_ids_against_export,
)
from scripts.create_reviewer_signoff import create_signoff_record, write_signoff_record
from scripts.select_approved_room_ids import main as select_main
from scripts.validate_approved_room_ids import main as validate_main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PILOT_CORPUS_DIR = _REPO_ROOT / "corpus" / "vendor_ticket_real_pilot"
_ALL_CHECKS = {
    "no_raw_pii_visible",
    "anonymization_verified",
    "retrieval_safe",
    "governance_approved",
    "corpus_scope_validated",
}


def _replay_row(
    *,
    room_id: str,
    label: str = "support",
    department: str = "support",
    qa_attention: bool = False,
    failed: bool = False,
) -> dict[str, object]:
    return {
        "room_id": room_id,
        "ticket_label": label,
        "assigned_department": department,
        "qa_issue_count": 1 if qa_attention else 0,
        "qa_warning_count": 0,
        "qa_passed": not qa_attention,
        "errors": ["workflow_error"] if failed else [],
    }


def test_approved_signoff_requires_all_checklist_checks() -> None:
    with pytest.raises(ValueError, match="requires --check"):
        create_signoff_record(
            signoff_id="signoff_test",
            source_batch_id="batch",
            reviewer_role=ReviewerRole.AI_OPS_REVIEWER,
            reviewer_id="rev1",
            decision=ReviewerDecision.APPROVED,
            checked_items={"no_raw_pii_visible"},
            privacy_review_completed=True,
            replay_review_completed=True,
            approved_record_count=10,
            signed_at_utc="2026-05-16T12:00:00Z",
        )


def test_rejected_signoff_without_all_checks(tmp_path: Path) -> None:
    record = create_signoff_record(
        signoff_id="signoff_reject",
        source_batch_id="batch",
        reviewer_role=ReviewerRole.PRIVACY_REVIEWER,
        reviewer_id="rev1",
        decision=ReviewerDecision.REJECTED,
        checked_items=set(),
        privacy_review_completed=True,
        replay_review_completed=True,
        approved_record_count=0,
        signed_at_utc="2026-05-16T12:00:00Z",
    )
    assert record.decision == ReviewerDecision.REJECTED
    out = tmp_path / "signoff.json"
    write_signoff_record(record, out, overwrite=True)
    text = out.read_text(encoding="utf-8")
    assert "draft_response" not in text
    assert "conversation_transcript" not in text


def test_approved_signoff_json_safe(tmp_path: Path) -> None:
    record = create_signoff_record(
        signoff_id="signoff_ok",
        source_batch_id="replay_166_redacted_v1",
        reviewer_role=ReviewerRole.AI_OPS_REVIEWER,
        reviewer_id="LOCAL_REVIEWER",
        decision=ReviewerDecision.APPROVED,
        checked_items=_ALL_CHECKS,
        privacy_review_completed=True,
        replay_review_completed=True,
        approved_record_count=20,
        signed_at_utc="2026-05-16T12:00:00Z",
    )
    out = tmp_path / "signoff.json"
    write_signoff_record(record, out, overwrite=True)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["decision"] == "approved"
    checklist_items = {item["item"] for item in payload["checklist_results"]}
    assert checklist_items == _ALL_CHECKS


def test_selection_excludes_qa_attention() -> None:
    rows = [
        _replay_row(room_id="ROOM_OK"),
        _replay_row(room_id="ROOM_QA", qa_attention=True),
    ]
    result = select_approved_room_ids_from_rows(
        rows,
        criteria=RoomSelectionCriteria(exclude_qa_attention=True),
    )
    assert result.selected_room_ids == ["ROOM_OK"]


def test_selection_respects_labels_and_limit() -> None:
    rows = [
        _replay_row(room_id="R1", label="support"),
        _replay_row(room_id="R2", label="fund"),
        _replay_row(room_id="R3", label="complaint"),
        _replay_row(room_id="R4", label="support"),
    ]
    result = select_approved_room_ids_from_rows(
        rows,
        criteria=RoomSelectionCriteria(
            limit=2,
            include_labels=frozenset({"support"}),
        ),
    )
    assert result.selected_room_ids == ["R1", "R4"]


def test_selection_zero_raises_via_cli(tmp_path: Path) -> None:
    report = tmp_path / "replay.jsonl"
    report.write_text(
        json.dumps(_replay_row(room_id="R1", qa_attention=True)) + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "approved.txt"
    code = select_main(
        [
            str(report),
            "-o",
            str(out),
            "--exclude-qa-attention",
            "--include-label",
            "support",
        ]
    )
    assert code == 1


def test_selection_output_format(tmp_path: Path) -> None:
    content = format_approved_room_ids_file(
        ["ROOM_A", "ROOM_B"],
        criteria=RoomSelectionCriteria(limit=25, exclude_qa_attention=True),
        source_report="reports/test.jsonl",
    )
    assert content.startswith("# Approved room IDs")
    assert "ROOM_A" in content
    assert "exclude_qa_attention: true" in content


def test_validate_catches_missing_room_id(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    export.write_text(
        json.dumps(
            {
                "room_id": "ROOM_A",
                "ticket_label": "support",
                "messages": [{"message_id": "m1", "sender_type": "seller", "text": "hi"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    approved = tmp_path / "approved.txt"
    approved.write_text("# test\nROOM_MISSING\n", encoding="utf-8")

    result = validate_approved_room_ids_against_export(export, approved)
    assert not result.passed
    assert "ROOM_MISSING" in result.missing_room_ids

    code = validate_main([str(export), "--approved-room-ids", str(approved)])
    assert code == 1


def test_validate_cli_passes(tmp_path: Path) -> None:
    export = tmp_path / "export.jsonl"
    export.write_text(
        json.dumps(
            {
                "room_id": "ROOM_A",
                "ticket_label": "support",
                "messages": [{"message_id": "m1", "sender_type": "seller", "text": "hi"}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    approved = tmp_path / "approved.txt"
    approved.write_text("# test\nROOM_A\n", encoding="utf-8")
    assert validate_main([str(export), "--approved-room-ids", str(approved)]) == 0


@pytest.mark.skipif(
    _PILOT_CORPUS_DIR.exists(),
    reason="local pilot corpus present after controlled build",
)
def test_no_corpus_directory_created() -> None:
    assert not _PILOT_CORPUS_DIR.exists()
