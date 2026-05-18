#!/usr/bin/env python3
"""Build offline Markdown/JSON dashboard from replay report JSONL (no raw content)."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.replay_ticket_export import is_label_department_mismatch

_FORBIDDEN_CONTENT_KEYS = frozenset(
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
        "text",
        "content",
    }
)
_FORBIDDEN_SUBSTRINGS = (
    "sk-",
    "api_key",
    "BEGIN PRIVATE KEY",
    "postgresql://",
    "OPENAI_API_KEY",
)
_PRIORITY_LEVELS = ("HIGH", "MEDIUM", "LOW")
_MAX_MISMATCH_EXAMPLES = 10


@dataclass
class MismatchExample:
    room_id: str
    ticket_label: str
    assigned_department: str


@dataclass
class ReplayDashboardMetrics:
    total_rows: int = 0
    parse_error_count: int = 0
    workflow_success_count: int = 0
    failed_replay_count: int = 0
    human_approval_required_count: int = 0
    ticket_label_counts: Counter[str] = field(default_factory=Counter)
    assigned_department_counts: Counter[str] = field(default_factory=Counter)
    review_priority_counts: Counter[str] = field(default_factory=Counter)
    route_label_counts: Counter[str] = field(default_factory=Counter)
    detected_intent_counts: Counter[str] = field(default_factory=Counter)
    reviewer_role_counts: Counter[str] = field(default_factory=Counter)
    qa_passed_count: int = 0
    qa_failed_count: int = 0
    qa_attention_count: int = 0
    total_qa_issue_count: int = 0
    total_qa_warning_count: int = 0
    label_vs_department_mismatch_count: int = 0
    mismatch_examples: list[MismatchExample] = field(default_factory=list)
    high_priority_count: int = 0
    medium_priority_count: int = 0
    low_priority_count: int = 0
    department_priority_matrix: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def qa_attention_rate(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return self.qa_attention_count / self.total_rows

    @property
    def mismatch_rate(self) -> float:
        if self.total_rows == 0:
            return 0.0
        return self.label_vs_department_mismatch_count / self.total_rows


def _safe_str(value: Any, *, default: str = "unknown") -> str:
    if value is None:
        return default
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(value)


def _row_failed(row: dict[str, Any]) -> bool:
    errors = row.get("errors")
    return bool(errors)


def _row_qa_attention(row: dict[str, Any]) -> bool:
    issues = row.get("qa_issue_count") or 0
    warnings = row.get("qa_warning_count") or 0
    if issues or warnings:
        return True
    if row.get("qa_passed") is False:
        return True
    return False


def load_replay_report_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Load replay JSONL rows; return (rows, parse_error_count)."""
    rows: list[dict[str, Any]] = []
    parse_errors = 0
    text = path.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            parse_errors += 1
            raise ValueError(f"invalid JSON on line {line_number}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            parse_errors += 1
            raise ValueError(f"line {line_number}: replay row must be a JSON object")
        for forbidden in _FORBIDDEN_CONTENT_KEYS:
            if forbidden in payload:
                raise ValueError(f"line {line_number}: forbidden key {forbidden!r} in report")
        rows.append(payload)
    return rows, parse_errors


def compute_replay_dashboard_metrics(rows: list[dict[str, Any]]) -> ReplayDashboardMetrics:
    """Aggregate compact metrics from replay report rows."""
    metrics = ReplayDashboardMetrics(total_rows=len(rows))
    matrix: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        if _row_failed(row):
            metrics.failed_replay_count += 1
        else:
            metrics.workflow_success_count += 1

        if bool(row.get("human_approval_required")):
            metrics.human_approval_required_count += 1

        label = _safe_str(row.get("ticket_label"), default="(none)")
        dept = _safe_str(row.get("assigned_department"), default="(none)")
        priority = _safe_str(row.get("review_priority"), default="(none)").upper()
        route = _safe_str(row.get("route_label"), default="(none)")
        intent = _safe_str(row.get("detected_intent"), default="(none)")
        role = _safe_str(row.get("reviewer_role"), default="(none)")

        metrics.ticket_label_counts[label] += 1
        metrics.assigned_department_counts[dept] += 1
        metrics.review_priority_counts[priority] += 1
        metrics.route_label_counts[route] += 1
        metrics.detected_intent_counts[intent] += 1
        metrics.reviewer_role_counts[role] += 1

        if priority == "HIGH":
            metrics.high_priority_count += 1
        elif priority == "MEDIUM":
            metrics.medium_priority_count += 1
        elif priority == "LOW":
            metrics.low_priority_count += 1

        if priority in _PRIORITY_LEVELS:
            matrix[dept][priority] += 1

        qa_passed = row.get("qa_passed")
        if qa_passed is True:
            metrics.qa_passed_count += 1
        elif qa_passed is False:
            metrics.qa_failed_count += 1

        metrics.total_qa_issue_count += int(row.get("qa_issue_count") or 0)
        metrics.total_qa_warning_count += int(row.get("qa_warning_count") or 0)

        if _row_qa_attention(row):
            metrics.qa_attention_count += 1

        ticket_label_raw = row.get("ticket_label")
        assigned_raw = row.get("assigned_department")
        label_str = ticket_label_raw if isinstance(ticket_label_raw, str) else None
        assigned_str = assigned_raw if isinstance(assigned_raw, str) else None
        if is_label_department_mismatch(label_str, assigned_str):
            metrics.label_vs_department_mismatch_count += 1
            if len(metrics.mismatch_examples) < _MAX_MISMATCH_EXAMPLES:
                metrics.mismatch_examples.append(
                    MismatchExample(
                        room_id=_safe_str(row.get("room_id"), default="(unknown)"),
                        ticket_label=label_str or "(none)",
                        assigned_department=assigned_str or "(none)",
                    )
                )

    for dept, pri_counts in sorted(matrix.items()):
        metrics.department_priority_matrix[dept] = {
            level: pri_counts.get(level, 0) for level in _PRIORITY_LEVELS
        }

    return metrics


def _counter_table(title: str, counts: Counter[str]) -> list[str]:
    lines = [f"### {title}", "", "| Value | Count |", "|-------|------:|"]
    if not counts:
        lines.append("| *(none)* | 0 |")
    else:
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"| {key} | {count} |")
    lines.append("")
    return lines


def _dominant_keys(counts: Counter[str], *, limit: int = 3) -> str:
    if not counts:
        return "none"
    top = counts.most_common(limit)
    return ", ".join(f"{key} ({count})" for key, count in top)


def format_markdown_dashboard(
    metrics: ReplayDashboardMetrics,
    *,
    source_path: str,
    generated_at: str,
) -> str:
    """Render Markdown dashboard (no raw ticket content)."""
    lines: list[str] = [
        "# Replay Metrics Dashboard",
        "",
        "## Source",
        "",
        f"- **Report:** `{source_path}`",
        f"- **Generated at:** {generated_at} (UTC)",
        "- **Scope:** local/offline artifact — do not commit if based on real private data",
        "",
        "## Executive Summary",
        "",
        f"- **Total tickets replayed:** {metrics.total_rows}",
        f"- **Workflow successes:** {metrics.workflow_success_count}",
        f"- **Failed replays:** {metrics.failed_replay_count}",
        (
            f"- **Label vs department mismatches:** "
            f"{metrics.label_vs_department_mismatch_count} "
            f"({metrics.mismatch_rate:.1%})"
        ),
        (f"- **QA attention:** {metrics.qa_attention_count} ({metrics.qa_attention_rate:.1%})"),
        f"- **Dominant departments:** {_dominant_keys(metrics.assigned_department_counts)}",
        (
            f"- **Priority mix:** HIGH={metrics.high_priority_count}, "
            f"MEDIUM={metrics.medium_priority_count}, "
            f"LOW={metrics.low_priority_count}"
        ),
        "",
        "## Distributions",
        "",
    ]
    lines.extend(_counter_table("Ticket labels", metrics.ticket_label_counts))
    lines.extend(_counter_table("Assigned departments", metrics.assigned_department_counts))
    lines.extend(_counter_table("Review priorities", metrics.review_priority_counts))
    lines.extend(_counter_table("Route labels", metrics.route_label_counts))
    lines.extend(_counter_table("Detected intents", metrics.detected_intent_counts))
    lines.extend(_counter_table("Reviewer roles", metrics.reviewer_role_counts))

    lines.extend(
        [
            "## QA Summary",
            "",
            f"- **qa_passed_count:** {metrics.qa_passed_count}",
            f"- **qa_failed_count:** {metrics.qa_failed_count}",
            f"- **qa_attention_count:** {metrics.qa_attention_count}",
            f"- **qa_attention_rate:** {metrics.qa_attention_rate:.1%}",
            f"- **total_qa_issue_count:** {metrics.total_qa_issue_count}",
            f"- **total_qa_warning_count:** {metrics.total_qa_warning_count}",
            "",
            "## Department × Priority Matrix",
            "",
            "| Department | HIGH | MEDIUM | LOW |",
            "|------------|-----:|-------:|----:|",
        ]
    )
    if not metrics.department_priority_matrix:
        lines.append("| *(none)* | 0 | 0 | 0 |")
    else:
        for dept in sorted(metrics.department_priority_matrix):
            row = metrics.department_priority_matrix[dept]
            lines.append(
                f"| {dept} | {row.get('HIGH', 0)} | {row.get('MEDIUM', 0)} | {row.get('LOW', 0)} |"
            )
    lines.extend(
        [
            "",
            "## Mismatch Analysis",
            "",
            (
                "- **label_vs_department_mismatch_count:** "
                f"{metrics.label_vs_department_mismatch_count}"
            ),
            f"- **mismatch_rate:** {metrics.mismatch_rate:.1%}",
            "",
        ]
    )
    if metrics.mismatch_examples:
        lines.extend(
            [
                "| room_id | ticket_label | assigned_department |",
                "|---------|--------------|---------------------|",
            ]
        )
        for example in metrics.mismatch_examples:
            lines.append(
                f"| {example.room_id} | {example.ticket_label} | {example.assigned_department} |"
            )
    else:
        lines.append("_No mismatches observed._")
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- No raw message text, transcripts, drafts, or retrieval payloads are included.",
            (
                "- This dashboard is for **observation only**; "
                "it does not change routing or workflow behavior."
            ),
            "- Re-run after routing calibration to compare before/after metrics.",
            "",
        ]
    )
    return "\n".join(lines)


def metrics_to_json_dict(
    metrics: ReplayDashboardMetrics,
    *,
    source_path: str,
    generated_at: str,
) -> dict[str, Any]:
    """Machine-readable summary without raw content."""
    return {
        "source_path": source_path,
        "generated_at": generated_at,
        "total_rows": metrics.total_rows,
        "parse_error_count": metrics.parse_error_count,
        "workflow_success_count": metrics.workflow_success_count,
        "failed_replay_count": metrics.failed_replay_count,
        "human_approval_required_count": metrics.human_approval_required_count,
        "ticket_label_counts": dict(metrics.ticket_label_counts),
        "assigned_department_counts": dict(metrics.assigned_department_counts),
        "review_priority_counts": dict(metrics.review_priority_counts),
        "route_label_counts": dict(metrics.route_label_counts),
        "detected_intent_counts": dict(metrics.detected_intent_counts),
        "reviewer_role_counts": dict(metrics.reviewer_role_counts),
        "qa_passed_count": metrics.qa_passed_count,
        "qa_failed_count": metrics.qa_failed_count,
        "qa_attention_count": metrics.qa_attention_count,
        "qa_attention_rate": round(metrics.qa_attention_rate, 4),
        "total_qa_issue_count": metrics.total_qa_issue_count,
        "total_qa_warning_count": metrics.total_qa_warning_count,
        "label_vs_department_mismatch_count": metrics.label_vs_department_mismatch_count,
        "mismatch_rate": round(metrics.mismatch_rate, 4),
        "mismatch_examples": [
            {
                "room_id": ex.room_id,
                "ticket_label": ex.ticket_label,
                "assigned_department": ex.assigned_department,
            }
            for ex in metrics.mismatch_examples
        ],
        "high_priority_count": metrics.high_priority_count,
        "medium_priority_count": metrics.medium_priority_count,
        "low_priority_count": metrics.low_priority_count,
        "department_priority_matrix": metrics.department_priority_matrix,
    }


def assert_dashboard_output_safe(content: str) -> None:
    """Reject outputs that accidentally embed forbidden keys or secret-like tokens."""
    lowered = content.lower()
    for key in _FORBIDDEN_CONTENT_KEYS:
        if f'"{key}"' in content or f"'{key}'" in content:
            raise ValueError(f"dashboard output must not reference forbidden key: {key}")
    for token in _FORBIDDEN_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"dashboard output must not contain forbidden token: {token}")


def build_dashboard(
    report_path: Path,
    *,
    markdown_output: Path,
    json_output: Path | None = None,
) -> ReplayDashboardMetrics:
    """Read replay JSONL and write Markdown (and optional JSON) dashboard."""
    rows, parse_errors = load_replay_report_rows(report_path)
    metrics = compute_replay_dashboard_metrics(rows)
    metrics.parse_error_count = parse_errors

    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = str(report_path)

    markdown = format_markdown_dashboard(
        metrics,
        source_path=source,
        generated_at=generated_at,
    )
    assert_dashboard_output_safe(markdown)

    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(markdown, encoding="utf-8")

    if json_output is not None:
        payload = metrics_to_json_dict(
            metrics,
            source_path=source,
            generated_at=generated_at,
        )
        json_text = json.dumps(payload, ensure_ascii=False, indent=2)
        assert_dashboard_output_safe(json_text)
        json_output.write_text(json_text, encoding="utf-8")

    return metrics


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build offline Markdown dashboard from replay report JSONL.",
    )
    parser.add_argument("report_path", type=Path, help="Path to replay report JSONL")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        required=True,
        help="Path to write Markdown dashboard (local artifact; do not commit real data)",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write JSON metrics summary",
    )
    args = parser.parse_args(argv)

    if not args.report_path.is_file():
        print(f"replay dashboard: file not found: {args.report_path}", file=sys.stderr)
        return 1

    try:
        metrics = build_dashboard(
            args.report_path,
            markdown_output=args.output,
            json_output=args.json_output,
        )
    except ValueError as exc:
        print(f"replay dashboard: {exc}", file=sys.stderr)
        return 1

    print(f"replay dashboard: wrote {args.output}")
    if args.json_output:
        print(f"replay dashboard: wrote {args.json_output}")
    print(f"  total_rows={metrics.total_rows}")
    print(f"  failed_replays={metrics.failed_replay_count}")
    print(f"  mismatch_count={metrics.label_vs_department_mismatch_count}")
    print(f"  qa_attention_count={metrics.qa_attention_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
