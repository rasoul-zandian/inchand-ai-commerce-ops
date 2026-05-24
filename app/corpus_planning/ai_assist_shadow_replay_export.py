"""Export sanitized AI assist shadow replay JSONL from local ticket exports (offline only)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.config import AppSettings, get_settings
from app.corpus_planning.ai_assist_shadow_metrics_dashboard import load_ai_assist_shadow_rows
from app.corpus_planning.ai_assist_shadow_replay_row_contract import (
    assert_ai_assist_shadow_replay_jsonl_line_safe,
    assert_ai_assist_shadow_replay_row_safe,
)
from app.corpus_planning.sandbox_retrieval_chain_dry_run import (
    SandboxRetrievalChainDryRunConfig,
    SandboxRetrievalChainDryRunResult,
)
from app.corpus_planning.shadow_replay_jsonl_export import (
    LineError,
    ShadowReplayExportConfig,
    _format_validation_error,
    _review_metadata_fields,
    build_initial_state_from_snapshot,
    configure_mock_workflow_runtime,
    export_shadow_replay_row_for_snapshot,
    resolve_shadow_export_route_label,
    run_routing_pipeline,
)
from app.hitl.hitl_payload_builder import extract_hitl_retrieval_fields_from_source
from app.hitl.ticket_text_preview import attach_ticket_text_preview_to_row
from app.live_feed.open_ticket_snapshot import (
    attach_open_ticket_snapshot_to_row,
    build_open_ticket_snapshot,
    open_ticket_snapshot_to_payload,
)
from app.state.ai_assist_state import apply_ai_assist_result_to_state
from app.state.commerce_state import CommerceAIState
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)
from app.workflows.vendor_ticket_ai_assist_shadow import evaluate_vendor_ticket_ai_assist_shadow


@dataclass
class AIAssistShadowReplayExportSummary:
    total_lines: int = 0
    empty_lines_ignored: int = 0
    valid_tickets: int = 0
    exported_rows: int = 0
    assist_executed_count: int = 0
    assist_generated_count: int = 0
    invalid_lines: int = 0
    export_failures: int = 0
    label_counts: Counter[str] = field(default_factory=Counter)
    suggested_action_counts: Counter[str] = field(default_factory=Counter)
    parse_errors: list[LineError] = field(default_factory=list)
    export_errors: list[LineError] = field(default_factory=list)


def build_ai_assist_shadow_replay_export_row(
    snapshot: ConversationTicketSnapshot,
    state: CommerceAIState,
    *,
    assist_executed: bool,
    export_errors: list[str] | None = None,
) -> dict[str, Any]:
    """One sanitized JSON object per ticket for AI assist shadow metrics."""
    row_errors = list(export_errors or [])
    priority, assigned_department, meta_errors = _review_metadata_fields(state)
    row_errors.extend(meta_errors)

    route_label = state.get("route_label")
    if not (isinstance(route_label, str) and route_label.strip()):
        route_label = resolve_shadow_export_route_label(snapshot.ticket_label)

    generated = bool(state.get("ai_assist_shadow_generated")) if assist_executed else False

    row: dict[str, Any] = {
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "route_label": route_label,
        "review_priority": priority,
        "assigned_department": assigned_department,
        "ai_assist_shadow_generated": generated,
        "ai_assist_suggested_priority": state.get("ai_assist_suggested_priority"),
        "ai_assist_escalation_recommended": state.get("ai_assist_escalation_recommended"),
        "ai_assist_duplicate_possible": state.get("ai_assist_duplicate_possible"),
        "ai_assist_suggested_action": state.get("ai_assist_suggested_action"),
        "ai_assist_suggested_action_reason": state.get("ai_assist_suggested_action_reason"),
        "ai_assist_confidence_band": state.get("ai_assist_confidence_band"),
        "ai_assist_human_review_required": (
            state.get("ai_assist_human_review_required")
            if state.get("ai_assist_human_review_required") is not None
            else True
        ),
        "ai_assist_shadow_only": (
            state.get("ai_assist_shadow_only")
            if state.get("ai_assist_shadow_only") is not None
            else True
        ),
        "seller_notification_detected": state.get("seller_notification_detected"),
        "seller_intent_type": state.get("seller_intent_type"),
        "seller_notification_type": state.get("seller_notification_type"),
        "seller_operational_request_type": state.get("seller_operational_request_type"),
        "extracted_order_id": state.get("extracted_order_id"),
        "extracted_order_ids": state.get("extracted_order_ids"),
        "extracted_tracking_code": state.get("extracted_tracking_code"),
        "extracted_product_ids": state.get("extracted_product_ids"),
        "extracted_tracking_carrier": state.get("extracted_tracking_carrier"),
        "entity_warnings_summary": state.get("entity_warnings_summary"),
        "seller_notification_shipment_status": state.get("seller_notification_shipment_status"),
        "detected_intent": state.get("detected_intent"),
        "intent_confidence_band": state.get("intent_confidence_band"),
        "intent_reasons_summary": state.get("intent_reasons_summary"),
        "intent_related_document_types": state.get("intent_related_document_types"),
        "downstream_consumed_retrieval": False,
        "errors": row_errors,
    }
    row.update(extract_hitl_retrieval_fields_from_source(state))
    row["retrieval_activated"] = False
    row["downstream_consumed_retrieval"] = False
    assert_ai_assist_shadow_replay_row_safe(row)
    return row


def _run_ai_assist_on_state(state: CommerceAIState) -> list[str]:
    """Evaluate shadow assist and write ai_assist_* fields; return row-level errors."""
    from app.state.ai_assist_state import build_sanitized_ai_assist_payload

    errors: list[str] = []
    try:
        payload = build_sanitized_ai_assist_payload(state)
        result = evaluate_vendor_ticket_ai_assist_shadow(payload)
        apply_ai_assist_result_to_state(state, result)
    except ValueError as exc:
        state["ai_assist_shadow_generated"] = False
        state["ai_assist_human_review_required"] = True
        state["ai_assist_shadow_only"] = True
        errors.append(f"ai_assist_shadow_rejected: {exc}")
    except Exception as exc:  # noqa: BLE001
        state["ai_assist_shadow_generated"] = False
        state["ai_assist_human_review_required"] = True
        state["ai_assist_shadow_only"] = True
        errors.append(f"ai_assist_shadow_error: {exc}")
    return errors


def export_ai_assist_shadow_replay_row_for_snapshot(
    snapshot: ConversationTicketSnapshot,
    export_config: ShadowReplayExportConfig,
    *,
    settings: AppSettings | None = None,
    run_chain: Callable[
        [CommerceAIState, SandboxRetrievalChainDryRunConfig, AppSettings],
        SandboxRetrievalChainDryRunResult,
    ]
    | None = None,
) -> dict[str, Any]:
    """Route, optional sandbox retrieval, optional AI assist; return sanitized export row."""
    settings = settings or get_settings()
    row_errors: list[str] = []

    retrieval_row = export_shadow_replay_row_for_snapshot(
        snapshot,
        export_config,
        settings=settings,
        run_chain=run_chain,
    )
    retrieval_errors = retrieval_row.get("errors")
    if isinstance(retrieval_errors, list):
        row_errors.extend(str(item) for item in retrieval_errors)

    state = build_initial_state_from_snapshot(snapshot)
    try:
        state = run_routing_pipeline(state)
        route_label = retrieval_row.get("route_label")
        if isinstance(route_label, str) and route_label.strip():
            state["route_label"] = route_label
        ticket_label = retrieval_row.get("ticket_label")
        if isinstance(ticket_label, str) and ticket_label.strip():
            state["ticket_label"] = ticket_label
        for key in (
            "retrieval_gate_decision",
            "retrieval_scenario",
            "retrieval_policy_reasons",
            "retrieval_query_hash",
            "retrieval_result_count",
            "retrieval_metadata_filter",
            "retrieval_sandbox_only",
        ):
            if key in retrieval_row:
                state[key] = retrieval_row[key]
        state["retrieval_activated"] = False
    except Exception as exc:  # noqa: BLE001
        row_errors.append(f"routing_error: {exc}")

    assist_executed = False
    if settings.vendor_ticket_ai_assist_shadow_enabled:
        try:
            open_snap = build_open_ticket_snapshot(snapshot)
            for key, value in open_ticket_snapshot_to_payload(open_snap).items():
                if key in ("latest_vendor_message", "original_vendor_issue_preview") and value:
                    state[key] = value
        except ValueError:
            pass
        assist_errors = _run_ai_assist_on_state(state)
        row_errors.extend(assist_errors)
        assist_executed = True
    else:
        row_errors.append(
            "ai_assist_shadow_skipped: VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=false",
        )

    row = build_ai_assist_shadow_replay_export_row(
        snapshot,
        state,
        assist_executed=assist_executed,
        export_errors=row_errors,
    )
    row = attach_ticket_text_preview_to_row(row, snapshot=snapshot)
    return attach_open_ticket_snapshot_to_row(row, snapshot=snapshot)


def export_ai_assist_shadow_replay_jsonl_content(
    lines: list[str],
    export_config: ShadowReplayExportConfig,
    *,
    settings: AppSettings | None = None,
    run_chain: Callable[
        [CommerceAIState, SandboxRetrievalChainDryRunConfig, AppSettings],
        SandboxRetrievalChainDryRunResult,
    ]
    | None = None,
) -> tuple[list[dict[str, Any]], AIAssistShadowReplayExportSummary]:
    """Process ticket export JSONL lines into sanitized AI assist shadow replay rows."""
    if not export_config.confirm_sandbox:
        raise ValueError("confirm_sandbox must be true for AI assist shadow replay export")

    settings = settings or get_settings()
    summary = AIAssistShadowReplayExportSummary()
    rows: list[dict[str, Any]] = []
    physical_line = 0

    for raw_line in lines:
        physical_line += 1
        if not raw_line.strip():
            summary.empty_lines_ignored += 1
            continue

        summary.total_lines += 1
        try:
            snapshot = parse_conversation_ticket_snapshot(raw_line)
        except json.JSONDecodeError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(
                    line_number=physical_line,
                    error_message=f"JSON decode error at column {exc.colno}: {exc.msg}",
                ),
            )
            continue
        except ValidationError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(
                    line_number=physical_line,
                    error_message=_format_validation_error(exc),
                ),
            )
            continue
        except ValueError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(line_number=physical_line, error_message=str(exc)),
            )
            continue

        summary.valid_tickets += 1
        summary.label_counts[snapshot.ticket_label] += 1

        try:
            row = export_ai_assist_shadow_replay_row_for_snapshot(
                snapshot,
                export_config,
                settings=settings,
                run_chain=run_chain,
            )
        except ValueError as exc:
            summary.export_failures += 1
            summary.export_errors.append(
                LineError(line_number=physical_line, error_message=str(exc)),
            )
            continue
        except Exception as exc:  # noqa: BLE001
            summary.export_failures += 1
            summary.export_errors.append(
                LineError(line_number=physical_line, error_message=str(exc)),
            )
            continue

        rows.append(row)
        summary.exported_rows += 1
        if row.get("ai_assist_shadow_generated"):
            summary.assist_generated_count += 1
        if not any(
            str(err).startswith("ai_assist_shadow_skipped:") for err in (row.get("errors") or [])
        ):
            summary.assist_executed_count += 1
        action = row.get("ai_assist_suggested_action")
        if isinstance(action, str) and action:
            summary.suggested_action_counts[action] += 1

    return rows, summary


def write_ai_assist_shadow_replay_jsonl(
    rows: list[dict[str, Any]],
    output_path: Path,
) -> None:
    """Write rows with per-line safety checks."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            assert_ai_assist_shadow_replay_row_safe(row)
            line = json.dumps(row, ensure_ascii=False) + "\n"
            assert_ai_assist_shadow_replay_jsonl_line_safe(line)
            handle.write(line)


def export_ai_assist_shadow_replay_jsonl_file(
    export_path: Path,
    output_path: Path,
    export_config: ShadowReplayExportConfig,
    *,
    settings: AppSettings | None = None,
    run_chain: Callable[
        [CommerceAIState, SandboxRetrievalChainDryRunConfig, AppSettings],
        SandboxRetrievalChainDryRunResult,
    ]
    | None = None,
) -> AIAssistShadowReplayExportSummary:
    """Read ticket JSONL, export AI assist shadow replay JSONL, validate dashboard-safe."""
    lines = export_path.read_text(encoding="utf-8").splitlines()
    rows, summary = export_ai_assist_shadow_replay_jsonl_content(
        lines,
        export_config,
        settings=settings,
        run_chain=run_chain,
    )
    write_ai_assist_shadow_replay_jsonl(rows, output_path)
    load_ai_assist_shadow_rows(output_path)
    return summary


def format_ai_assist_export_summary(
    summary: AIAssistShadowReplayExportSummary,
    *,
    export_path: str | None = None,
    output_path: str | None = None,
) -> str:
    lines: list[str] = ["ai_assist_shadow_replay_jsonl_export: complete"]
    if export_path:
        lines.append(f"  input={export_path}")
    if output_path:
        lines.append(f"  output={output_path}")
    lines.extend(
        [
            f"  total_lines={summary.total_lines}",
            f"  valid_tickets={summary.valid_tickets}",
            f"  exported_rows={summary.exported_rows}",
            f"  assist_executed_count={summary.assist_executed_count}",
            f"  assist_generated_count={summary.assist_generated_count}",
            f"  invalid_lines={summary.invalid_lines}",
            f"  export_failures={summary.export_failures}",
        ],
    )
    if summary.suggested_action_counts:
        lines.append("  suggested_action_counts:")
        for action, count in sorted(summary.suggested_action_counts.items()):
            lines.append(f"    {action}={count}")
    if summary.parse_errors:
        lines.append("  parse_errors:")
        for err in summary.parse_errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    if summary.export_errors:
        lines.append("  export_errors:")
        for err in summary.export_errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    return "\n".join(lines)


__all__ = [
    "AIAssistShadowReplayExportSummary",
    "configure_mock_workflow_runtime",
    "export_ai_assist_shadow_replay_jsonl_file",
    "export_ai_assist_shadow_replay_jsonl_content",
    "format_ai_assist_export_summary",
]
