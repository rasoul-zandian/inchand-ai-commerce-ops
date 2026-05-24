"""Tests for operator console local JSONL feedback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.operator_console.feedback import (
    INTERNAL_NOTE_MAX_CHARS,
    append_operator_feedback,
    assert_internal_note_safe,
    build_operator_feedback_record,
    load_operator_feedback_summary,
)


def test_build_operator_feedback_record() -> None:
    record = build_operator_feedback_record(
        room_id="ROOM_1",
        suggested_action="monitor",
        ticket_label="support",
        route_label="general_vendor_support",
        feedback_type="helpful",
        internal_note="Looks reasonable",
    )
    assert record["room_id"] == "ROOM_1"
    assert record["feedback_type"] == "helpful"
    assert record["source"] == "operator_console"
    assert record["persisted_to"] == "local_jsonl"
    assert record["reviewer_id"] == "local_operator"
    assert len(record["feedback_id"]) == 36


def test_append_and_summary(tmp_path: Path) -> None:
    path = tmp_path / "operator_feedback.jsonl"
    r1 = build_operator_feedback_record(
        room_id="A",
        suggested_action="monitor",
        ticket_label="support",
        route_label="r1",
        feedback_type="helpful",
    )
    r2 = build_operator_feedback_record(
        room_id="B",
        suggested_action="escalate",
        ticket_label="complaint",
        route_label="r2",
        feedback_type="noisy",
    )
    append_operator_feedback(r1, path=path)
    append_operator_feedback(r2, path=path)
    summary = load_operator_feedback_summary(path)
    assert summary.total_count == 2
    assert summary.helpful_count == 1
    assert summary.noisy_wrong_count == 1


def test_internal_note_truncation() -> None:
    long_note = "x" * (INTERNAL_NOTE_MAX_CHARS + 50)
    record = build_operator_feedback_record(
        room_id="R",
        suggested_action=None,
        ticket_label=None,
        route_label=None,
        feedback_type="needs_human_followup",
        internal_note=long_note,
    )
    assert record["internal_note"] is not None
    assert len(record["internal_note"]) <= INTERNAL_NOTE_MAX_CHARS


def test_forbidden_pattern_in_note_rejected() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        assert_internal_note_safe("see draft_response in ticket")


def test_append_record_has_no_forbidden_keys(tmp_path: Path) -> None:
    path = tmp_path / "fb.jsonl"
    record = build_operator_feedback_record(
        room_id="Z",
        suggested_action="monitor",
        ticket_label="fund",
        route_label="billing_review",
        feedback_type="wrong_action",
    )
    append_operator_feedback(record, path=path)
    line = path.read_text(encoding="utf-8").strip()
    parsed = json.loads(line)
    forbidden = {"messages", "user_input", "draft_response", "final_response", "content"}
    assert forbidden.isdisjoint(parsed.keys())
