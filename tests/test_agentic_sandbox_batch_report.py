"""Tests for agentic sandbox batch report (first-vendor only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from app.agentic_sandbox.agentic_batch_report import (
    AgenticBatchRunRow,
    assert_batch_output_safe,
    error_batch_row,
    load_first_vendor_room_ids,
    render_agentic_batch_report_markdown,
    run_agentic_sandbox_batch,
    state_to_batch_row,
    summarize_agentic_batch_runs,
    write_batch_outputs,
)
from app.agentic_sandbox.agentic_state import initial_agentic_sandbox_state
from app.llm.types import LLMMessage, LLMResponse
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import KnowledgeHint
from app.tickets.conversation_models import ConversationMessage


def _mock_generate(messages: list[LLMMessage], *, provider: str, model: str) -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "conceptual_intent_fa": "پیگیری تسویه",
                "draft_reply": "لطفاً شماره سفارش را ارسال کنید.",
            },
            ensure_ascii=False,
        ),
        provider=provider,
        model=model,
        metadata={},
    )


def _message(sender_type: str, *, message_id: str = "m1") -> ConversationMessage:
    return ConversationMessage(
        message_id=message_id,
        sender_type=sender_type,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        text="body",
    )


def _snapshot(*senders: str, room_id: str) -> dict[str, object]:
    messages = [
        {
            "message_id": f"m{i}",
            "sender_type": sender,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "text": "preview text",
        }
        for i, sender in enumerate(senders)
    ]
    return {
        "room_id": room_id,
        "ticket_label": "support",
        "messages": messages,
    }


def _replay_row(room_id: str, *, preview: str | None = "seller issue") -> dict[str, object]:
    return {
        "room_id": room_id,
        "ticket_label": "support",
        "route_label": "general_vendor_support",
        "ai_assist_shadow_generated": True,
        "ai_assist_suggested_action": "human_followup",
        "ai_assist_human_review_required": True,
        "ai_assist_shadow_only": True,
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
        "original_vendor_issue_preview": preview,
        "errors": [],
    }


def _write_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    replay = tmp_path / "replay.jsonl"
    redacted = tmp_path / "redacted.jsonl"
    replay.write_text(
        "\n".join(
            [
                json.dumps(_replay_row("ROOM_VENDOR"), ensure_ascii=False),
                json.dumps(_replay_row("ROOM_SUPPORT"), ensure_ascii=False),
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    redacted.write_text(
        "\n".join(
            [
                json.dumps(_snapshot("seller", room_id="ROOM_VENDOR"), ensure_ascii=False),
                json.dumps(
                    _snapshot("support_agent", "seller", room_id="ROOM_SUPPORT"),
                    ensure_ascii=False,
                ),
            ],
        )
        + "\n",
        encoding="utf-8",
    )
    return replay, redacted


def test_only_first_vendor_rooms_selected(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted)
    assert "ROOM_VENDOR" in selection.room_ids
    assert "ROOM_SUPPORT" not in selection.room_ids
    assert selection.excluded_support_first >= 1


def test_support_first_rooms_excluded(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted)
    assert selection.first_vendor_rooms == 1
    assert selection.total_candidate_rooms == 2


def test_batch_continues_on_one_failed_room(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)

    def _resolve(room_id: str, **kwargs: object) -> OperatorTicket:
        if room_id == "ROOM_BAD":
            raise ValueError("boom")
        return OperatorTicket(
            room_id=room_id,
            ticket_label="support",
            route_label=None,
            assigned_department=None,
            review_priority=None,
            suggested_action=None,
            suggested_priority=None,
            escalation_recommended=None,
            duplicate_possible=None,
            confidence_band=None,
            retrieval_gate_decision=None,
            retrieval_result_count=None,
            ticket_text_preview=None,
            open_ticket_preview=None,
            original_vendor_issue_preview="لطفاً تایید کالا را بررسی کنید",
            latest_vendor_message=None,
            recent_context_preview=None,
        )

    with patch(
        "app.agentic_sandbox.agentic_batch_report.resolve_ticket_for_sandbox",
        side_effect=_resolve,
    ):
        rows = run_agentic_sandbox_batch(
            ("ROOM_VENDOR", "ROOM_BAD"),
            replay_jsonl=replay,
            redacted_jsonl=redacted,
            generate_fn=_mock_generate,
        )
    assert len(rows) == 2
    assert any(row.room_id == "ROOM_BAD" and row.errors for row in rows)
    assert any(row.room_id == "ROOM_VENDOR" for row in rows)


def test_summary_metrics_correct(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=1)
    rows = [
        error_batch_row("ROOM_ERR", error="test"),
    ]
    summary = summarize_agentic_batch_runs(
        rows,
        selection=selection,
        replay_jsonl=str(replay),
        redacted_jsonl=str(redacted),
    )
    assert summary.processed_count == 1
    assert summary.error_count == 1
    assert summary.execution_allowed_true_count == 0
    assert summary.customer_send_allowed_true_count == 0


def test_markdown_excludes_forbidden_raw_content(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=0)
    summary = summarize_agentic_batch_runs(
        [],
        selection=selection,
        replay_jsonl=str(replay),
    )
    md = render_agentic_batch_report_markdown(summary)
    assert "conversation transcript" not in md.lower()
    assert "gold_reference_reply" not in md
    assert_batch_output_safe(md)


def test_execution_and_send_remain_false_in_batch_row(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=1)
    rows = run_agentic_sandbox_batch(
        selection.room_ids,
        replay_jsonl=replay,
        redacted_jsonl=redacted,
        generate_fn=_mock_generate,
    )
    assert rows
    for row in rows:
        assert row.execution_allowed is False
        assert row.customer_send_allowed is False
        assert row.human_review_required is True
    payload = json.dumps(rows[0].to_json_dict(), ensure_ascii=False)
    assert "draft_reply" not in payload


def test_write_batch_outputs(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=1)
    rows = run_agentic_sandbox_batch(
        selection.room_ids,
        replay_jsonl=replay,
        redacted_jsonl=redacted,
        generate_fn=_mock_generate,
    )
    summary = summarize_agentic_batch_runs(
        rows,
        selection=selection,
        replay_jsonl=str(replay),
    )
    runs = tmp_path / "runs.jsonl"
    summary_path = tmp_path / "summary.json"
    md_path = tmp_path / "report.md"
    write_batch_outputs(
        rows, summary, runs_jsonl=runs, summary_json=summary_path, report_md=md_path
    )
    assert runs.is_file()
    line = json.loads(runs.read_text(encoding="utf-8").strip().splitlines()[0])
    assert "room_id" in line
    assert "draft_reply" not in line
    assert line["knowledge_hints_enabled"] is False


def test_default_batch_keeps_knowledge_hints_disabled(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=1)
    rows = run_agentic_sandbox_batch(
        selection.room_ids,
        replay_jsonl=replay,
        redacted_jsonl=redacted,
        generate_fn=_mock_generate,
    )
    assert rows
    assert all(row.knowledge_hints_enabled is False for row in rows)
    assert all(row.knowledge_hint_count == 0 for row in rows)


def test_enable_knowledge_hints_sets_flag_and_fetches_safe_metadata(
    tmp_path: Path,
) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=1)

    mock_hint = KnowledgeHint(
        document_type="settlement_rules",
        section_title="تسویه",
        source_lane="official_policy",
        priority_rank=1,
        snippet="sandbox snippet must not appear in batch jsonl",
        score=0.9,
    )

    with (
        patch(
            "app.operator_console.knowledge_hints.fetch_knowledge_hints_for_ticket",
            return_value=(mock_hint,),
        ) as fetch_mock,
        patch(
            "app.evals.first_turn_draft_context.fetch_knowledge_hints_for_ticket",
            return_value=(mock_hint,),
        ),
    ):
        rows = run_agentic_sandbox_batch(
            selection.room_ids,
            replay_jsonl=replay,
            redacted_jsonl=redacted,
            generate_fn=_mock_generate,
            enable_knowledge_hints=True,
        )

    assert fetch_mock.called
    assert rows
    row = rows[0]
    assert row.knowledge_hints_enabled is True
    assert row.knowledge_hint_count == 1
    assert row.knowledge_hint_document_types == ("settlement_rules",)
    payload = json.dumps(row.to_json_dict(), ensure_ascii=False)
    assert "sandbox snippet must not appear" not in payload
    assert '"snippet"' not in payload
    assert_batch_output_safe(payload)


def test_batch_row_includes_hint_metadata_without_raw_snippets() -> None:
    state = initial_agentic_sandbox_state(
        room_id="ROOM_META",
        first_turn_text="پیگیری تسویه",
        knowledge_hints_enabled=True,
    )
    state["knowledge_hints"] = [
        {
            "document_type": "settlement_rules",
            "section_title": "تسویه",
            "source_lane": "official_policy",
            "priority_rank": 1,
            "snippet_chars": 42,
        },
    ]
    state["draft_reply"] = "پاسخ کوتاه"
    state["safety_status"] = "passed"
    row = state_to_batch_row(state, success=True, knowledge_hints_enabled=True)
    assert row.knowledge_hint_count == 1
    assert row.knowledge_hint_document_types == ("settlement_rules",)
    text = json.dumps(row.to_json_dict(), ensure_ascii=False)
    assert "snippet_chars" not in text
    assert_batch_output_safe(text)


def test_coverage_summary_reflects_hints_when_present(tmp_path: Path) -> None:
    replay, redacted = _write_fixtures(tmp_path)
    selection = load_first_vendor_room_ids(replay, redacted_jsonl=redacted, limit=0)
    disabled_summary = summarize_agentic_batch_runs(
        [
            AgenticBatchRunRow(
                room_id="1",
                ticket_label="fund",
                route_label="billing_review",
                node_statuses={},
                safety_status="passed",
                detected_intent="settlement_status_inquiry",
                conceptual_intent_fa="پیگیری تسویه",
                suggested_action="billing_review",
                actionability_actionable=True,
                missing_required_entities=None,
                order_id_count=0,
                product_id_count=0,
                has_tracking_code=False,
                knowledge_hints_enabled=False,
                knowledge_hint_count=0,
                knowledge_hint_document_types=(),
                draft_char_count=10,
                human_review_required=True,
                execution_allowed=False,
                customer_send_allowed=False,
                success=True,
                errors=(),
            ),
        ],
        selection=selection,
        replay_jsonl=str(replay),
        knowledge_hints_enabled=False,
    )
    enabled_summary = summarize_agentic_batch_runs(
        [
            AgenticBatchRunRow(
                room_id="1",
                ticket_label="fund",
                route_label="billing_review",
                node_statuses={},
                safety_status="passed",
                detected_intent="settlement_status_inquiry",
                conceptual_intent_fa="پیگیری تسویه",
                suggested_action="billing_review",
                actionability_actionable=True,
                missing_required_entities=None,
                order_id_count=0,
                product_id_count=0,
                has_tracking_code=False,
                knowledge_hints_enabled=True,
                knowledge_hint_count=2,
                knowledge_hint_document_types=("settlement_rules", "support_faq"),
                draft_char_count=10,
                human_review_required=True,
                execution_allowed=False,
                customer_send_allowed=False,
                success=True,
                errors=(),
            ),
        ],
        selection=selection,
        replay_jsonl=str(replay),
        knowledge_hints_enabled=True,
    )
    assert disabled_summary.knowledge_hint_coverage_rate == 0.0
    assert enabled_summary.knowledge_hint_coverage_rate == 1.0
    assert enabled_summary.policy_relevant_with_hints == 1
    md = render_agentic_batch_report_markdown(enabled_summary)
    assert "knowledge_hint_coverage_rate" in md
