"""Tests for OpenAI multi-turn behavioral baseline freeze and compare."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.multi_turn_eval_runner import EvalScenarioResult, EvalSuiteSummary
from app.evals.openai_multi_turn_baseline import (
    BaselineDriftClass,
    BaselineFreezeSummary,
    BaselineManifest,
    BaselineReflectionMetrics,
    BaselineScenarioRecord,
    assert_baseline_payload_safe,
    build_manifest_from_run,
    classify_scenario_drift,
    compare_baseline_records,
    compute_baseline_draft_fingerprint,
    freeze_openai_baseline,
    load_all_baseline_records,
    load_baseline_manifest,
    load_baseline_scenario_record,
    normalize_baseline_draft_text,
    reflection_metrics_from_results,
    render_compare_report_markdown,
    render_freeze_report_markdown,
    scenario_record_from_eval_result,
    write_baseline_manifest,
    write_baseline_reports,
    write_baseline_scenario_record,
)


def _eval_result(
    *,
    scenario_id: str = "s1",
    passed: bool = True,
    draft: str = "درخواست لغو سفارش شما ثبت شد.",
    intent: str = "cancellation_request",
    action: str = "human_followup",
    rewrite: bool = True,
    should_generate: bool = True,
) -> EvalScenarioResult:
    return EvalScenarioResult(
        scenario_id=scenario_id,
        title=scenario_id,
        category="cancellation",
        passed=passed,
        error=None,
        draft_reply=draft,
        draft_fingerprint=compute_baseline_draft_fingerprint(draft),
        detected_intent=intent,
        suggested_action=action,
        should_generate_draft=should_generate,
        skip_reason=None,
        reflection_reviewed=True,
        reflection_rewrite_applied=rewrite,
        reflection_issue_types=("missing_operational_ack",),
        policy_question_type="none",
        assertion_results=(),
        provider="openai",
        graph_status="ok",
    )


def test_normalization_stability() -> None:
    a = normalize_baseline_draft_text("درخواست لغو سفارش شما ثبت شد.  ")
    b = normalize_baseline_draft_text("درخواست لغو سفارش شما ثبت شد.")
    assert normalize_baseline_draft_text("درخواست لغو سفارش شما ثبت شد…") == a
    assert a == b
    fp_trim = compute_baseline_draft_fingerprint("test  ")
    fp_plain = compute_baseline_draft_fingerprint("test")
    assert fp_trim == fp_plain


def test_fingerprint_generation() -> None:
    fp = compute_baseline_draft_fingerprint("کد رهگیری دریافت شد")
    assert fp is not None
    assert len(fp) == 64


def test_acceptable_drift_fingerprint_only() -> None:
    baseline = BaselineScenarioRecord(
        scenario_id="tracking_fulfilled_after_support_request",
        draft_fingerprint="aaa",
        detected_intent="cancellation_request",
        suggested_action="human_followup",
        reflection_rewrite_applied=True,
        should_generate_draft=True,
        policy_question_type="none",
        eval_passed=True,
    )
    current = BaselineScenarioRecord(
        scenario_id="tracking_fulfilled_after_support_request",
        draft_fingerprint="bbb",
        detected_intent="cancellation_request",
        suggested_action="human_followup",
        reflection_rewrite_applied=True,
        should_generate_draft=True,
        policy_question_type="none",
        eval_passed=True,
    )
    item = classify_scenario_drift(baseline, current)
    assert item.drift_class == BaselineDriftClass.ACCEPTABLE


def test_critical_regression_eval_pass_to_fail() -> None:
    baseline = BaselineScenarioRecord(
        scenario_id="closed_ticket_skip",
        draft_fingerprint="aaa",
        detected_intent="order_status_review",
        suggested_action="check_order_status",
        reflection_rewrite_applied=False,
        should_generate_draft=False,
        policy_question_type="none",
        eval_passed=True,
    )
    current = BaselineScenarioRecord(
        scenario_id="closed_ticket_skip",
        draft_fingerprint="bbb",
        detected_intent="order_status_review",
        suggested_action="check_order_status",
        reflection_rewrite_applied=False,
        should_generate_draft=True,
        policy_question_type="none",
        eval_passed=False,
    )
    item = classify_scenario_drift(
        baseline,
        current,
        scenario_category="latest_support_skip",
    )
    assert item.drift_class == BaselineDriftClass.CRITICAL_REGRESSION
    assert "eval_regression" in item.reasons


def test_review_required_intent_drift() -> None:
    baseline = BaselineScenarioRecord(
        scenario_id="cancellation_no_reason_ask",
        draft_fingerprint="aaa",
        detected_intent="cancellation_request",
        suggested_action="human_followup",
        reflection_rewrite_applied=True,
        should_generate_draft=True,
        policy_question_type="none",
        eval_passed=True,
    )
    current = BaselineScenarioRecord(
        scenario_id="cancellation_no_reason_ask",
        draft_fingerprint="aaa",
        detected_intent="seller_notification",
        suggested_action="record_update",
        reflection_rewrite_applied=True,
        should_generate_draft=True,
        policy_question_type="none",
        eval_passed=True,
    )
    item = classify_scenario_drift(baseline, current)
    assert item.drift_class == BaselineDriftClass.REVIEW_REQUIRED
    assert "intent_drift" in item.reasons


def test_baseline_write_read_roundtrip(tmp_path: Path) -> None:
    record = scenario_record_from_eval_result(_eval_result())
    path = write_baseline_scenario_record(record, baseline_dir=tmp_path, overwrite=True)
    loaded = load_baseline_scenario_record("s1", baseline_dir=tmp_path)
    assert loaded is not None
    assert loaded.draft_fingerprint == record.draft_fingerprint
    assert path.name == "s1.json"


def test_update_baseline_guard(tmp_path: Path) -> None:
    record = scenario_record_from_eval_result(_eval_result())
    write_baseline_scenario_record(record, baseline_dir=tmp_path, overwrite=False)
    with pytest.raises(FileExistsError, match="--update-baseline"):
        write_baseline_scenario_record(record, baseline_dir=tmp_path, overwrite=False)


def test_freeze_requires_update_flag() -> None:
    with pytest.raises(ValueError, match="--update-baseline"):
        freeze_openai_baseline(scenarios=(), update_baseline=False)


def test_reflection_metrics_persistence() -> None:
    results = (
        _eval_result(rewrite=True),
        _eval_result(scenario_id="s2", rewrite=False),
    )
    metrics = reflection_metrics_from_results(results)
    assert metrics.rewrite_applied_count == 1
    assert metrics.rewrite_rate == 0.5
    assert metrics.issue_type_counts.get("missing_operational_ack") == 2


def test_no_hidden_prompt_leakage_in_payload() -> None:
    payload = {
        "scenario_id": "s1",
        "draft_fingerprint": "abc",
        "detected_intent": "cancellation_request",
    }
    assert_baseline_payload_safe(payload)
    with pytest.raises(ValueError, match="forbidden"):
        assert_baseline_payload_safe({"draft_reply": "secret"})


def test_compare_report_generation(tmp_path: Path) -> None:
    baseline = {
        "s1": BaselineScenarioRecord(
            scenario_id="s1",
            draft_fingerprint="aaa",
            detected_intent="cancellation_request",
            suggested_action="human_followup",
            reflection_rewrite_applied=True,
            should_generate_draft=True,
            policy_question_type="none",
            eval_passed=True,
        ),
    }
    current = {
        "s1": BaselineScenarioRecord(
            scenario_id="s1",
            draft_fingerprint="aaa",
            detected_intent="cancellation_request",
            suggested_action="human_followup",
            reflection_rewrite_applied=True,
            should_generate_draft=True,
            policy_question_type="none",
            eval_passed=True,
        ),
    }
    summary = compare_baseline_records(baseline, current, baseline_dir=tmp_path)
    md = render_compare_report_markdown(summary)
    assert "unchanged: 1" in md
    assert "raw_prompt" not in md.lower()


def test_manifest_roundtrip(tmp_path: Path) -> None:
    eval_summary = EvalSuiteSummary(
        status="passed",
        provider="openai",
        knowledge_hints_enabled=True,
        total_scenarios=1,
        passed_count=1,
        failed_count=0,
        pass_rate=1.0,
        by_category={},
        reflection_rewrite_count=1,
        reflection_saved_bad_draft_count=1,
        repeated_ask_failures=0,
        policy_grounding_failures=0,
        unsupported_claim_failures=0,
        golden_checked_count=0,
        golden_mismatch_count=0,
        generated_at_utc="2026-05-26T12:00:00+00:00",
        scenarios_path="data/evals/multi_turn_scenarios.json",
    )
    from app.config import AppSettings

    manifest = build_manifest_from_run(
        eval_summary,
        settings=AppSettings(),
        reflection_metrics=BaselineReflectionMetrics(
            rewrite_applied_count=1,
            rewrite_rate=1.0,
            saved_bad_draft_count=1,
            save_rate=1.0,
            reflection_reviewed_count=1,
        ),
    )
    write_baseline_manifest(manifest, baseline_dir=tmp_path, overwrite=True)
    loaded = load_baseline_manifest(tmp_path)
    assert loaded is not None
    assert loaded.provider == "openai"
    assert loaded.reflection_metrics.rewrite_applied_count == 1


def test_load_all_baseline_records(tmp_path: Path) -> None:
    write_baseline_scenario_record(
        scenario_record_from_eval_result(_eval_result()),
        baseline_dir=tmp_path,
        overwrite=True,
    )
    records = load_all_baseline_records(baseline_dir=tmp_path)
    assert "s1" in records


def test_freeze_report_safe() -> None:
    freeze = BaselineFreezeSummary(
        status="passed",
        baseline_dir=str(Path("data/evals/golden_outputs/openai_baseline")),
        update_baseline=True,
        eval_summary=EvalSuiteSummary(
            status="passed",
            provider="openai",
            knowledge_hints_enabled=True,
            total_scenarios=1,
            passed_count=1,
            failed_count=0,
            pass_rate=1.0,
            by_category={},
            reflection_rewrite_count=0,
            reflection_saved_bad_draft_count=0,
            repeated_ask_failures=0,
            policy_grounding_failures=0,
            unsupported_claim_failures=0,
            golden_checked_count=0,
            golden_mismatch_count=0,
            generated_at_utc="2026-05-26T12:00:00+00:00",
            scenarios_path="data/evals/multi_turn_scenarios.json",
        ),
        manifest=BaselineManifest(
            baseline_id="openai_multi_turn_v1",
            provider="openai",
            model="gpt-test",
            knowledge_hints_enabled=True,
            multi_turn_context_enabled=True,
            final_draft_reflection_enabled=True,
            reflection_provider="rule_based",
            frozen_at_utc="2026-05-26T12:00:00+00:00",
            scenario_count=1,
            eval_passed_count=1,
            eval_failed_count=0,
            reflection_metrics=BaselineReflectionMetrics(
                rewrite_applied_count=0,
                rewrite_rate=0.0,
                saved_bad_draft_count=0,
                save_rate=0.0,
                reflection_reviewed_count=0,
            ),
        ),
        triage_real_failures=0,
        triage_critical_count=0,
        triage_high_count=0,
        scenario_files_written=1,
        generated_at_utc="2026-05-26T12:00:00+00:00",
    )
    text = render_freeze_report_markdown(freeze)
    assert "OpenAI multi-turn baseline freeze" in text


def test_write_reports_no_transcript(tmp_path: Path) -> None:
    summary = compare_baseline_records({}, {})
    write_baseline_reports(
        compare_summary=summary,
        compare_summary_json=tmp_path / "compare.json",
        compare_report_md=tmp_path / "compare.md",
        overwrite=True,
    )
    payload = json.loads((tmp_path / "compare.json").read_text(encoding="utf-8"))
    assert "messages" not in payload
