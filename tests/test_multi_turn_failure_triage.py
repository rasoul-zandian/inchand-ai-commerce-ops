"""Tests for multi-turn eval failure triage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.multi_turn_failure_triage import (
    EvalFailureCategory,
    EvalFailureSeverity,
    EvalFailureTriageItem,
    SuggestedFixArea,
    _draft_has_ack_equivalent,
    _is_acceptable_variance,
    assert_report_safe,
    cluster_triage_items,
    load_eval_results_jsonl,
    render_triage_report_markdown,
    run_failure_triage,
    triage_eval_row,
    write_failure_triage_reports,
)


def _row(
    *,
    scenario_id: str = "s1",
    passed: bool = False,
    draft: str = "",
    failed_assertions: list[dict[str, str]] | None = None,
    **extra: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "scenario_id": scenario_id,
        "title": "Test",
        "category": "tracking_fulfillment",
        "passed": passed,
        "draft_reply": draft,
        "provider": "mock",
        "reflection_reviewed": True,
        "reflection_rewrite_applied": False,
        "reflection_issue_types": [],
        "failed_assertions": failed_assertions or [],
        "detected_intent": "unknown",
        "suggested_action": "monitor",
    }
    payload.update(extra)
    return payload


def test_repeated_ask_classification() -> None:
    items = triage_eval_row(
        _row(
            draft="لطفاً کد رهگیری را ارسال کنید.",
            failed_assertions=[
                {
                    "name": "must_not_contain:کد رهگیری را ارسال کنید",
                    "message": "forbidden marker present",
                },
            ],
        ),
        scenarios_by_id={},
    )
    assert len(items) == 1
    assert items[0].failure_type == EvalFailureCategory.REPEATED_IDENTIFIER_REQUEST
    assert items[0].severity == EvalFailureSeverity.CRITICAL
    assert items[0].suggested_fix_area == SuggestedFixArea.MULTI_TURN_CONTEXT


def test_policy_grounding_classification() -> None:
    items = triage_eval_row(
        _row(
            category="settlement_policy",
            draft="لطفاً به قوانین مراجعه کنید.",
            policy_question_type="settlement_timing",
            failed_assertions=[
                {
                    "name": "must_contain:۳ روز",
                    "message": "missing marker: ۳ روز",
                },
            ],
        ),
        scenarios_by_id={},
    )
    assert items[0].failure_type == EvalFailureCategory.POLICY_GROUNDING_FAILURE
    assert items[0].suggested_fix_area == SuggestedFixArea.POLICY_GROUNDING


def test_reflection_miss_detection() -> None:
    items = triage_eval_row(
        _row(
            failed_assertions=[
                {
                    "name": "reflection_rewrite_expected",
                    "message": "expected=True actual=False",
                },
            ],
        ),
        scenarios_by_id={},
    )
    assert items[0].failure_type == EvalFailureCategory.REFLECTION_MISSED_ISSUE
    assert items[0].suggested_fix_area == SuggestedFixArea.REFLECTION


def test_acceptable_variance_downgrade() -> None:
    draft = "کد رهگیری دریافت شد و درخواست شما در دست بررسی قرار گرفت."
    row = _row(
        draft=draft,
        failed_assertions=[
            {
                "name": "must_contain:ثبت شد",
                "message": "missing marker: ثبت شد",
            },
        ],
    )
    assert _draft_has_ack_equivalent(draft, "ثبت شد") or _draft_has_ack_equivalent(
        draft,
        "دریافت شد",
    )
    assert _is_acceptable_variance(
        row,
        assertion_name="must_contain:ثبت شد",
        assertion_message="missing",
        draft=draft,
    )
    items = triage_eval_row(row, scenarios_by_id={})
    assert items[0].acceptable_variance is True
    assert items[0].failure_type == EvalFailureCategory.ACCEPTABLE_VARIANCE


def test_clustering_groups_same_pattern() -> None:
    items = [
        EvalFailureTriageItem(
            scenario_id="a",
            scenario_category="tracking_fulfillment",
            failure_type=EvalFailureCategory.REPEATED_IDENTIFIER_REQUEST,
            severity=EvalFailureSeverity.CRITICAL,
            provider="mock",
            ticket_label=None,
            expected_assertion="must_not_contain:کد رهگیری را ارسال کنید",
            actual_output_summary="x",
            conversation_summary="c",
            draft_reply="d",
            reflection_applied=False,
            reflection_saved=False,
            reflection_issue_types=(),
            root_cause_hypothesis="h",
            suggested_fix_area=SuggestedFixArea.MULTI_TURN_CONTEXT,
            regression_risk="high",
            priority_score=100.0,
        ),
        EvalFailureTriageItem(
            scenario_id="b",
            scenario_category="tracking_fulfillment",
            failure_type=EvalFailureCategory.REPEATED_IDENTIFIER_REQUEST,
            severity=EvalFailureSeverity.CRITICAL,
            provider="mock",
            ticket_label=None,
            expected_assertion="must_not_contain:کد رهگیری را ارسال کنید",
            actual_output_summary="x",
            conversation_summary="c",
            draft_reply="d",
            reflection_applied=False,
            reflection_saved=False,
            reflection_issue_types=(),
            root_cause_hypothesis="h",
            suggested_fix_area=SuggestedFixArea.MULTI_TURN_CONTEXT,
            regression_risk="high",
            priority_score=100.0,
        ),
    ]
    clusters = cluster_triage_items(items)
    assert len(clusters) == 1
    assert clusters[0].occurrence_count == 2
    assert "a" in clusters[0].scenario_ids and "b" in clusters[0].scenario_ids


def test_severity_and_subsystem_suggestion() -> None:
    items = triage_eval_row(
        _row(
            category="panel_issue",
            draft="لطفاً شناسه پنل را ارسال کنید.",
            failed_assertions=[
                {
                    "name": "must_not_contain:شناسه پنل",
                    "message": "forbidden",
                },
            ],
        ),
        scenarios_by_id={},
    )
    assert items[0].failure_type == EvalFailureCategory.PANEL_ISSUE_HANDLING_FAILURE
    assert items[0].severity == EvalFailureSeverity.HIGH
    assert items[0].suggested_fix_area == SuggestedFixArea.OPERATIONAL_SUFFICIENCY


def test_priority_ordering_in_summary() -> None:
    rows = [
        _row(
            scenario_id="low",
            draft="x",
            failed_assertions=[{"name": "expected_intent", "message": "mismatch"}],
        ),
        _row(
            scenario_id="high",
            draft="لطفاً کد رهگیری را ارسال کنید",
            failed_assertions=[
                {"name": "must_not_contain:کد رهگیری را ارسال کنید", "message": "forbidden"},
            ],
        ),
    ]
    summary = run_failure_triage(rows, source_path="test.jsonl")
    real = [item for item in summary.items if not item.acceptable_variance]
    assert real[0].priority_score >= real[-1].priority_score


def test_reflection_metrics() -> None:
    rows = [
        _row(scenario_id="ok", passed=True, draft="ok", reflection_rewrite_applied=True),
        _row(
            scenario_id="miss",
            failed_assertions=[
                {"name": "reflection_rewrite_expected", "message": "expected=True actual=False"},
            ],
        ),
    ]
    summary = run_failure_triage(rows, source_path="test.jsonl")
    assert summary.reflection_metrics.failures_missed_by_reflection >= 1


def test_markdown_report_no_hidden_reasoning() -> None:
    summary = run_failure_triage(
        [
            _row(
                draft="test",
                failed_assertions=[{"name": "must_contain:ثبت", "message": "missing"}],
            ),
        ],
        source_path="test.jsonl",
    )
    md = render_triage_report_markdown(summary)
    assert_report_safe(md)
    assert "chain_of_thought" not in md
    assert "raw_prompt" not in md
    assert "Critical failures" in md or "High-impact" in md


def test_load_jsonl_and_write_reports(tmp_path: Path) -> None:
    jsonl = tmp_path / "results.jsonl"
    row = _row(
        draft="لطفاً کد رهگیری را ارسال کنید",
        failed_assertions=[
            {"name": "must_not_contain:کد رهگیری را ارسال کنید", "message": "forbidden"},
        ],
    )
    jsonl.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = load_eval_results_jsonl(jsonl)
    summary = run_failure_triage(rows, source_path=str(jsonl))
    write_failure_triage_reports(
        summary,
        summary_json=tmp_path / "summary.json",
        report_md=tmp_path / "report.md",
        clusters_json=tmp_path / "clusters.json",
        overwrite=True,
    )
    assert (tmp_path / "summary.json").is_file()
    public = (tmp_path / "summary.json").read_text(encoding="utf-8")
    assert "hidden_reasoning" not in public


def test_photo_request_leakage_classification() -> None:
    items = triage_eval_row(
        _row(
            category="delivery_completed",
            draft="لطفاً فایل عکس را ارسال کنید.",
            failed_assertions=[
                {"name": "must_not_contain:عکس", "message": "forbidden"},
            ],
        ),
        scenarios_by_id={},
    )
    assert items[0].failure_type == EvalFailureCategory.PHOTO_REQUEST_LEAKAGE


def test_load_jsonl_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_eval_results_jsonl(tmp_path / "missing.jsonl")
