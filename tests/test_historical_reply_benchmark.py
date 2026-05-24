"""Tests for historical reply benchmark builder (synthetic tickets; no committed payloads)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.evals.historical_reply_benchmark import (
    FIRST_VENDOR_TURN_CASE_ID_SUFFIX,
    BenchmarkCaseMode,
    build_benchmark_from_jsonl,
    extract_cases_from_ticket_line,
)


def _ticket(
    *,
    room_id: str = "ROOM_BENCH",
    ticket_label: str = "support",
    route_label: str | None = None,
    messages: list[dict[str, str]],
) -> dict[str, object]:
    row: dict[str, object] = {
        "room_id": room_id,
        "ticket_label": ticket_label,
        "messages": messages,
        "metadata": {},
    }
    if route_label is not None:
        row["route_label"] = route_label
    return row


def test_extract_single_vendor_support_pair() -> None:
    raw = _ticket(
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "First vendor issue"},
            {
                "message_id": "m1",
                "sender_type": "support_agent",
                "text": "Human support reply here.",
            },
        ],
    )
    cases, skipped_unsafe, had_adj = extract_cases_from_ticket_line(raw)
    assert had_adj is True
    assert skipped_unsafe == 0
    assert len(cases) == 1
    assert cases[0]["case_id"] == "ROOM_BENCH__m0"
    assert cases[0]["responder_role"] == "support_agent"
    assert cases[0]["gold_reference_reply"] == "Human support reply here."
    snap = cases[0]["snapshot_before_reply"]
    assert snap["latest_vendor_message"] is not None
    assert "First vendor issue" in (snap["latest_vendor_message"] or "")


def test_double_vendor_before_support_one_case() -> None:
    raw = _ticket(
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "A"},
            {"message_id": "m1", "sender_type": "seller", "text": "B before reply"},
            {"message_id": "m2", "sender_type": "support_agent", "text": "Support after B"},
        ],
    )
    cases, _, had_adj = extract_cases_from_ticket_line(raw)
    assert had_adj is True
    assert len(cases) == 1
    assert cases[0]["sequence"]["vendor_message_id"] == "m1"
    assert "B before reply" in (cases[0]["snapshot_before_reply"]["latest_vendor_message"] or "")


def test_finance_responder_role() -> None:
    raw = _ticket(
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "Need invoice"},
            {"message_id": "m1", "sender_type": "finance_agent", "text": "Finance will review."},
        ],
    )
    cases, _, _ = extract_cases_from_ticket_line(raw)
    assert len(cases) == 1
    assert cases[0]["responder_role"] == "finance_agent"


def test_route_label_passthrough() -> None:
    raw = _ticket(
        route_label="billing_review",
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "Hello"},
            {"message_id": "m1", "sender_type": "support_agent", "text": "OK"},
        ],
    )
    cases, _, _ = extract_cases_from_ticket_line(raw)
    assert cases[0]["route_label"] == "billing_review"


def test_no_adjacent_support_skipped_no_support_in_summary(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    out_j = tmp_path / "bench.jsonl"
    out_s = tmp_path / "summary.json"
    inp.write_text(
        json.dumps(
            _ticket(
                room_id="R1",
                messages=[
                    {"message_id": "a", "sender_type": "seller", "text": "Only vendor"},
                ],
            ),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    stats = build_benchmark_from_jsonl(
        inp,
        output_jsonl_path=out_j,
        output_summary_path=out_s,
    )
    assert stats.total_cases == 0
    assert stats.skipped_no_support_reply == 1
    assert stats.tickets_processed == 1
    assert out_j.read_text(encoding="utf-8").strip() == ""


def test_build_benchmark_from_jsonl_writes_summary(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    out_j = tmp_path / "bench.jsonl"
    out_s = tmp_path / "summary.json"
    row = _ticket(
        room_id="R2",
        messages=[
            {"message_id": "v0", "sender_type": "seller", "text": "Question"},
            {"message_id": "s0", "sender_type": "support_agent", "text": "Answer text."},
        ],
    )
    inp.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    stats = build_benchmark_from_jsonl(
        inp,
        output_jsonl_path=out_j,
        output_summary_path=out_s,
    )
    assert stats.total_cases == 1
    assert stats.skipped_no_support_reply == 0
    lines = out_j.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    summary = json.loads(out_s.read_text(encoding="utf-8"))
    assert summary["total_cases"] == 1
    assert summary["cases_by_label"]["support"] == 1


def test_two_vendor_support_turns_yield_two_cases() -> None:
    raw = _ticket(
        room_id="R_MULTI",
        messages=[
            {"message_id": "v0", "sender_type": "seller", "text": "First"},
            {"message_id": "s0", "sender_type": "support_agent", "text": "Reply one."},
            {"message_id": "v1", "sender_type": "seller", "text": "Second"},
            {"message_id": "s1", "sender_type": "support_agent", "text": "Reply two."},
        ],
    )
    cases, _, _ = extract_cases_from_ticket_line(raw)
    assert len(cases) == 2
    assert {c["sequence"]["vendor_message_id"] for c in cases} == {"v0", "v1"}


def test_skipped_unsafe_when_gold_contains_transcript_marker() -> None:
    raw = _ticket(
        room_id="R_UNSAFE",
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "Vendor ok"},
            {
                "message_id": "m1",
                "sender_type": "support_agent",
                "text": 'Leaked "messages": [ in reply',
            },
        ],
    )
    cases, skipped_unsafe, had_adj = extract_cases_from_ticket_line(raw)
    assert had_adj is True
    assert skipped_unsafe == 1
    assert cases == []


def test_skipped_unsafe_when_open_snapshot_valueerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.evals import historical_reply_benchmark as hrb

    def _boom(_snap: object) -> object:
        raise ValueError("snapshot validation failed")

    monkeypatch.setattr(hrb, "build_open_ticket_snapshot", _boom)
    raw = _ticket(
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "Hi"},
            {"message_id": "m1", "sender_type": "support_agent", "text": "OK"},
        ],
    )
    cases, skipped_unsafe, had_adj = extract_cases_from_ticket_line(raw)
    assert had_adj is True
    assert skipped_unsafe == 1
    assert cases == []


def test_first_vendor_turn_one_case_per_room() -> None:
    raw = _ticket(
        room_id="ROOM_FT",
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "First vendor only"},
            {"message_id": "m1", "sender_type": "support_agent", "text": "First human reply."},
            {"message_id": "m2", "sender_type": "seller", "text": "Follow-up vendor"},
            {"message_id": "m3", "sender_type": "support_agent", "text": "Second human reply."},
        ],
    )
    cases, skipped, had = extract_cases_from_ticket_line(
        raw,
        case_mode=BenchmarkCaseMode.FIRST_VENDOR_TURN,
    )
    assert had is True
    assert skipped == 0
    assert len(cases) == 1
    assert cases[0]["case_id"] == f"ROOM_FT__{FIRST_VENDOR_TURN_CASE_ID_SUFFIX}"
    assert cases[0]["gold_reference_reply"] == "First human reply."
    snap = cases[0]["snapshot_before_reply"]
    assert snap["original_vendor_issue_preview"] == snap["latest_vendor_message"]
    assert "First vendor only" in (snap["latest_vendor_message"] or "")
    assert snap["recent_context_preview"] is None


def test_first_message_support_skips_room() -> None:
    raw = _ticket(
        room_id="ROOM_SKIP",
        messages=[
            {"message_id": "m0", "sender_type": "support_agent", "text": "Support opened"},
            {"message_id": "m1", "sender_type": "seller", "text": "Vendor later"},
        ],
    )
    cases, skipped, had = extract_cases_from_ticket_line(
        raw,
        case_mode=BenchmarkCaseMode.FIRST_VENDOR_TURN,
    )
    assert had is False
    assert cases == []
    assert skipped == 0


def test_first_vendor_turn_multiple_seller_still_one_case() -> None:
    raw = _ticket(
        messages=[
            {"message_id": "m0", "sender_type": "seller", "text": "A"},
            {"message_id": "m1", "sender_type": "seller", "text": "B before reply"},
            {"message_id": "m2", "sender_type": "support_agent", "text": "Support after B"},
        ],
    )
    cases, _, _ = extract_cases_from_ticket_line(
        raw,
        case_mode=BenchmarkCaseMode.FIRST_VENDOR_TURN,
    )
    assert len(cases) == 1
    assert cases[0]["gold_reference_reply"] == "Support after B"
    assert "A" in (cases[0]["snapshot_before_reply"]["latest_vendor_message"] or "")


def test_all_adjacent_pairs_unchanged_with_two_turns() -> None:
    raw = _ticket(
        room_id="R_MULTI",
        messages=[
            {"message_id": "v0", "sender_type": "seller", "text": "First"},
            {"message_id": "s0", "sender_type": "support_agent", "text": "Reply one."},
            {"message_id": "v1", "sender_type": "seller", "text": "Second"},
            {"message_id": "s1", "sender_type": "support_agent", "text": "Reply two."},
        ],
    )
    cases, _, _ = extract_cases_from_ticket_line(raw)
    assert len(cases) == 2


def test_build_benchmark_first_vendor_turn_cli_paths(tmp_path: Path) -> None:
    inp = tmp_path / "in.jsonl"
    out_j = tmp_path / "first_turn.jsonl"
    out_s = tmp_path / "first_turn_summary.json"
    inp.write_text(
        json.dumps(
            _ticket(
                room_id="R1",
                messages=[
                    {"message_id": "v0", "sender_type": "seller", "text": "Hi"},
                    {"message_id": "s0", "sender_type": "finance_agent", "text": "Finance OK"},
                ],
            ),
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    stats = build_benchmark_from_jsonl(
        inp,
        output_jsonl_path=out_j,
        output_summary_path=out_s,
        case_mode=BenchmarkCaseMode.FIRST_VENDOR_TURN,
    )
    assert stats.total_cases == 1
    assert stats.case_mode == BenchmarkCaseMode.FIRST_VENDOR_TURN.value
    summary = json.loads(out_s.read_text(encoding="utf-8"))
    assert summary["case_mode"] == "first_vendor_turn"


def test_invalid_jsonl_line_raises(tmp_path: Path) -> None:
    inp = tmp_path / "bad.jsonl"
    inp.write_text("not json\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        build_benchmark_from_jsonl(
            inp,
            output_jsonl_path=tmp_path / "o.jsonl",
            output_summary_path=tmp_path / "s.json",
        )
