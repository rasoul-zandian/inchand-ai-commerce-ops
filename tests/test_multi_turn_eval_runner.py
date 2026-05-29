"""Tests for multi-turn evaluation scenario pack and assertion engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.multi_turn_eval_runner import (
    EvalExpected,
    EvalScenario,
    assert_report_safe,
    compute_draft_fingerprint,
    evaluate_assertions,
    load_eval_scenarios,
    load_golden_fingerprint,
    normalize_eval_text,
    render_eval_report_markdown,
    run_multi_turn_eval_suite,
    text_contains_marker,
    write_golden_fingerprint,
    write_multi_turn_eval_reports,
)
from app.operator_console.manual_chat_models import ManualChatMessage

_SAMPLE_SCENARIO_JSON = {
    "version": 1,
    "scenarios": [
        {
            "scenario_id": "test_tracking",
            "title": "Test tracking",
            "category": "tracking_fulfillment",
            "messages": [
                {"sender_type": "support_agent", "text": "لطفاً کد رهگیری را ارسال کنید"},
                {"sender_type": "seller", "text": "051800506400081160839102"},
            ],
            "expected": {
                "must_contain": ["دریافت شد"],
                "must_not_contain": ["کد رهگیری را ارسال کنید"],
                "should_generate_draft": True,
            },
        },
        {
            "scenario_id": "test_skip_support",
            "title": "Skip support latest",
            "category": "latest_support_skip",
            "messages": [
                {"sender_type": "seller", "text": "سلام"},
                {"sender_type": "support_agent", "text": "در حال بررسی"},
            ],
            "expected": {"should_generate_draft": False},
        },
    ],
}


def test_load_eval_scenarios_and_category_filter(tmp_path: Path) -> None:
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(_SAMPLE_SCENARIO_JSON, ensure_ascii=False), encoding="utf-8")
    all_scenarios = load_eval_scenarios(path)
    assert len(all_scenarios) == 2
    filtered = load_eval_scenarios(path, category="latest_support_skip")
    assert len(filtered) == 1
    assert filtered[0].scenario_id == "test_skip_support"
    single = load_eval_scenarios(path, scenario_id="test_tracking")
    assert len(single) == 1


def test_must_contain_and_must_not_contain() -> None:
    draft = "کد رهگیری دریافت شد و برای بررسی ارجاع شد."
    results = evaluate_assertions(
        EvalExpected(
            must_contain=["کد رهگیری دریافت شد"],
            must_not_contain=["کد رهگیری را ارسال کنید"],
        ),
        draft_reply=draft,
        detected_intent=None,
        suggested_action=None,
        should_generate_draft=True,
        skip_reason=None,
        reflection_rewrite_applied=False,
    )
    assert all(item.passed for item in results)


def test_must_not_contain_fails_when_forbidden_present() -> None:
    draft = "لطفاً کد رهگیری را ارسال کنید."
    results = evaluate_assertions(
        EvalExpected(must_not_contain=["کد رهگیری را ارسال کنید"]),
        draft_reply=draft,
        detected_intent=None,
        suggested_action=None,
        should_generate_draft=True,
        skip_reason=None,
        reflection_rewrite_applied=None,
    )
    assert any(item.name.startswith("must_not_contain") and not item.passed for item in results)


def test_expected_should_generate_draft() -> None:
    results = evaluate_assertions(
        EvalExpected(should_generate_draft=False),
        draft_reply=None,
        detected_intent=None,
        suggested_action=None,
        should_generate_draft=False,
        skip_reason="latest_message_from_support",
        reflection_rewrite_applied=None,
    )
    assert results[0].passed is True


def test_reflection_rewrite_expected_assertion() -> None:
    results = evaluate_assertions(
        EvalExpected(reflection_rewrite_expected=True),
        draft_reply="test",
        detected_intent=None,
        suggested_action=None,
        should_generate_draft=True,
        skip_reason=None,
        reflection_rewrite_applied=True,
    )
    assert results[0].passed is True


def test_persian_matching_normalization() -> None:
    assert text_contains_marker("شماره شبای صحیح", "شماره شبا")
    normalized = normalize_eval_text("۳ روز بعد")
    assert "3" in normalized or "۳" in normalized


def test_compute_draft_fingerprint_stable() -> None:
    fp1 = compute_draft_fingerprint("بانک سامان  ")
    fp2 = compute_draft_fingerprint("بانک سامان")
    assert fp1 == fp2


def test_golden_fingerprint_roundtrip(tmp_path: Path) -> None:
    golden_dir = tmp_path / "golden"
    write_golden_fingerprint("scenario_a", "abc123", golden_dir=golden_dir, overwrite=True)
    assert load_golden_fingerprint("scenario_a", golden_dir=golden_dir) == "abc123"


def test_report_generation_no_forbidden_tokens(tmp_path: Path) -> None:
    scenario = EvalScenario(
        scenario_id="s1",
        title="T",
        category="cancellation",
        messages=(
            ManualChatMessage(
                message_id="m1",
                sender_type="seller",
                text="لغو سفارش",
                created_at="2026-05-20T12:00:00Z",
            ),
        ),
        expected=EvalExpected(),
    )
    from app.evals.multi_turn_eval_runner import EvalScenarioResult, EvalSuiteSummary

    result = EvalScenarioResult(
        scenario_id="s1",
        title="T",
        category="cancellation",
        passed=False,
        error=None,
        draft_reply="پیش‌نویس تست",
        draft_fingerprint="fp",
        detected_intent="cancellation_request",
        suggested_action="cancel_order",
        should_generate_draft=True,
        skip_reason=None,
        reflection_reviewed=True,
        reflection_rewrite_applied=True,
        reflection_issue_types=("repeated_identifier_request",),
        policy_question_type="none",
        assertion_results=(),
        provider="mock",
        graph_status="ok",
    )
    summary = EvalSuiteSummary(
        status="failed",
        provider="mock",
        knowledge_hints_enabled=False,
        total_scenarios=1,
        passed_count=0,
        failed_count=1,
        pass_rate=0.0,
        by_category={"cancellation": {"passed": 0, "failed": 1, "total": 1}},
        reflection_rewrite_count=1,
        reflection_saved_bad_draft_count=1,
        repeated_ask_failures=0,
        policy_grounding_failures=0,
        unsupported_claim_failures=0,
        golden_checked_count=0,
        golden_mismatch_count=0,
        generated_at_utc="2026-05-20T12:00:00Z",
        scenarios_path="data/evals/multi_turn_scenarios.json",
        results=(result,),
    )
    md = render_eval_report_markdown(summary, (scenario,))
    assert_report_safe(md)
    assert "s1" in md
    assert "raw_prompt" not in md

    write_multi_turn_eval_reports(
        summary,
        (scenario,),
        summary_json=tmp_path / "summary.json",
        report_md=tmp_path / "report.md",
        results_jsonl=tmp_path / "results.jsonl",
        overwrite=True,
    )
    assert (tmp_path / "summary.json").is_file()


def test_run_eval_suite_mock_smoke() -> None:
    scenarios = load_eval_scenarios(limit=3)
    summary = run_multi_turn_eval_suite(
        scenarios,
        provider="mock",
        enable_knowledge_hints=False,
    )
    assert summary.total_scenarios == 3
    assert summary.provider == "mock"


def test_fail_fast_stops_early() -> None:
    scenarios = load_eval_scenarios(limit=10)
    summary = run_multi_turn_eval_suite(
        scenarios,
        provider="mock",
        fail_fast=True,
    )
    if summary.failed_count > 0:
        assert summary.total_scenarios < 10


def test_closed_ticket_skip_scenario_passes_mock() -> None:
    scenarios = load_eval_scenarios(scenario_id="closed_ticket_skip")
    assert len(scenarios) == 1
    assert scenarios[0].status == "closed"
    summary = run_multi_turn_eval_suite(
        scenarios,
        provider="mock",
        enable_knowledge_hints=False,
    )
    assert summary.passed_count == 1
    assert summary.failed_count == 0


def test_default_scenarios_file_loads() -> None:
    scenarios = load_eval_scenarios()
    assert len(scenarios) >= 25
    categories = {item.category for item in scenarios}
    required = {
        "tracking_fulfillment",
        "settlement_policy",
        "sheba_registration",
        "panel_issue",
        "latest_support_skip",
        "repeated_ask_prevention",
    }
    assert required.issubset(categories)


def test_scenarios_path_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_eval_scenarios(tmp_path / "missing.json")
