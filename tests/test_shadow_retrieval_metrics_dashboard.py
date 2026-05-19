"""Tests for shadow retrieval metrics dashboard builder."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.shadow_retrieval_metrics_dashboard import (
    build_shadow_retrieval_dashboard,
    compute_shadow_retrieval_metrics,
    format_shadow_retrieval_markdown,
    load_shadow_retrieval_rows,
)


def _safe_rows() -> list[dict[str, object]]:
    return [
        {
            "room_id": "ROOM_FUND_1",
            "shadow_node_executed": True,
            "retrieval_gate_decision": "allow",
            "retrieval_scenario": "fund_finance",
            "retrieval_policy_reasons": ["retrieval_allowed for fund"],
            "retrieval_query_hash": "abc123456789abcd",
            "retrieval_result_count": 5,
            "retrieval_metadata_filter": {
                "ticket_label": "fund",
                "route_label": "billing_review",
            },
            "retrieval_sandbox_only": True,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "ticket_label": "fund",
            "route_label": "billing_review",
        },
        {
            "room_id": "ROOM_SUPPORT_1",
            "shadow_node_executed": True,
            "retrieval_gate_decision": "skip",
            "retrieval_scenario": "unknown",
            "retrieval_policy_reasons": ["ticket_label missing or unknown"],
            "retrieval_sandbox_only": True,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "ticket_label": "support",
            "route_label": "general_vendor_support",
        },
        {
            "room_id": "ROOM_DENY_1",
            "shadow_node_executed": False,
            "retrieval_gate_decision": "deny",
            "retrieval_scenario": "fund_finance",
            "retrieval_policy_reasons": ["fund retrieval requires metadata_filter"],
            "retrieval_sandbox_only": True,
            "retrieval_activated": False,
            "downstream_consumed_retrieval": False,
            "ticket_label": "fund",
            "route_label": "other_route",
        },
    ]


def test_compute_counts_and_matrices() -> None:
    metrics = compute_shadow_retrieval_metrics(_safe_rows())
    assert metrics.total_rows == 3
    assert metrics.shadow_node_executed_count == 2
    assert metrics.gate_decision_counts["allow"] == 1
    assert metrics.gate_decision_counts["skip"] == 1
    assert metrics.gate_decision_counts["deny"] == 1
    assert metrics.scenario_counts["fund_finance"] == 2
    assert metrics.result_count_distribution["5"] == 1
    assert metrics.result_count_distribution["(null)"] == 2
    assert metrics.retrieval_activated_true_count == 0
    assert metrics.downstream_consumed_true_count == 0
    assert metrics.label_gate_matrix["fund"]["allow"] == 1
    assert metrics.route_scenario_matrix["billing_review"]["fund_finance"] == 1


def test_rejects_forbidden_query_key(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text(
        json.dumps({"query": "secret", "retrieval_activated": False}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="forbidden keys"):
        load_shadow_retrieval_rows(path)


def test_rejects_retrieval_activated_true(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    row = dict(_safe_rows()[0])
    row["retrieval_activated"] = True
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="retrieval_activated"):
        load_shadow_retrieval_rows(path)


def test_rejects_downstream_consumed_true(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    row = dict(_safe_rows()[0])
    row["downstream_consumed_retrieval"] = True
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="downstream_consumed_retrieval"):
        load_shadow_retrieval_rows(path)


def test_markdown_contains_required_sections() -> None:
    metrics = compute_shadow_retrieval_metrics(_safe_rows())
    md = format_shadow_retrieval_markdown(
        metrics,
        source_path="reports/shadow_replay.jsonl",
        generated_at="2026-01-01T00:00:00Z",
    )
    assert "## Summary" in md
    assert "## Gate decision counts" in md
    assert "## Scenario counts" in md
    assert "## Retrieval result count distribution" in md
    assert "Label × gate decision" in md
    assert "Route label × scenario" in md
    assert "retrieval_activated_true_count" in md
    assert "downstream_consumed_retrieval_true_count" in md


def test_build_dashboard_writes_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "shadow.jsonl"
    input_path.write_text(
        "\n".join(json.dumps(row) for row in _safe_rows()) + "\n",
        encoding="utf-8",
    )
    md_path = tmp_path / "dashboard.md"
    json_path = tmp_path / "dashboard.json"
    build_shadow_retrieval_dashboard(
        input_path,
        markdown_output=md_path,
        json_output=json_path,
        generated_at="2026-01-01T00:00:00Z",
    )
    assert md_path.is_file()
    assert json_path.is_file()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["total_rows"] == 3
    assert payload["retrieval_activated_true_count"] == 0
