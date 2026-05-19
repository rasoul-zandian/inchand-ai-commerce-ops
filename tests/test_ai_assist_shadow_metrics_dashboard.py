"""Tests for AI assist shadow metrics dashboard builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.ai_assist_shadow_metrics_dashboard import (
    build_ai_assist_shadow_dashboard,
    compute_ai_assist_shadow_metrics,
    format_ai_assist_shadow_markdown,
    load_ai_assist_shadow_rows,
)


def _safe_rows() -> list[dict[str, object]]:
    return [
        {
            "room_id": "ROOM_FUND_1",
            "ticket_label": "fund",
            "route_label": "billing_review",
            "review_priority": "LOW",
            "assigned_department": "billing",
            "ai_assist_shadow_generated": True,
            "ai_assist_suggested_priority": "low",
            "ai_assist_escalation_recommended": False,
            "ai_assist_duplicate_possible": True,
            "ai_assist_suggested_action": "billing_review",
            "ai_assist_confidence_band": "high",
            "ai_assist_human_review_required": True,
            "ai_assist_shadow_only": True,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "errors": [],
        },
        {
            "room_id": "ROOM_COMPLAINT_1",
            "ticket_label": "complaint",
            "route_label": "escalation_review",
            "review_priority": "HIGH",
            "assigned_department": "escalation",
            "ai_assist_shadow_generated": True,
            "ai_assist_suggested_priority": "high",
            "ai_assist_escalation_recommended": True,
            "ai_assist_duplicate_possible": False,
            "ai_assist_suggested_action": "escalate",
            "ai_assist_confidence_band": "medium",
            "ai_assist_human_review_required": True,
            "ai_assist_shadow_only": True,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "errors": ["ai_assist_shadow_skipped: test"],
        },
        {
            "room_id": "ROOM_SUPPORT_1",
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "ai_assist_shadow_generated": False,
            "ai_assist_suggested_priority": None,
            "ai_assist_escalation_recommended": None,
            "ai_assist_duplicate_possible": None,
            "ai_assist_suggested_action": None,
            "ai_assist_confidence_band": None,
            "ai_assist_human_review_required": True,
            "ai_assist_shadow_only": True,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "errors": [],
        },
    ]


def test_compute_counts_and_matrices() -> None:
    metrics = compute_ai_assist_shadow_metrics(_safe_rows())
    assert metrics.total_rows == 3
    assert metrics.ai_assist_shadow_generated_count == 2
    assert metrics.escalation_recommended_count == 1
    assert metrics.duplicate_possible_count == 1
    assert metrics.suggested_action_counts["billing_review"] == 1
    assert metrics.suggested_action_counts["escalate"] == 1
    assert metrics.suggested_priority_counts["low"] == 1
    assert metrics.suggested_priority_counts["high"] == 1
    assert metrics.confidence_band_counts["high"] == 1
    assert metrics.error_count == 1
    assert metrics.label_action_matrix["fund"]["billing_review"] == 1
    assert metrics.label_priority_matrix["complaint"]["high"] == 1


def test_rejects_forbidden_draft_response_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    row = {
        "room_id": "R1",
        "ticket_label": "fund",
        "draft_response": "secret",
        "ai_assist_shadow_generated": False,
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
        "errors": [],
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden keys"):
        load_ai_assist_shadow_rows(path)


def test_rejects_retrieval_activated_true(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    row = {
        "room_id": "R1",
        "ticket_label": "fund",
        "ai_assist_shadow_generated": False,
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_activated": True,
        "downstream_consumed_retrieval": False,
        "errors": [],
    }
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="retrieval_activated"):
        load_ai_assist_shadow_rows(path)


def test_markdown_has_no_raw_content_fields() -> None:
    metrics = compute_ai_assist_shadow_metrics(_safe_rows())
    md = format_ai_assist_shadow_markdown(
        metrics,
        source_path="reports/ai_assist_shadow_replay_v1.jsonl",
        generated_at="2026-01-01T00:00:00Z",
    )
    lowered = md.lower()
    assert "draft_response" not in lowered
    assert "final_response" not in lowered
    assert '"messages"' not in lowered


def test_build_dashboard_writes_files(tmp_path: Path) -> None:
    input_path = tmp_path / "replay.jsonl"
    md_path = tmp_path / "dashboard.md"
    json_path = tmp_path / "dashboard.json"
    with input_path.open("w", encoding="utf-8") as handle:
        for row in _safe_rows():
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    metrics = build_ai_assist_shadow_dashboard(
        input_path,
        markdown_output=md_path,
        json_output=json_path,
        generated_at="2026-01-01T00:00:00Z",
    )
    assert metrics.total_rows == 3
    assert md_path.is_file()
    assert json_path.is_file()
