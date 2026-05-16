"""Tests for operator-facing QA attention summary on API responses."""

from __future__ import annotations

import pytest
from app.api.main import _serialize_state, app
from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.vendor_ticket import DraftingResult, build_qa_attention_summary
from fastapi.testclient import TestClient

from tests.test_vendor_ticket_workflow import make_base_state


def test_build_qa_attention_summary_limits_top_items() -> None:
    state = make_base_state()
    state["qa_issues"] = [f"issue-{i}" for i in range(5)]
    state["qa_warnings"] = [f"warn-{i}" for i in range(4)]
    state["qa_summary"] = "failed:5 issue(s), 4 warning(s)"
    state["route_label"] = "qa_attention"
    state["qa_requires_human_attention"] = True

    summary = build_qa_attention_summary(state)
    assert summary["requires_attention"] is True
    assert summary["issue_count"] == 5
    assert summary["warning_count"] == 4
    assert summary["top_issues"] == ["issue-0", "issue-1", "issue-2"]
    assert summary["top_warnings"] == ["warn-0", "warn-1", "warn-2"]
    assert summary["summary"] == "failed:5 issue(s), 4 warning(s)"
    assert summary["route_label"] == "qa_attention"
    assert "draft_response" not in summary
    assert "OPENAI" not in str(summary).upper()


def test_build_qa_attention_summary_requires_attention_from_issues_only() -> None:
    state = make_base_state()
    state["qa_issues"] = ["risky_promise_language:مبلغ قطعی"]
    state["qa_requires_human_attention"] = False

    summary = build_qa_attention_summary(state)
    assert summary["requires_attention"] is True


def test_happy_path_api_qa_attention_summary() -> None:
    state = run_vendor_ticket_demo(
        "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
        ticket_id="t-qa-summary-happy",
    )
    response = _serialize_state(state)
    body = response.model_dump()
    assert "qa_attention_summary" in body
    qa = body["qa_attention_summary"]
    assert qa["requires_attention"] is False
    assert qa["route_label"] == "billing_review"
    assert qa["issue_count"] == 0


def test_qa_issue_path_api_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    def _risky_draft(**kwargs: object) -> DraftingResult:
        _ = kwargs
        return DraftingResult(
            draft_response="مبلغ قطعی فردا واریز می‌شود.",
            llm_provider="mock",
            llm_model="mock-vendor-ticket-drafter",
        )

    monkeypatch.setattr("app.nodes.vendor_ticket._drafting_agent", _risky_draft)
    client = TestClient(app)
    res = client.post(
        "/run-vendor-ticket",
        json={
            "user_input": "سلام، تسویه این هفته با فاکتور هم‌خوان نیست.",
            "ticket_id": "t-qa-summary-issue",
        },
    )
    assert res.status_code == 200
    body = res.json()
    qa = body["qa_attention_summary"]
    assert qa["requires_attention"] is True
    assert qa["qa_passed"] is False
    assert qa["issue_count"] >= 1
    assert qa["top_issues"]
    assert "risky_promise" in qa["top_issues"][0]
    assert qa["route_label"] == "qa_attention"
    assert "draft_response" not in qa


def test_api_response_includes_existing_and_qa_summary_fields() -> None:
    client = TestClient(app)
    res = client.post(
        "/run-vendor-ticket",
        json={"user_input": "سلام", "ticket_id": "t-qa-summary-keys"},
    )
    body = res.json()
    assert set(body.keys()) >= {
        "request_id",
        "specialist_output",
        "qa_attention_summary",
        "review_queue_metadata",
        "audit_log",
        "human_approval_required",
    }
