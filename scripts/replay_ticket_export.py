#!/usr/bin/env python3
"""Offline replay: validate JSONL exports, run mock vendor-ticket workflow, write JSONL report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.vendor_ticket import build_review_queue_metadata
from app.state.commerce_state import CommerceAIState
from app.tickets.conversation_models import (
    ConversationTicketSnapshot,
    parse_conversation_ticket_snapshot,
)
from app.tickets.workflow_mapping import conversation_snapshot_to_workflow_input
from pydantic import ValidationError

_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "draft_response",
        "final_response",
        "user_input",
        "retrieved_context",
        "tool_results",
        "conversation_transcript",
        "messages",
        "specialist_output",
        "rag_sources",
        "grounding_sources",
        "audit_log",
    }
)

_FINANCE_LABEL_TOKENS = (
    "financial",
    "finance",
    "billing",
    "مالی",
    "تسویه",
    "invoice",
    "settlement",
)
_COMPLAINT_LABEL_TOKENS = ("complaint", "شکایت", "اعتراض")
_SUPPORT_LABEL_TOKENS = ("support", "پشتیبانی", "escalation", "ارجاع")

_MAX_MISMATCH_EXAMPLES = 5


@dataclass
class LineError:
    line_number: int
    error_message: str


@dataclass
class LabelDepartmentMismatch:
    room_id: str
    ticket_label: str
    assigned_department: str


@dataclass
class ReplaySummary:
    total_lines: int = 0
    empty_lines_ignored: int = 0
    valid_tickets: int = 0
    replayed_tickets: int = 0
    failed_replays: int = 0
    invalid_lines: int = 0
    label_counts: Counter[str] = field(default_factory=Counter)
    route_label_counts: Counter[str] = field(default_factory=Counter)
    review_priority_counts: Counter[str] = field(default_factory=Counter)
    assigned_department_counts: Counter[str] = field(default_factory=Counter)
    qa_attention_count: int = 0
    label_vs_department_mismatch_count: int = 0
    parse_errors: list[LineError] = field(default_factory=list)
    replay_errors: list[LineError] = field(default_factory=list)
    mismatch_examples: list[LabelDepartmentMismatch] = field(default_factory=list)


def _configure_mock_runtime() -> None:
    """Force offline mock providers (no OpenAI/Postgres)."""
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("LLM_MODEL", "mock-vendor-ticket-drafter")
    os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
    os.environ.setdefault("EMBEDDING_MODEL", "mock-embedding-small")
    os.environ.setdefault("RAG_STRATEGY", "mock")
    os.environ.setdefault("RAG_PROFILE", "")
    os.environ.setdefault("LANGSMITH_TRACING", "false")
    from app.config import get_settings

    get_settings.cache_clear()


def expected_department_from_ticket_label(ticket_label: str | None) -> str | None:
    """Map room topic label to finance/support/complaint; None if unknown/general."""
    norm = (ticket_label or "").strip().lower()
    if not norm:
        return None
    if any(token in norm for token in _FINANCE_LABEL_TOKENS):
        return "finance"
    if any(token in norm for token in _COMPLAINT_LABEL_TOKENS):
        return "complaint"
    if any(token in norm for token in _SUPPORT_LABEL_TOKENS):
        return "support"
    return None


def is_label_department_mismatch(
    ticket_label: str | None,
    assigned_department: str | None,
) -> bool:
    expected = expected_department_from_ticket_label(ticket_label)
    if expected is None or not assigned_department:
        return False
    return assigned_department != expected


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def build_replay_report_row(
    snapshot: ConversationTicketSnapshot,
    state: CommerceAIState | dict[str, Any],
    *,
    errors: list[str] | None = None,
) -> dict[str, Any]:
    """Compact per-ticket report row (no draft/transcript/raw text)."""
    row_errors = list(errors or [])
    data = dict(state)
    review_meta: dict[str, Any] = {}
    if not row_errors:
        try:
            review_meta = build_review_queue_metadata(data)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — observation harness must not abort
            row_errors.append(f"review_metadata_error: {exc}")

    department_route = review_meta.get("department_route") or {}
    assigned_department = department_route.get("assigned_department")
    reviewer_role = department_route.get("reviewer_role")

    workflow_meta = conversation_snapshot_to_workflow_input(snapshot)["workflow_metadata"]
    row: dict[str, Any] = {
        "room_id": snapshot.room_id,
        "ticket_label": snapshot.ticket_label,
        "ticket_subtype": snapshot.ticket_subtype,
        "status": snapshot.status,
        "message_count": workflow_meta["message_count"],
        "sender_types": workflow_meta["sender_types"],
        "workflow_status": _enum_value(data.get("workflow_status")),
        "approval_status": _enum_value(data.get("approval_status")),
        "human_approval_required": bool(data.get("human_approval_required")),
        "detected_intent": data.get("detected_intent"),
        "route_label": data.get("route_label"),
        "review_category": review_meta.get("review_category"),
        "review_priority": review_meta.get("review_priority"),
        "assigned_department": assigned_department,
        "reviewer_role": reviewer_role,
        "qa_passed": data.get("qa_passed"),
        "qa_issue_count": len(data.get("qa_issues") or []),
        "qa_warning_count": len(data.get("qa_warnings") or []),
        "errors": row_errors,
    }
    _assert_report_row_safe(row)
    return row


def _assert_report_row_safe(row: dict[str, Any]) -> None:
    """Guard against accidental inclusion of sensitive keys (dev/test aid)."""
    for key in row:
        if key in _FORBIDDEN_REPORT_KEYS:
            raise ValueError(f"report row must not include forbidden key: {key}")


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err.get("loc", ()))
        msg = str(err.get("msg", "validation error"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "validation error"


def _run_workflow_for_snapshot(
    snapshot: ConversationTicketSnapshot,
    run_workflow: Callable[..., CommerceAIState],
) -> CommerceAIState:
    workflow_input = conversation_snapshot_to_workflow_input(snapshot)
    return run_workflow(
        workflow_input["user_input"],
        ticket_id=snapshot.room_id,
        room_id=workflow_input.get("room_id"),
        ticket_label=workflow_input.get("ticket_label"),
        ticket_subtype=workflow_input.get("ticket_subtype"),
        workflow_state_snapshot=workflow_input.get("workflow_state_snapshot"),
    )


def replay_jsonl_content(
    lines: list[str],
    *,
    run_workflow: Callable[..., CommerceAIState] | None = None,
) -> tuple[list[dict[str, Any]], ReplaySummary]:
    """Replay each valid JSONL line; return report rows and aggregate summary."""
    runner = run_workflow or run_vendor_ticket_demo
    summary = ReplaySummary()
    report_rows: list[dict[str, Any]] = []
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
                )
            )
            continue
        except ValidationError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(
                    line_number=physical_line,
                    error_message=_format_validation_error(exc),
                )
            )
            continue
        except ValueError as exc:
            summary.invalid_lines += 1
            summary.parse_errors.append(
                LineError(line_number=physical_line, error_message=str(exc))
            )
            continue

        summary.valid_tickets += 1
        summary.label_counts[snapshot.ticket_label] += 1

        try:
            state = _run_workflow_for_snapshot(snapshot, runner)
            row = build_replay_report_row(snapshot, state)
            summary.replayed_tickets += 1
        except Exception as exc:  # noqa: BLE001 — continue replay for remaining tickets
            summary.failed_replays += 1
            summary.replay_errors.append(
                LineError(line_number=physical_line, error_message=str(exc))
            )
            row = build_replay_report_row(
                snapshot,
                {},
                errors=[f"workflow_error: {exc}"],
            )

        report_rows.append(row)

        route_label = row.get("route_label")
        if isinstance(route_label, str) and route_label:
            summary.route_label_counts[route_label] += 1

        review_priority = row.get("review_priority")
        if isinstance(review_priority, str) and review_priority:
            summary.review_priority_counts[review_priority] += 1

        assigned = row.get("assigned_department")
        if isinstance(assigned, str) and assigned:
            summary.assigned_department_counts[assigned] += 1

        qa_issues = row.get("qa_issue_count") or 0
        qa_warnings = row.get("qa_warning_count") or 0
        if qa_issues or qa_warnings or row.get("qa_passed") is False:
            summary.qa_attention_count += 1

        assigned_dept = assigned if isinstance(assigned, str) else None
        if is_label_department_mismatch(snapshot.ticket_label, assigned_dept):
            summary.label_vs_department_mismatch_count += 1
            if len(summary.mismatch_examples) < _MAX_MISMATCH_EXAMPLES and isinstance(
                assigned, str
            ):
                summary.mismatch_examples.append(
                    LabelDepartmentMismatch(
                        room_id=snapshot.room_id,
                        ticket_label=snapshot.ticket_label,
                        assigned_department=assigned,
                    )
                )

    return report_rows, summary


def replay_jsonl_file(
    export_path: Path,
    output_path: Path,
    *,
    run_workflow: Callable[..., CommerceAIState] | None = None,
) -> ReplaySummary:
    """Read export JSONL, replay tickets, write report JSONL."""
    lines = export_path.read_text(encoding="utf-8").splitlines()
    report_rows, summary = replay_jsonl_content(lines, run_workflow=run_workflow)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in report_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return summary


def format_human_summary(summary: ReplaySummary, *, export_path: str | None = None) -> str:
    lines: list[str] = []
    if export_path:
        lines.append(f"ticket export replay: {export_path}")
    lines.append(f"  total_lines={summary.total_lines}")
    lines.append(f"  empty_lines_ignored={summary.empty_lines_ignored}")
    lines.append(f"  valid_tickets={summary.valid_tickets}")
    lines.append(f"  replayed_tickets={summary.replayed_tickets}")
    lines.append(f"  failed_replays={summary.failed_replays}")
    lines.append(f"  invalid_lines={summary.invalid_lines}")
    lines.append(f"  qa_attention_count={summary.qa_attention_count}")
    lines.append(
        f"  label_vs_department_mismatch_count={summary.label_vs_department_mismatch_count}"
    )
    if summary.label_counts:
        lines.append("  ticket_label_counts:")
        for label, count in sorted(summary.label_counts.items()):
            lines.append(f"    {label}={count}")
    if summary.route_label_counts:
        lines.append("  route_label_counts:")
        for route, count in sorted(summary.route_label_counts.items()):
            lines.append(f"    {route}={count}")
    if summary.review_priority_counts:
        lines.append("  review_priority_counts:")
        for priority, count in sorted(summary.review_priority_counts.items()):
            lines.append(f"    {priority}={count}")
    if summary.assigned_department_counts:
        lines.append("  assigned_department_counts:")
        for dept, count in sorted(summary.assigned_department_counts.items()):
            lines.append(f"    {dept}={count}")
    if summary.mismatch_examples:
        lines.append("  label_vs_department_mismatch_examples:")
        for example in summary.mismatch_examples:
            lines.append(
                f"    room_id={example.room_id} "
                f"ticket_label={example.ticket_label} "
                f"assigned_department={example.assigned_department}"
            )
    if summary.parse_errors:
        lines.append("  parse_errors:")
        for err in summary.parse_errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    if summary.replay_errors:
        lines.append("  replay_errors:")
        for err in summary.replay_errors:
            lines.append(f"    line {err.line_number}: {err.error_message}")
    return "\n".join(lines)


def format_json_summary(summary: ReplaySummary, *, export_path: str | None = None) -> str:
    payload: dict[str, Any] = {
        "export_path": export_path,
        "total_lines": summary.total_lines,
        "empty_lines_ignored": summary.empty_lines_ignored,
        "valid_tickets": summary.valid_tickets,
        "replayed_tickets": summary.replayed_tickets,
        "failed_replays": summary.failed_replays,
        "invalid_lines": summary.invalid_lines,
        "qa_attention_count": summary.qa_attention_count,
        "label_vs_department_mismatch_count": summary.label_vs_department_mismatch_count,
        "ticket_label_counts": dict(summary.label_counts),
        "route_label_counts": dict(summary.route_label_counts),
        "review_priority_counts": dict(summary.review_priority_counts),
        "assigned_department_counts": dict(summary.assigned_department_counts),
        "label_vs_department_mismatch_examples": [
            {
                "room_id": ex.room_id,
                "ticket_label": ex.ticket_label,
                "assigned_department": ex.assigned_department,
            }
            for ex in summary.mismatch_examples
        ],
        "parse_errors": [
            {"line_number": err.line_number, "error_message": err.error_message}
            for err in summary.parse_errors
        ],
        "replay_errors": [
            {"line_number": err.line_number, "error_message": err.error_message}
            for err in summary.replay_errors
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Replay anonymized ticket JSONL through mock vendor-ticket workflow.",
    )
    parser.add_argument("export_path", type=Path, help="Path to UTF-8 JSONL export file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Path to write JSONL replay report (local artifact; do not commit)",
    )
    parser.add_argument(
        "--summary-json",
        action="store_true",
        help="Print machine-readable JSON summary to stdout",
    )
    args = parser.parse_args(argv)

    if not args.export_path.is_file():
        print(f"ticket export replay: file not found: {args.export_path}", file=sys.stderr)
        return 1

    _configure_mock_runtime()
    summary = replay_jsonl_file(args.export_path, args.output)
    human = format_human_summary(summary, export_path=str(args.export_path))
    print(human)
    if args.summary_json:
        print(format_json_summary(summary, export_path=str(args.export_path)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
