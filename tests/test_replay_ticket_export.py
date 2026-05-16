"""Tests for offline real-ticket replay harness (mock workflow, no external calls)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.schemas.workflow import ApprovalStatus, WorkflowStatus
from app.state.commerce_state import CommerceAIState
from app.tickets.conversation_models import ConversationTicketSnapshot
from scripts.replay_ticket_export import (
    build_replay_report_row,
    expected_department_from_ticket_label,
    is_label_department_mismatch,
    main,
    replay_jsonl_content,
    replay_jsonl_file,
)


def _valid_line(*, label: str = "financial", room_id: str = "ROOM_001") -> str:
    payload = {
        "room_id": room_id,
        "ticket_label": label,
        "ticket_subtype": "settlement_discrepancy",
        "status": "closed",
        "seller_id": "SELLER_ID_001",
        "messages": [
            {"message_id": "m1", "sender_type": "seller", "text": "مبلغ تسویه اشتباه است"},
            {
                "message_id": "m2",
                "sender_type": "support_agent",
                "text": "لطفاً شماره فاکتور را ارسال کنید",
            },
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _mock_state(
    *,
    route_label: str = "billing_review",
    ticket_label: str = "financial",
) -> CommerceAIState:
    return {
        "workflow_status": WorkflowStatus.AWAITING_APPROVAL,
        "approval_status": ApprovalStatus.REQUIRED,
        "human_approval_required": True,
        "detected_intent": "billing_discrepancy",
        "route_label": route_label,
        "ticket_label": ticket_label,
        "qa_passed": True,
        "qa_issues": [],
        "qa_warnings": [{"code": "tone"}],
        "qa_requires_human_attention": False,
        "risk_score": 0.3,
        "confidence_score": 0.9,
    }  # type: ignore[typeddict-item]


def _snapshot_from_line(line: str) -> ConversationTicketSnapshot:
    from app.tickets.conversation_models import parse_conversation_ticket_snapshot

    return parse_conversation_ticket_snapshot(line)


def test_valid_jsonl_produces_report_rows(tmp_path: Path) -> None:
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    report_file = tmp_path / "report.jsonl"

    def _fake_run(
        user_input: str,
        ticket_id: str | None = None,
        **kwargs: object,
    ) -> CommerceAIState:
        _ = user_input, ticket_id, kwargs
        return _mock_state()

    summary = replay_jsonl_file(export_file, report_file, run_workflow=_fake_run)
    assert summary.valid_tickets == 1
    assert summary.replayed_tickets == 1
    assert summary.failed_replays == 0
    rows = report_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1
    row = json.loads(rows[0])
    assert row["room_id"] == "ROOM_001"
    assert row["ticket_label"] == "financial"
    assert row["message_count"] == 2
    assert row["sender_types"] == ["seller", "support_agent"]
    assert row["workflow_status"] == "awaiting_approval"
    assert row["assigned_department"] == "finance"


def test_invalid_line_recorded_without_stopping_replay(tmp_path: Path) -> None:
    lines = [_valid_line(room_id="ROOM_OK"), "{not json"]
    calls = {"n": 0}

    def _fake_run(
        user_input: str,
        ticket_id: str | None = None,
        **kwargs: object,
    ) -> CommerceAIState:
        _ = user_input, kwargs
        _ = ticket_id
        calls["n"] += 1
        return _mock_state()

    report_rows, summary = replay_jsonl_content(lines, run_workflow=_fake_run)
    assert summary.valid_tickets == 1
    assert summary.invalid_lines == 1
    assert summary.replayed_tickets == 1
    assert len(report_rows) == 1
    assert calls["n"] == 1
    assert summary.parse_errors[0].line_number == 2


def test_output_excludes_draft_final_and_raw_text() -> None:
    line = _valid_line()
    snapshot = _snapshot_from_line(line)
    row = build_replay_report_row(snapshot, _mock_state())
    dumped = json.dumps(row, ensure_ascii=False)
    assert "draft_response" not in dumped
    assert "final_response" not in dumped
    assert "conversation_transcript" not in dumped
    assert "مبلغ تسویه" not in dumped
    assert "retrieved_context" not in dumped
    for forbidden in ("user_input", "messages", "tool_results"):
        assert forbidden not in row


def test_summary_counts_labels_routes_and_departments() -> None:
    lines = [
        _valid_line(label="financial", room_id="R1"),
        _valid_line(label="شکایت", room_id="R2"),
    ]

    def _fake_run(
        user_input: str,
        ticket_id: str | None = None,
        **kwargs: object,
    ) -> CommerceAIState:
        _ = user_input, kwargs
        label = "financial" if ticket_id == "R1" else "شکایت"
        route = "billing_review" if ticket_id == "R1" else "general_vendor_review"
        return _mock_state(route_label=route, ticket_label=label)

    _, summary = replay_jsonl_content(lines, run_workflow=_fake_run)
    assert summary.label_counts["financial"] == 1
    assert summary.label_counts["شکایت"] == 1
    assert summary.route_label_counts["billing_review"] == 1
    assert summary.assigned_department_counts["finance"] >= 1
    assert summary.assigned_department_counts["complaint"] >= 1


def test_mismatch_count_when_label_and_department_differ() -> None:
    assert expected_department_from_ticket_label("مالی") == "finance"
    assert is_label_department_mismatch("مالی", "support")
    assert not is_label_department_mismatch("مالی", "finance")
    assert not is_label_department_mismatch("unknown_topic", "general")
    assert not is_label_department_mismatch(None, "finance")


def test_mismatch_observed_in_replay_summary() -> None:
    line = _valid_line(label="مالی")

    def _fake_run(
        user_input: str,
        ticket_id: str | None = None,
        **kwargs: object,
    ) -> CommerceAIState:
        _ = user_input, ticket_id, kwargs
        return _mock_state(route_label="escalation_review", ticket_label="مالی")

    _, summary = replay_jsonl_content([line], run_workflow=_fake_run)
    assert summary.label_vs_department_mismatch_count >= 1
    assert summary.mismatch_examples
    example = summary.mismatch_examples[0]
    assert example.room_id == "ROOM_001"
    assert example.ticket_label == "مالی"
    assert "support" in example.assigned_department or example.assigned_department != "finance"


def test_workflow_can_be_monkeypatched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    report_file = tmp_path / "report.jsonl"
    seen: dict[str, Any] = {}

    def _patched(
        user_input: str,
        ticket_id: str | None = None,
        **kwargs: object,
    ) -> CommerceAIState:
        seen["user_input"] = user_input
        seen["ticket_id"] = ticket_id
        seen.update(kwargs)  # type: ignore[arg-type]
        return _mock_state()

    monkeypatch.setattr(
        "scripts.replay_ticket_export.run_vendor_ticket_demo",
        _patched,
    )
    summary = replay_jsonl_file(export_file, report_file)
    assert summary.replayed_tickets == 1
    assert seen.get("ticket_label") == "financial"
    assert seen.get("room_id") == "ROOM_001"


def test_failed_replay_records_error_row() -> None:
    line = _valid_line()

    def _boom(
        user_input: str,
        ticket_id: str | None = None,
        **kwargs: object,
    ) -> CommerceAIState:
        _ = user_input, ticket_id, kwargs
        raise RuntimeError("mock workflow failure")

    report_rows, summary = replay_jsonl_content([line], run_workflow=_boom)
    assert summary.failed_replays == 1
    assert summary.replay_errors
    assert report_rows[0]["errors"]
    assert "workflow_error" in report_rows[0]["errors"][0]


def test_main_cli_writes_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    export_file = tmp_path / "export.jsonl"
    export_file.write_text(_valid_line() + "\n", encoding="utf-8")
    report_file = tmp_path / "out.jsonl"

    def _fake_run(
        user_input: str,
        ticket_id: str | None = None,
        **kwargs: object,
    ) -> CommerceAIState:
        _ = user_input, ticket_id, kwargs
        return _mock_state()

    def _replay_stub(
        export_path: Path,
        output_path: Path,
        *,
        run_workflow: object = None,
    ) -> object:
        _ = run_workflow
        return replay_jsonl_file(export_path, output_path, run_workflow=_fake_run)

    monkeypatch.setattr("scripts.replay_ticket_export.replay_jsonl_file", _replay_stub)
    code = main([str(export_file), "--output", str(report_file)])
    assert code == 0
    assert report_file.is_file()
