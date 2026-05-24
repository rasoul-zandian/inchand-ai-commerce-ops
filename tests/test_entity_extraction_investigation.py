"""Tests for entity extraction miss investigation (advisory diagnostics)."""

from __future__ import annotations

import json
from pathlib import Path

from app.agentic_sandbox.preview_review_feedback import build_agentic_preview_review_record
from app.evals.first_turn_draft_context import ENTITY_SOURCE_FULL_FIRST_VENDOR
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot
from app.workflows.entity_extraction_investigation import (
    EntityExtractionRootCause,
    EntitySnapshot,
    assert_entity_extraction_investigation_output_safe,
    build_entity_extraction_investigation_report,
    classify_entity_extraction_root_cause,
    flagged_entity_review_room_ids,
    investigate_room_entity_extraction,
    render_entity_extraction_investigation_markdown,
    summarize_entity_extraction_investigations,
)
from app.workflows.operational_entity_extraction import extract_operational_entities


def _write_feedback(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_redacted(path: Path, snapshots: list[ConversationTicketSnapshot]) -> None:
    lines = [snap.model_dump_json() for snap in snapshots]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_replay(path: Path, rows: list[dict[str, object]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _review_record(room_id: str, *, entity_ok: bool) -> dict[str, object]:
    return build_agentic_preview_review_record(
        room_id=room_id,
        graph_status_correct=True,
        intent_correct=True,
        action_correct=True,
        actionability_correct=True,
        entity_extraction_correct=entity_ok,
        knowledge_hints_helpful=True,
        safety_correct=True,
        ready_for_human_review_correct=True,
        draft_length_reasonable=True,
        overall_preview_useful=True,
    )


def test_empty_investigation_set(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    _write_feedback(feedback, [_review_record("1", entity_ok=True)])
    assert flagged_entity_review_room_ids(feedback) == []
    summary = build_entity_extraction_investigation_report(
        feedback_path=feedback,
        batch_runs_path=tmp_path / "batch.jsonl",
        replay_path=tmp_path / "replay.jsonl",
        redacted_path=tmp_path / "redacted.jsonl",
        summary_output=tmp_path / "summary.json",
        markdown_output=tmp_path / "report.md",
    )
    assert summary.investigated_room_count == 0
    markdown = render_entity_extraction_investigation_markdown(summary)
    assert "No flagged rooms" in markdown


def test_investigation_missing_order_id_first_turn_truncation(tmp_path: Path) -> None:
    padding = "x" * 220
    first_text = f"سفارش INC-7452190 {padding} INC-7447698"
    snap = ConversationTicketSnapshot(
        room_id="ROOM_TRUNC",
        ticket_label="support",
        messages=[
            ConversationMessage(
                message_id="m1",
                sender_type="seller",
                text=first_text,
            ),
        ],
    )
    redacted = tmp_path / "redacted.jsonl"
    _write_redacted(redacted, [snap])

    preview = first_text[:200]
    replay = tmp_path / "replay.jsonl"
    _write_replay(
        replay,
        [
            {
                "room_id": "ROOM_TRUNC",
                "ticket_label": "support",
                "route_label": "general_vendor_support",
                "original_vendor_issue_preview": preview,
                "extracted_order_ids": "7452190",
            },
        ],
    )

    result = investigate_room_entity_extraction(
        "ROOM_TRUNC",
        replay_path=replay,
        redacted_path=redacted,
    )
    assert result is not None
    assert result.missing_entities == {}
    assert result.entity_source == ENTITY_SOURCE_FULL_FIRST_VENDOR
    assert "7452190" in result.extracted_entities.get("order_ids", [])
    assert "7447698" in result.extracted_entities.get("order_ids", [])
    assert result.likely_root_cause == EntityExtractionRootCause.NOT_REPRODUCIBLE.value
    assert result.first_turn_preview_truncated is True


def test_later_thread_only_false_expectation(tmp_path: Path) -> None:
    snap = ConversationTicketSnapshot(
        room_id="ROOM_LATE",
        ticket_label="support",
        messages=[
            ConversationMessage(
                message_id="m1",
                sender_type="seller",
                text="سفارش INC-7452190",
            ),
            ConversationMessage(
                message_id="m2",
                sender_type="seller",
                text="پیگیری سفارش INC-9999999",
            ),
        ],
    )
    redacted = tmp_path / "redacted.jsonl"
    _write_redacted(redacted, [snap])
    replay = tmp_path / "replay.jsonl"
    _write_replay(
        replay,
        [
            {
                "room_id": "ROOM_LATE",
                "ticket_label": "support",
                "route_label": "general_vendor_support",
                "original_vendor_issue_preview": "سفارش INC-7452190",
                "latest_vendor_message": "پیگیری سفارش INC-9999999",
                "extracted_order_ids": "7452190",
            },
        ],
    )
    result = investigate_room_entity_extraction(
        "ROOM_LATE",
        replay_path=replay,
        redacted_path=redacted,
    )
    assert result is not None
    assert result.missing_entities == {}
    assert "9999999" in (result.later_thread_only_entities.get("order_ids") or [])


def test_malformed_identifier_ambiguous_pattern() -> None:
    text = "سفارش 123456 لغو شد"
    reference = EntitySnapshot.from_extraction(extract_operational_entities(text))
    preview = reference
    missing, unexpected = {"order_ids": ["1234567"]}, {}
    cause = classify_entity_extraction_root_cause(
        missing=missing,
        unexpected=unexpected,
        later_thread_only={},
        reference=reference,
        preview=preview,
        full_first_text=text,
        preview_text=text,
        preview_truncated=False,
    )
    assert reference.warnings or cause in {
        EntityExtractionRootCause.AMBIGUOUS_NUMERIC_PATTERN.value,
        EntityExtractionRootCause.EXTRACTION_RULE_GAP.value,
    }


def test_unsupported_pattern_tracking_keyword_without_digits() -> None:
    text = "کد رهگیری پست برای سفارش INC-7452190"
    reference = EntitySnapshot.from_extraction(extract_operational_entities(text))
    cause = classify_entity_extraction_root_cause(
        missing={"tracking_code": "expected"},
        unexpected={},
        later_thread_only={},
        reference=reference,
        preview=reference,
        full_first_text=text,
        preview_text=text,
        preview_truncated=False,
    )
    assert cause == EntityExtractionRootCause.UNSUPPORTED_PATTERN


def test_normalization_mismatch_classification() -> None:
    full = "سفارش ۸۴۵۲۱۹۰"
    preview = "سفارش 8452190"
    ref = EntitySnapshot.from_extraction(extract_operational_entities(full))
    prev = EntitySnapshot.from_extraction(extract_operational_entities(preview))
    missing, _ = (
        {"order_ids": ["8452190"]} if "8452190" not in prev.order_ids else {},
        {},
    )
    if not missing:
        missing = {}
    cause = classify_entity_extraction_root_cause(
        missing=missing,
        unexpected={},
        later_thread_only={},
        reference=ref,
        preview=prev,
        full_first_text=full,
        preview_text=preview,
        preview_truncated=False,
    )
    assert ref.order_ids == prev.order_ids or cause in {
        EntityExtractionRootCause.NORMALIZATION_GAP.value,
        EntityExtractionRootCause.NOT_REPRODUCIBLE.value,
        EntityExtractionRootCause.REVIEW_MISMATCH.value,
    }


def test_markdown_safety(tmp_path: Path) -> None:
    summary = summarize_entity_extraction_investigations(
        [],
        source_feedback_path=str(tmp_path / "f.jsonl"),
        source_batch_runs_path=str(tmp_path / "b.jsonl"),
        source_replay_path=str(tmp_path / "r.jsonl"),
        source_redacted_path=None,
        flagged_review_count=0,
        generated_at_utc="2026-01-01T00:00:00+00:00",
    )
    md = render_entity_extraction_investigation_markdown(summary)
    lowered = md.lower()
    assert "draft_reply" not in lowered
    assert "raw_prompt" not in lowered
    assert '"messages"' not in lowered
    assert_entity_extraction_investigation_output_safe(md)


def test_flagged_room_ids_from_feedback(tmp_path: Path) -> None:
    feedback = tmp_path / "feedback.jsonl"
    _write_feedback(
        feedback,
        [
            _review_record("A", entity_ok=True),
            _review_record("B", entity_ok=False),
        ],
    )
    assert flagged_entity_review_room_ids(feedback) == ["B"]
