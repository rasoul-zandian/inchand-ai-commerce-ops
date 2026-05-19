"""Tests for shadow replay hit-count diagnosis (no raw content in outputs)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.pilot_pgvector_metadata_inventory import PilotMetadataRow
from app.corpus_planning.shadow_replay_hit_diagnosis import (
    IndexFilterMatchDiagnosis,
    ShadowReplayRowSummary,
    assert_safe_diagnosis_output,
    build_shadow_replay_hit_findings,
    diagnose_index_filter_matches,
    format_diagnosis_markdown,
    run_shadow_replay_hit_diagnosis,
    summarize_shadow_replay_rows,
    write_shadow_replay_hit_diagnosis_report,
)


def _sample_replay_row(
    *,
    ticket_label: str = "fund",
    route_label: str = "billing_review",
    review_priority: str = "LOW",
    result_count: int = 0,
) -> dict[str, object]:
    return {
        "room_id": "ROOM_1",
        "ticket_label": ticket_label,
        "route_label": route_label,
        "review_priority": review_priority,
        "shadow_node_executed": True,
        "retrieval_gate_decision": "allow",
        "retrieval_scenario": "fund_finance",
        "retrieval_policy_reasons": ["retrieval_allowed for fund"],
        "retrieval_query_hash": "abc123456789abcd",
        "retrieval_result_count": result_count,
        "retrieval_metadata_filter": {
            "ticket_label": ticket_label,
            "route_label": route_label,
            "review_priority": review_priority,
        },
        "retrieval_sandbox_only": True,
        "executor_called": True,
        "retrieval_activated": False,
        "downstream_consumed_retrieval": False,
        "errors": [],
    }


def test_summarize_counts_metadata_filters_safely() -> None:
    rows = [
        _sample_replay_row(),
        _sample_replay_row(ticket_label="support", route_label="general_vendor_support"),
    ]
    summary = summarize_shadow_replay_rows(rows)
    assert summary.total_rows == 2
    assert summary.executor_called_count == 2
    assert summary.distinct_metadata_filter_patterns == 2
    assert summary.retrieval_result_count_distribution["0"] == 2


def test_findings_index_rows_but_export_filters_zero() -> None:
    replay = ShadowReplayRowSummary(
        total_rows=10,
        retrieval_result_count_distribution={"0": 10},
        executor_called_count=10,
    )
    index = IndexFilterMatchDiagnosis(
        pgvector_available=True,
        index_row_count=25,
        index_ticket_label_counts={"fund": 8, "support": 10, "complaint": 7},
        standard_filter_match_counts={
            "ticket_label=fund,route_label=billing_review": 8,
        },
        export_filter_pattern_match_counts={
            "review_priority=LOW,route_label=billing_review,ticket_label=fund": 0,
        },
        export_filter_patterns_all_zero_hits=True,
    )
    findings = build_shadow_replay_hit_findings(replay, query=None, index=index)
    joined = " ".join(findings).lower()
    assert "over-constrained" in joined or "0 index rows" in joined
    assert "review_priority" in joined
    assert "query" not in joined or "raw" in joined


def test_diagnose_index_filter_matches_with_injected_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    index_rows = [
        PilotMetadataRow(
            record_id="pilot::vendor_ticket_real_pilot_balanced::pilot_balanced_v1::fund-1",
            metadata={
                "ticket_label": "fund",
                "route_label": "billing_review",
                "review_priority": "high",
                "namespace": "vendor_ticket_real_pilot_balanced",
                "index_version": "pilot_balanced_v1",
            },
            embedding_provider="openai",
            embedding_model="text-embedding-3-small",
        ),
    ]

    def _fake_fetch(*_args: object, **_kwargs: object) -> list[PilotMetadataRow]:
        return index_rows

    monkeypatch.setattr(
        "app.corpus_planning.shadow_replay_hit_diagnosis.fetch_pilot_metadata_rows",
        _fake_fetch,
    )

    diagnosis = diagnose_index_filter_matches(
        namespace="vendor_ticket_real_pilot_balanced",
        index_version="pilot_balanced_v1",
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        export_filter_patterns={
            "review_priority=LOW,route_label=billing_review,ticket_label=fund": 20,
        },
    )
    assert diagnosis.pgvector_available is True
    assert diagnosis.index_row_count == 1
    assert (
        diagnosis.standard_filter_match_counts["ticket_label=fund,route_label=billing_review"] == 1
    )
    assert (
        diagnosis.export_filter_pattern_match_counts[
            "review_priority=LOW,route_label=billing_review,ticket_label=fund"
        ]
        == 0
    )


def test_diagnosis_output_rejects_forbidden_content() -> None:
    with pytest.raises(ValueError, match="forbidden key"):
        assert_safe_diagnosis_output('{"query": "secret"}')


def test_run_diagnosis_on_fixture_jsonl(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.jsonl"
    shadow.write_text(json.dumps(_sample_replay_row()) + "\n", encoding="utf-8")

    diagnosis = run_shadow_replay_hit_diagnosis(
        shadow,
        database_url="",
        ticket_export_path=None,
    )
    assert diagnosis.replay_summary.total_rows == 1
    md = format_diagnosis_markdown(diagnosis)
    assert_safe_diagnosis_output(md)
    assert "retrieval_result_count" in md
    assert '"query"' not in md


def test_write_diagnosis_reports(tmp_path: Path) -> None:
    shadow = tmp_path / "shadow.jsonl"
    shadow.write_text(json.dumps(_sample_replay_row()) + "\n", encoding="utf-8")
    diagnosis = run_shadow_replay_hit_diagnosis(shadow, database_url="")
    json_out = tmp_path / "diag.json"
    md_out = tmp_path / "diag.md"
    write_shadow_replay_hit_diagnosis_report(
        diagnosis,
        json_output=json_out,
        markdown_output=md_out,
    )
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["replay_summary"]["total_rows"] == 1
    assert_safe_diagnosis_output(md_out.read_text(encoding="utf-8"))
