"""Tests for read-only HITL panel markdown preview renderer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.hitl.hitl_payload_builder import build_hitl_read_only_payload_from_replay_row
from app.hitl.hitl_read_only_panel_preview import (
    assert_hitl_preview_markdown_safe,
    render_hitl_payload_markdown,
    render_hitl_payloads_markdown,
)


def _safe_payload() -> dict[str, object]:
    return build_hitl_read_only_payload_from_replay_row(
        {
            "room_id": "ROOM_1",
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
            "retrieval_gate_decision": "allow",
            "retrieval_scenario": "fund_finance",
            "retrieval_result_count": 5,
            "retrieval_metadata_filter": {
                "ticket_label": "fund",
                "route_label": "billing_review",
            },
            "retrieval_sandbox_only": True,
            "retrieval_activated": False,
            "errors": [],
        },
    )


def test_renders_safe_markdown() -> None:
    md = render_hitl_payload_markdown(_safe_payload())
    assert "## Ticket ROOM_1" in md
    assert "### Ticket metadata" in md
    assert "### Open ticket snapshot" in md
    assert "### AI assist summary" in md
    assert "### Retrieval aggregate summary" in md
    assert "billing_review" in md
    assert_hitl_preview_markdown_safe(md)


def test_includes_read_only_safety_footer() -> None:
    md = render_hitl_payload_markdown(_safe_payload())
    assert "Read-only. No customer response generated. No auto-send." in md


def test_rejects_unsafe_payload() -> None:
    bad = _safe_payload()
    bad["retrieval_activated"] = True
    with pytest.raises(ValueError, match="retrieval_activated"):
        render_hitl_payload_markdown(bad)


def test_excludes_forbidden_fields_from_output() -> None:
    md = render_hitl_payload_markdown(_safe_payload())
    lowered = md.lower()
    assert "retrieval_query_hash" not in lowered
    assert "draft_response" not in lowered
    assert "final_response" not in lowered
    assert "user_input" not in lowered
    assert '"messages"' not in lowered


def test_render_multiple_payloads() -> None:
    md = render_hitl_payloads_markdown([_safe_payload(), _safe_payload()])
    assert md.count("## Ticket ROOM_1") == 2
    assert "# HITL Read-Only Panel Preview" in md


def test_cli_writes_preview_file(tmp_path: Path) -> None:
    from scripts.render_hitl_read_only_panel_preview import main as render_main

    input_path = tmp_path / "payloads.json"
    output_path = tmp_path / "preview.md"
    input_path.write_text(
        json.dumps([_safe_payload()], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rc = render_main([str(input_path), "--output", str(output_path), "--overwrite"])
    assert rc == 0
    text = output_path.read_text(encoding="utf-8")
    assert "HITL Read-Only Panel Preview" in text
    assert "Read-only. No customer response generated" in text
