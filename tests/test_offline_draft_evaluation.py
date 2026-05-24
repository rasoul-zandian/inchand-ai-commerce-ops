"""Tests for offline draft vs gold evaluation (deterministic; no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.offline_draft_evaluation import (
    evaluate_draft_against_gold,
    lexical_overlap_score,
    load_benchmark_gold,
    load_draft_suggestions,
    render_draft_evaluation_markdown,
    run_offline_draft_evaluation,
    summarize_draft_evaluation,
)
from app.evals.offline_draft_generation import gold_reference_reply_hash


def _gold_row(
    case_id: str = "CASE_A",
    gold: str = "سلام واحد مالی بررسی می‌کند",
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "room_id": "ROOM_A",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "gold_reference_reply": gold,
    }


def _draft_row(
    case_id: str = "CASE_A",
    *,
    draft: str | None = "سلام واحد مالی در حال بررسی است",
    generated: bool = True,
) -> dict[str, object]:
    gold = "سلام واحد مالی بررسی می‌کند"
    return {
        "case_id": case_id,
        "room_id": "ROOM_A",
        "ticket_label": "fund",
        "route_label": "billing_review",
        "detected_intent": "settlement_status_inquiry",
        "suggested_action": "billing_review",
        "draft_reply": draft,
        "draft_generated": generated,
        "gold_reference_reply_hash": gold_reference_reply_hash(gold),
    }


def test_lexical_overlap_partial_match() -> None:
    draft = "سلام واحد مالی در حال بررسی است"
    gold = "سلام واحد مالی بررسی می‌کند"
    score = lexical_overlap_score(draft, gold)
    assert 0.0 < score < 1.0


def test_evaluate_matches_by_case_id_and_detects_missing_draft() -> None:
    result_ok = evaluate_draft_against_gold("CASE_A", _draft_row(), _gold_row())
    assert result_ok.missing_draft is False
    assert result_ok.lexical_overlap_score is not None
    assert result_ok.unsafe_draft is False

    result_missing = evaluate_draft_against_gold(
        "CASE_B",
        _draft_row("CASE_B", draft=None, generated=False),
        _gold_row("CASE_B"),
    )
    assert result_missing.missing_draft is True
    assert result_missing.lexical_overlap_score is None


def test_flags_unsafe_draft() -> None:
    unsafe = "لطفاً به کارت 6037991234567890 واریز کنید."
    result = evaluate_draft_against_gold(
        "CASE_U",
        _draft_row("CASE_U", draft=unsafe),
        _gold_row("CASE_U"),
    )
    assert result.unsafe_draft is True
    assert result.lexical_overlap_score is None


def test_summarize_counts_and_low_overlap(tmp_path: Path) -> None:
    results = [
        evaluate_draft_against_gold("C1", _draft_row("C1"), _gold_row("C1")),
        evaluate_draft_against_gold(
            "C2",
            _draft_row("C2", draft="متن کاملاً متفاوت بدون همپوشانی"),
            _gold_row("C2", gold="پاسخ دیگر با واژگان ناآشنا"),
        ),
    ]
    summary = summarize_draft_evaluation(
        results,
        draft_suggestions_path=tmp_path / "d.jsonl",
        benchmark_path=tmp_path / "b.jsonl",
        output_json_path=tmp_path / "out.json",
        output_markdown_path=tmp_path / "out.md",
        low_overlap_threshold=0.5,
    )
    assert summary.total_cases == 2
    assert summary.evaluated_cases == 2
    assert summary.missing_draft_count == 0
    assert summary.intent_counts.get("settlement_status_inquiry") == 2
    assert summary.suggested_action_counts.get("billing_review") == 2
    assert len(summary.cases_with_low_overlap) >= 1


def test_markdown_excludes_raw_replies(tmp_path: Path) -> None:
    gold_text = "سلام — این متن طلایی محرمانه برای تست است"
    draft_text = "سلام — پیش‌نویس داخلی"
    results = [
        evaluate_draft_against_gold(
            "CASE_MD",
            _draft_row("CASE_MD", draft=draft_text),
            _gold_row("CASE_MD", gold=gold_text),
        ),
    ]
    summary = summarize_draft_evaluation(
        results,
        draft_suggestions_path=tmp_path / "d.jsonl",
        benchmark_path=tmp_path / "b.jsonl",
        output_json_path=tmp_path / "out.json",
        output_markdown_path=tmp_path / "out.md",
    )
    md = render_draft_evaluation_markdown(summary)
    assert "CASE_MD" in md
    assert gold_text not in md
    assert draft_text not in md
    assert "gold_reference_reply" not in md
    assert "draft_reply" not in md


def test_run_evaluation_end_to_end(tmp_path: Path) -> None:
    drafts_path = tmp_path / "drafts.jsonl"
    bench_path = tmp_path / "bench.jsonl"
    out_json = tmp_path / "eval.json"
    out_md = tmp_path / "eval.md"

    drafts_path.write_text(
        json.dumps(_draft_row(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    bench_path.write_text(
        json.dumps(_gold_row(), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    summary = run_offline_draft_evaluation(
        drafts_path,
        bench_path,
        output_json_path=out_json,
        output_markdown_path=out_md,
    )
    assert summary.total_cases == 1
    assert out_json.is_file()
    assert out_md.is_file()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "gold_reference_reply" not in json.dumps(payload)
    assert payload["summary"]["evaluated_cases"] == 1
    assert load_draft_suggestions(drafts_path)["CASE_A"]["case_id"] == "CASE_A"
    assert "CASE_A" in load_benchmark_gold(bench_path)


def test_load_requires_valid_jsonl(tmp_path: Path) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_draft_suggestions(bad)
