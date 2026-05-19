"""Aggregate shadow retrieval metrics from sanitized replay JSONL (offline; no raw content)."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.corpus_planning.shadow_replay_row_contract import (
    FORBIDDEN_SHADOW_REPLAY_KEYS,
    FORBIDDEN_SHADOW_REPLAY_SUBSTRINGS,
    assert_shadow_replay_row_safe,
)

_GATE_DECISIONS = ("allow", "skip", "deny")


def load_shadow_retrieval_rows(path: Path) -> list[dict[str, Any]]:
    """Load sanitized shadow replay JSONL rows with safety validation."""
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
        assert_shadow_replay_row_safe(payload, line_number=line_number)
        rows.append(payload)
    return rows


def _safe_label(value: Any, *, default: str = "(none)") -> str:
    if value is None:
        return default
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(value)


def _row_ticket_label(row: dict[str, Any]) -> str:
    label = row.get("ticket_label")
    if isinstance(label, str) and label.strip():
        return label.strip()
    metadata = row.get("retrieval_metadata_filter")
    if isinstance(metadata, dict):
        ticket = metadata.get("ticket_label")
        if isinstance(ticket, str) and ticket.strip():
            return ticket.strip()
    return "(none)"


def _row_has_retrieval_error(row: dict[str, Any]) -> bool:
    if bool(row.get("retrieval_error")):
        return True
    reasons = row.get("retrieval_policy_reasons")
    if not isinstance(reasons, list):
        return False
    for item in reasons:
        text = str(item).lower()
        if "error" in text and ("shadow" in text or "retrieval" in text):
            return True
    return False


@dataclass
class ShadowRetrievalDashboardMetrics:
    total_rows: int = 0
    shadow_node_executed_count: int = 0
    gate_decision_counts: Counter[str] = field(default_factory=Counter)
    scenario_counts: Counter[str] = field(default_factory=Counter)
    result_count_distribution: Counter[str] = field(default_factory=Counter)
    retrieval_error_count: int = 0
    retrieval_activated_true_count: int = 0
    downstream_consumed_true_count: int = 0
    label_gate_matrix: dict[str, dict[str, int]] = field(default_factory=dict)
    route_scenario_matrix: dict[str, dict[str, int]] = field(default_factory=dict)


def compute_shadow_retrieval_metrics(rows: list[dict[str, Any]]) -> ShadowRetrievalDashboardMetrics:
    """Aggregate metrics from validated shadow replay rows."""
    metrics = ShadowRetrievalDashboardMetrics(total_rows=len(rows))
    label_gate: dict[str, Counter[str]] = defaultdict(Counter)
    route_scenario: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        if row.get("retrieval_activated") is True:
            metrics.retrieval_activated_true_count += 1
        if row.get("downstream_consumed_retrieval") is True:
            metrics.downstream_consumed_true_count += 1

        if bool(row.get("shadow_node_executed")):
            metrics.shadow_node_executed_count += 1

        gate = _safe_label(row.get("retrieval_gate_decision"), default="(none)")
        metrics.gate_decision_counts[gate] += 1

        scenario = _safe_label(row.get("retrieval_scenario"), default="(none)")
        metrics.scenario_counts[scenario] += 1

        result_raw = row.get("retrieval_result_count")
        if result_raw is None:
            metrics.result_count_distribution["(null)"] += 1
        else:
            metrics.result_count_distribution[str(int(result_raw))] += 1

        if _row_has_retrieval_error(row):
            metrics.retrieval_error_count += 1

        ticket_label = _row_ticket_label(row)
        label_gate[ticket_label][gate] += 1

        route = _safe_label(row.get("route_label"), default="(none)")
        route_scenario[route][scenario] += 1

    for label, gate_counts in sorted(label_gate.items()):
        metrics.label_gate_matrix[label] = {
            decision: gate_counts.get(decision, 0) for decision in _GATE_DECISIONS
        }
        for decision in gate_counts:
            if decision not in _GATE_DECISIONS:
                metrics.label_gate_matrix[label][decision] = gate_counts[decision]

    for route, scenario_counts in sorted(route_scenario.items()):
        metrics.route_scenario_matrix[route] = dict(sorted(scenario_counts.items()))

    return metrics


def _matrix_markdown(
    title: str,
    matrix: dict[str, dict[str, int]],
    *,
    columns: list[str] | None = None,
) -> list[str]:
    if not matrix:
        return [f"### {title}", "", "*(no data)*", ""]
    col_headers = columns or sorted({key for row in matrix.values() for key in row})
    header = "| Row | " + " | ".join(col_headers) + " |"
    sep = "|-----|" + "|".join("------:" for _ in col_headers) + "|"
    lines = [f"### {title}", "", header, sep]
    for row_name, counts in sorted(matrix.items()):
        cells = " | ".join(str(counts.get(col, 0)) for col in col_headers)
        lines.append(f"| {row_name} | {cells} |")
    lines.append("")
    return lines


def format_shadow_retrieval_markdown(
    metrics: ShadowRetrievalDashboardMetrics,
    *,
    source_path: str,
    generated_at: str,
) -> str:
    """Render aggregate-safe Markdown dashboard."""
    lines = [
        "# Shadow Retrieval Metrics Dashboard",
        "",
        f"**Generated:** {generated_at}  ",
        f"**Source:** `{source_path}`  ",
        "**Scope:** Offline aggregate metrics from sanitized shadow replay JSONL only.",
        "",
        "## Summary",
        "",
        f"- **total_rows:** {metrics.total_rows}",
        f"- **shadow_node_executed_count:** {metrics.shadow_node_executed_count}",
        f"- **retrieval_error_count:** {metrics.retrieval_error_count}",
        f"- **retrieval_activated_true_count:** {metrics.retrieval_activated_true_count} "
        "(must be 0)",
        f"- **downstream_consumed_retrieval_true_count:** "
        f"{metrics.downstream_consumed_true_count} (must be 0)",
        "",
        "## Gate decision counts",
        "",
        "| Decision | Count |",
        "|----------|------:|",
    ]
    for decision in _GATE_DECISIONS:
        lines.append(f"| {decision} | {metrics.gate_decision_counts.get(decision, 0)} |")
    for decision, count in sorted(metrics.gate_decision_counts.items()):
        if decision not in _GATE_DECISIONS:
            lines.append(f"| {decision} | {count} |")
    lines.extend(["", "## Scenario counts", "", "| Scenario | Count |", "|----------|------:|"])
    for scenario, count in metrics.scenario_counts.most_common():
        lines.append(f"| {scenario} | {count} |")
    lines.extend(
        [
            "",
            "## Retrieval result count distribution",
            "",
            "| result_count | Count |",
            "|-------------|------:|",
        ]
    )
    for bucket, count in sorted(
        metrics.result_count_distribution.items(),
        key=lambda item: (item[0] == "(null)", item[0]),
    ):
        lines.append(f"| {bucket} | {count} |")
    lines.extend(_matrix_markdown("Label × gate decision", metrics.label_gate_matrix))
    lines.extend(_matrix_markdown("Route label × scenario", metrics.route_scenario_matrix))
    lines.extend(
        [
            "## Governance",
            "",
            "- Input JSONL is produced by "
            "`scripts/export_shadow_replay_jsonl.py` (Step 137; gitignored).",
            "- Shadow replay input must not contain raw queries, retrieved content, "
            "vectors, or transcripts.",
            "- `retrieval_activated=true` and `downstream_consumed_retrieval=true` "
            "rows are rejected at load time.",
            "- Default `LANGGRAPH_SANDBOX_RETRIEVAL_ENABLED=false`; this dashboard "
            "does not approve non-shadow consumption.",
            "",
        ]
    )
    return "\n".join(lines)


def metrics_to_json_dict(
    metrics: ShadowRetrievalDashboardMetrics,
    *,
    source_path: str,
    generated_at: str,
) -> dict[str, Any]:
    """Serialize metrics for optional JSON output."""
    return {
        "generated_at": generated_at,
        "source_path": source_path,
        "total_rows": metrics.total_rows,
        "shadow_node_executed_count": metrics.shadow_node_executed_count,
        "gate_decision_counts": dict(metrics.gate_decision_counts),
        "scenario_counts": dict(metrics.scenario_counts),
        "result_count_distribution": dict(metrics.result_count_distribution),
        "retrieval_error_count": metrics.retrieval_error_count,
        "retrieval_activated_true_count": metrics.retrieval_activated_true_count,
        "downstream_consumed_true_count": metrics.downstream_consumed_true_count,
        "label_gate_matrix": metrics.label_gate_matrix,
        "route_scenario_matrix": metrics.route_scenario_matrix,
    }


def assert_dashboard_output_safe(content: str) -> None:
    lowered = content.lower()
    for key in FORBIDDEN_SHADOW_REPLAY_KEYS:
        if f'"{key}"' in content:
            raise ValueError(f"dashboard output must not reference forbidden key: {key}")
    for token in FORBIDDEN_SHADOW_REPLAY_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"dashboard output must not contain forbidden token: {token}")


def build_shadow_retrieval_dashboard(
    report_path: Path,
    *,
    markdown_output: Path,
    json_output: Path | None = None,
    generated_at: str | None = None,
) -> ShadowRetrievalDashboardMetrics:
    """Read shadow replay JSONL and write Markdown (and optional JSON) dashboard."""
    from datetime import UTC, datetime

    rows = load_shadow_retrieval_rows(report_path)
    metrics = compute_shadow_retrieval_metrics(rows)

    if metrics.retrieval_activated_true_count or metrics.downstream_consumed_true_count:
        raise ValueError("aggregated metrics contain forbidden activation/consumption counts")

    ts = generated_at or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = str(report_path)

    markdown = format_shadow_retrieval_markdown(metrics, source_path=source, generated_at=ts)
    assert_dashboard_output_safe(markdown)

    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.write_text(markdown, encoding="utf-8")

    if json_output is not None:
        payload = metrics_to_json_dict(metrics, source_path=source, generated_at=ts)
        json_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        assert_dashboard_output_safe(json_text)
        json_output.write_text(json_text, encoding="utf-8")

    return metrics
