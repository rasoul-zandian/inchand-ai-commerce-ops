"""Aggregate AI assist shadow metrics from sanitized replay JSONL (offline; no raw content)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.corpus_planning.ai_assist_shadow_replay_row_contract import (
    FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_KEYS,
    FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_SUBSTRINGS,
    assert_ai_assist_shadow_replay_row_safe,
)


def load_ai_assist_shadow_rows(path: Path) -> list[dict[str, Any]]:
    """Load sanitized AI assist shadow replay JSONL rows with safety validation."""
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8")
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON on line {line_number}: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: row must be a JSON object")
        assert_ai_assist_shadow_replay_row_safe(payload, line_number=line_number)
        rows.append(payload)
    return rows


def _safe_label(value: Any, *, default: str = "(none)") -> str:
    if value is None:
        return default
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(value)


def _row_has_error(row: dict[str, Any]) -> bool:
    errors = row.get("errors")
    if not isinstance(errors, list):
        return False
    return len(errors) > 0


@dataclass
class AIAssistShadowDashboardMetrics:
    total_rows: int = 0
    ai_assist_shadow_generated_count: int = 0
    suggested_priority_counts: Counter[str] = field(default_factory=Counter)
    escalation_recommended_count: int = 0
    duplicate_possible_count: int = 0
    suggested_action_counts: Counter[str] = field(default_factory=Counter)
    confidence_band_counts: Counter[str] = field(default_factory=Counter)
    error_count: int = 0
    label_action_matrix: dict[str, dict[str, int]] = field(default_factory=dict)
    label_priority_matrix: dict[str, dict[str, int]] = field(default_factory=dict)
    retrieval_activated_true_count: int = 0
    downstream_consumed_true_count: int = 0
    ai_assist_shadow_only_false_count: int = 0


def compute_ai_assist_shadow_metrics(rows: list[dict[str, Any]]) -> AIAssistShadowDashboardMetrics:
    """Aggregate metrics from validated AI assist shadow replay rows."""
    metrics = AIAssistShadowDashboardMetrics(total_rows=len(rows))
    label_action: dict[str, Counter[str]] = defaultdict(Counter)
    label_priority: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        if row.get("retrieval_activated") is True:
            metrics.retrieval_activated_true_count += 1
        if row.get("downstream_consumed_retrieval") is True:
            metrics.downstream_consumed_true_count += 1
        if row.get("ai_assist_shadow_only") is False:
            metrics.ai_assist_shadow_only_false_count += 1

        if bool(row.get("ai_assist_shadow_generated")):
            metrics.ai_assist_shadow_generated_count += 1

        if bool(row.get("ai_assist_escalation_recommended")):
            metrics.escalation_recommended_count += 1

        if bool(row.get("ai_assist_duplicate_possible")):
            metrics.duplicate_possible_count += 1

        priority = _safe_label(row.get("ai_assist_suggested_priority"), default="(none)")
        metrics.suggested_priority_counts[priority] += 1

        action = _safe_label(row.get("ai_assist_suggested_action"), default="(none)")
        metrics.suggested_action_counts[action] += 1

        band = _safe_label(row.get("ai_assist_confidence_band"), default="(none)")
        metrics.confidence_band_counts[band] += 1

        if _row_has_error(row):
            metrics.error_count += 1

        ticket_label = _safe_label(row.get("ticket_label"))
        label_action[ticket_label][action] += 1
        label_priority[ticket_label][priority] += 1

    for label, action_counts in sorted(label_action.items()):
        metrics.label_action_matrix[label] = dict(sorted(action_counts.items()))

    for label, priority_counts in sorted(label_priority.items()):
        metrics.label_priority_matrix[label] = dict(sorted(priority_counts.items()))

    return metrics


def _matrix_markdown(title: str, matrix: dict[str, dict[str, int]]) -> list[str]:
    if not matrix:
        return [f"### {title}", "", "*(no data)*", ""]
    col_headers = sorted({key for row in matrix.values() for key in row})
    header = "| Row | " + " | ".join(col_headers) + " |"
    sep = "|-----|" + "|".join("------:" for _ in col_headers) + "|"
    lines = [f"### {title}", "", header, sep]
    for row_name, counts in sorted(matrix.items()):
        cells = " | ".join(str(counts.get(col, 0)) for col in col_headers)
        lines.append(f"| {row_name} | {cells} |")
    lines.append("")
    return lines


def format_ai_assist_shadow_markdown(
    metrics: AIAssistShadowDashboardMetrics,
    *,
    source_path: str,
    generated_at: str,
) -> str:
    lines = [
        "# AI Assist Shadow Metrics Dashboard",
        "",
        f"**Generated:** {generated_at}  ",
        f"**Source:** `{source_path}`  ",
        "**Scope:** Offline aggregate metrics from sanitized AI assist shadow replay JSONL only.",
        "",
        "## Summary",
        "",
        f"- **total_rows:** {metrics.total_rows}",
        f"- **ai_assist_shadow_generated_count:** {metrics.ai_assist_shadow_generated_count}",
        f"- **escalation_recommended_count:** {metrics.escalation_recommended_count}",
        f"- **duplicate_possible_count:** {metrics.duplicate_possible_count}",
        f"- **error_count:** {metrics.error_count}",
        f"- **retrieval_activated_true_count:** {metrics.retrieval_activated_true_count} "
        "(must be 0)",
        f"- **downstream_consumed_retrieval_true_count:** "
        f"{metrics.downstream_consumed_true_count} (must be 0)",
        "",
        "## Suggested priority counts",
        "",
        "| Priority | Count |",
        "|----------|------:|",
    ]
    for priority, count in metrics.suggested_priority_counts.most_common():
        lines.append(f"| {priority} | {count} |")
    lines.extend(
        [
            "",
            "## Suggested action counts",
            "",
            "| Action | Count |",
            "|--------|------:|",
        ],
    )
    for action, count in metrics.suggested_action_counts.most_common():
        lines.append(f"| {action} | {count} |")
    lines.extend(
        [
            "",
            "## Confidence band counts",
            "",
            "| Band | Count |",
            "|------|------:|",
        ],
    )
    for band, count in metrics.confidence_band_counts.most_common():
        lines.append(f"| {band} | {count} |")
    lines.extend(_matrix_markdown("Label × suggested action", metrics.label_action_matrix))
    lines.extend(_matrix_markdown("Label × suggested priority", metrics.label_priority_matrix))
    lines.extend(
        [
            "## Governance",
            "",
            "- Input JSONL is produced by `scripts/export_ai_assist_shadow_replay_jsonl.py` "
            "(Step 147; gitignored).",
            "- Rows must not contain raw messages, draft/final responses, retrieval hits, "
            "or vectors.",
            "- `retrieval_activated=true`, `downstream_consumed_retrieval=true`, and "
            "`ai_assist_shadow_only=false` are rejected at load time.",
            "- Default `VENDOR_TICKET_AI_ASSIST_SHADOW_ENABLED=false`; "
            "no HITL UI or downstream consumption.",
            "",
        ],
    )
    return "\n".join(lines)


def metrics_to_json_dict(
    metrics: AIAssistShadowDashboardMetrics,
    *,
    source_path: str,
    generated_at: str,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "source_path": source_path,
        "total_rows": metrics.total_rows,
        "ai_assist_shadow_generated_count": metrics.ai_assist_shadow_generated_count,
        "suggested_priority_counts": dict(metrics.suggested_priority_counts),
        "escalation_recommended_count": metrics.escalation_recommended_count,
        "duplicate_possible_count": metrics.duplicate_possible_count,
        "suggested_action_counts": dict(metrics.suggested_action_counts),
        "confidence_band_counts": dict(metrics.confidence_band_counts),
        "error_count": metrics.error_count,
        "label_action_matrix": metrics.label_action_matrix,
        "label_priority_matrix": metrics.label_priority_matrix,
        "retrieval_activated_true_count": metrics.retrieval_activated_true_count,
        "downstream_consumed_true_count": metrics.downstream_consumed_true_count,
        "ai_assist_shadow_only_false_count": metrics.ai_assist_shadow_only_false_count,
    }


def assert_dashboard_output_safe(content: str) -> None:
    lowered = content.lower()
    for key in FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_KEYS:
        if f'"{key}"' in content:
            raise ValueError(f"dashboard output must not reference forbidden key: {key}")
    for token in FORBIDDEN_AI_ASSIST_SHADOW_REPLAY_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"dashboard output must not contain forbidden token: {token}")


def build_ai_assist_shadow_dashboard(
    report_path: Path,
    *,
    markdown_output: Path,
    json_output: Path | None = None,
    generated_at: str | None = None,
) -> AIAssistShadowDashboardMetrics:
    from datetime import UTC, datetime

    rows = load_ai_assist_shadow_rows(report_path)
    metrics = compute_ai_assist_shadow_metrics(rows)

    if (
        metrics.retrieval_activated_true_count
        or metrics.downstream_consumed_true_count
        or metrics.ai_assist_shadow_only_false_count
    ):
        raise ValueError("aggregated metrics contain forbidden governance violations")

    ts = generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = str(report_path)

    markdown = format_ai_assist_shadow_markdown(metrics, source_path=source, generated_at=ts)
    assert_dashboard_output_safe(markdown)

    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(markdown, encoding="utf-8")

    if json_output is not None:
        payload = metrics_to_json_dict(metrics, source_path=source, generated_at=ts)
        json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        assert_dashboard_output_safe(json_text)
        json_output.write_text(json_text, encoding="utf-8")

    return metrics
