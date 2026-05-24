"""Tests for live first-turn shadow intake (read-only)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from app.agentic_sandbox.agentic_batch_report import error_batch_row, state_to_batch_row
from app.live_feed.ticket_feed_adapter import normalize_live_ticket
from app.live_shadow.live_first_turn_shadow_intake import (
    LiveShadowFilterStats,
    assert_live_shadow_output_safe,
    assert_live_shadow_row_safe,
    build_shadow_result_row,
    classify_shadow_eligibility,
    compute_first_turn_signature,
    filter_first_turn_shadow_eligible,
    load_shadow_dedupe_keys,
    run_live_first_turn_shadow_intake,
    run_shadow_graph_for_ticket,
    summarize_live_shadow_runs,
)


def _seller_first_line(room_id: str = "LIVE_1", *, support_reply: bool = False) -> str:
    messages = [
        {
            "message_id": "m1",
            "sender_type": "seller",
            "text": "Need help with order INC-100",
            "timestamp": "2026-05-19T10:00:00+00:00",
        },
    ]
    if support_reply:
        messages.append(
            {
                "message_id": "m2",
                "sender_type": "support_agent",
                "text": "We are checking",
                "timestamp": "2026-05-19T11:00:00+00:00",
            },
        )
    payload = {
        "room_id": room_id,
        "ticket_label": "support",
        "status": "open",
        "messages": messages,
        "created_at": "2026-05-19T09:00:00+00:00",
    }
    return json.dumps(payload)


def _support_first_line(room_id: str = "LIVE_SUPPORT") -> str:
    payload = {
        "room_id": room_id,
        "ticket_label": "support",
        "status": "open",
        "messages": [
            {
                "message_id": "m1",
                "sender_type": "support_agent",
                "text": "Please send your order id",
                "timestamp": "2026-05-19T10:00:00+00:00",
            },
        ],
        "created_at": "2026-05-19T09:00:00+00:00",
    }
    return json.dumps(payload)


def test_first_turn_eligible_filter() -> None:
    tickets = [normalize_live_ticket(_seller_first_line("A"))]
    eligible, stats = filter_first_turn_shadow_eligible(tickets, dedupe=False)
    assert len(eligible) == 1
    assert stats.eligible_first_turn == 1
    assert stats.skipped_multi_turn == 0


def test_support_started_skipped() -> None:
    tickets = [normalize_live_ticket(_support_first_line())]
    eligible, stats = filter_first_turn_shadow_eligible(tickets, dedupe=False)
    assert not eligible
    assert stats.skipped_support_started == 1


def test_multi_turn_skipped() -> None:
    tickets = [normalize_live_ticket(_seller_first_line(support_reply=True))]
    eligible, stats = filter_first_turn_shadow_eligible(tickets, dedupe=False)
    assert not eligible
    assert stats.skipped_multi_turn == 1


def test_dedupe_works(tmp_path: Path) -> None:
    ticket = normalize_live_ticket(_seller_first_line("DEDUPE_1"))
    signature = compute_first_turn_signature(ticket)
    runs = tmp_path / "runs.jsonl"
    runs.write_text(
        json.dumps(
            {
                "room_id": "DEDUPE_1",
                "first_turn_signature": signature,
            },
        )
        + "\n",
        encoding="utf-8",
    )
    keys = load_shadow_dedupe_keys(runs)
    ok, reason = classify_shadow_eligibility(
        ticket,
        processed_keys=keys,
        dedupe=True,
    )
    assert not ok
    assert reason == "already_processed"


def test_safe_row_excludes_forbidden_fields() -> None:
    batch_row = error_batch_row("R1", error="test")
    row = build_shadow_result_row(
        batch_row,
        shadow_processed_at_utc="2026-05-20T00:00:00+00:00",
        first_turn_signature="abc123",
        provider="mock",
        processing_latency_ms=12,
        live_ticket_updated_at_utc=None,
        ticket_status="open",
    )
    payload = json.dumps(row.to_json_dict())
    assert "draft_reply" not in payload
    assert '"messages"' not in payload
    assert_live_shadow_row_safe(row)
    assert_live_shadow_output_safe(payload)


def test_shadow_graph_preserves_safety_flags() -> None:
    ticket = normalize_live_ticket(_seller_first_line("SAFE_1"))
    final_state = {
        "room_id": ticket.room_id,
        "ticket_label": ticket.ticket_label,
        "route_label": None,
        "safety_status": "passed",
        "draft_reply": "internal draft only",
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "node_results": [],
        "errors": [],
        "actionability": {},
        "extracted_entities": {},
        "knowledge_hints": [],
    }
    with patch(
        "app.live_shadow.live_first_turn_shadow_intake.run_agentic_sandbox_workflow",
        return_value=final_state,
    ):
        row, _ = run_shadow_graph_for_ticket(ticket, provider="mock")
    assert row.human_review_required is True
    assert row.execution_allowed is False
    assert row.customer_send_allowed is False
    assert "draft_reply" not in row.to_json_dict()


def test_summary_metrics_correct() -> None:
    batch_row = state_to_batch_row(
        {
            "room_id": "R1",
            "safety_status": "passed",
            "draft_reply": "x" * 10,
            "human_review_required": True,
            "execution_allowed": False,
            "customer_send_allowed": False,
            "node_results": [],
            "errors": [],
            "actionability": {"actionability_actionable": False},
            "extracted_entities": {},
            "knowledge_hints": [],
        },
        success=True,
    )
    shadow_row = build_shadow_result_row(
        batch_row,
        shadow_processed_at_utc="2026-05-20T00:00:00+00:00",
        first_turn_signature="sig",
        provider="mock",
        processing_latency_ms=100,
        live_ticket_updated_at_utc=None,
        ticket_status="open",
    )
    stats = LiveShadowFilterStats(
        total_live_seen=3,
        eligible_first_turn=1,
        skipped_multi_turn=1,
        skipped_support_started=1,
        skipped_internal_started=0,
        skipped_closed=0,
        skipped_not_first_vendor=0,
        skipped_missing_snapshot=0,
        skipped_missing_first_turn=0,
        skipped_not_open_status=0,
        skipped_already_processed=0,
    )
    summary = summarize_live_shadow_runs(
        [shadow_row],
        filter_stats=stats,
        live_feed_source="data/live.jsonl",
        provider="mock",
        knowledge_hints_enabled=False,
        limit_applied=25,
        since_hours=None,
        dedupe_enabled=True,
        dry_run=False,
        runs_jsonl=Path("reports/live_shadow_first_turn_runs.jsonl"),
    )
    assert summary.processed_count == 1
    assert summary.graph_success_count == 1
    assert summary.safety_pass_count == 1
    assert summary.draft_generation_count == 1
    assert summary.skipped_multi_turn == 1


def test_run_intake_end_to_end(tmp_path: Path) -> None:
    feed = tmp_path / "live.jsonl"
    feed.write_text(_seller_first_line("RUN_1") + "\n", encoding="utf-8")
    runs = tmp_path / "runs.jsonl"
    summary_path = tmp_path / "summary.json"
    final_state = {
        "room_id": "RUN_1",
        "ticket_label": "support",
        "route_label": None,
        "safety_status": "passed",
        "draft_reply": "سلام",
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "node_results": [{"node": "safety_gate", "status": "success"}],
        "errors": [],
        "detected_intent": "order_status",
        "suggested_action": "monitor",
        "actionability": {},
        "extracted_entities": {},
        "knowledge_hints": [],
    }
    with patch(
        "app.live_shadow.live_first_turn_shadow_intake.run_agentic_sandbox_workflow",
        return_value=final_state,
    ):
        summary = run_live_first_turn_shadow_intake(
            source_path=feed,
            runs_jsonl=runs,
            summary_json=summary_path,
            limit=5,
            dedupe=False,
            overwrite=True,
        )
    assert summary.processed_count == 1
    assert runs.is_file()
    line = runs.read_text(encoding="utf-8").strip()
    row = json.loads(line)
    assert row["room_id"] == "RUN_1"
    assert row["execution_allowed"] is False
    assert_live_shadow_output_safe(line)
