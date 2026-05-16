"""Tests for controlled redraft execution (operator-triggered only)."""

from __future__ import annotations

import json

import pytest
from app.api.main import ReviewActionRequest, _intake_review_action, app
from app.llm.types import LLMResponse
from app.review_queue.action_adapters import InMemoryReviewActionAdapter
from app.review_queue.redraft_execution import execute_controlled_redraft
from fastapi.testclient import TestClient


def _safe_snapshot(*, draft: str = "پیش‌نویس اولیه برای تست.") -> dict:
    return {
        "user_input": "سلام، تسویه با فاکتور مغایرت دارد.",
        "detected_intent": "billing_discrepancy",
        "grounding_summary": "policy: billing",
        "specialist_output": {"draft_response": draft, "detected_intent": "billing_discrepancy"},
        "retrieved_context": {
            "ticket": {"subject": "مغایرت تسویه", "body": "سلام"},
            "vendor": {"name": "فروشگاه نمونه"},
        },
    }


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_execute_false_approve_remains_not_executed(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-exec-off",
            "action_type": "approve",
            "execute": False,
        },
    )
    assert res.status_code == 200
    assert res.json()["execution_status"] == "not_executed"


def test_execute_true_approve_rejected(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-exec-approve",
            "action_type": "approve",
            "execute": True,
        },
    )
    assert res.status_code == 422


def test_execute_redraft_without_comment_rejected(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-exec-no-comment",
            "action_type": "request_redraft",
            "execute": True,
            "workflow_state_snapshot": _safe_snapshot(),
        },
    )
    assert res.status_code == 422


def test_execute_redraft_without_snapshot_rejected(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-exec-no-snapshot",
            "action_type": "request_redraft",
            "execute": True,
            "comment": "Remove guaranteed payment language.",
        },
    )
    assert res.status_code == 422
    assert "workflow_state_snapshot" in res.json()["detail"]["validation_errors"][0]


def test_execute_redraft_success_pending_approval(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _mock_generate_text(*args: object, **kwargs: object) -> LLMResponse:
        _ = args, kwargs
        return LLMResponse(
            content="پیش‌نویس بازنگری‌شده بدون وعده پرداخت قطعی.",
            provider="mock",
            model="mock-vendor-ticket-drafter",
            metadata={},
        )

    monkeypatch.setattr("app.review_queue.redraft_execution.generate_text", _mock_generate_text)
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-exec-ok",
            "action_type": "request_redraft",
            "execute": True,
            "comment": "Remove guaranteed payment language and ask for invoice number.",
            "workflow_state_snapshot": _safe_snapshot(),
            "operator_id": "op-redraft-1",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body["execution_status"] == "pending_approval"
    assert body["redraft_response"]
    assert body["redraft_summary"]["requires_human_approval"] is True
    assert body["redraft_summary"]["used_operator_comment"] is True
    assert body["redraft_result"]["redraft_id"]
    assert body["redraft_audit"]["previous_draft_hash"]
    assert body["redraft_audit"]["redraft_hash"]
    dumped = json.dumps(body)
    assert "api_key" not in dumped
    assert "sk-" not in dumped


def test_redraft_does_not_run_graph(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def _mock_generate_text(*args: object, **kwargs: object) -> LLMResponse:
        _ = args, kwargs
        return LLMResponse(content="پیش‌نویس جدید.", provider="mock", model="mock-m", metadata={})

    def _fail_graph(*args: object, **kwargs: object) -> None:
        raise AssertionError("run_vendor_ticket_demo must not run during controlled redraft")

    monkeypatch.setattr("app.review_queue.redraft_execution.generate_text", _mock_generate_text)
    monkeypatch.setattr("app.api.main.run_vendor_ticket_demo", _fail_graph)
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-no-graph",
            "action_type": "request_redraft",
            "execute": True,
            "comment": "Soften tone.",
            "workflow_state_snapshot": _safe_snapshot(),
        },
    )
    assert res.status_code == 200
    assert res.json()["execution_status"] == "pending_approval"


def test_endpoint_records_action_before_redraft(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = InMemoryReviewActionAdapter()

    def _mock_generate_text(*args: object, **kwargs: object) -> LLMResponse:
        _ = args, kwargs
        assert len(adapter.list_actions()) == 1
        return LLMResponse(content="پیش‌نویس.", provider="mock", model="mock-m", metadata={})

    monkeypatch.setattr("app.review_queue.redraft_execution.generate_text", _mock_generate_text)
    request = ReviewActionRequest(
        review_item_id="rid-record-order",
        action_type="request_redraft",
        comment="Add invoice request.",
        execute=True,
        workflow_state_snapshot=_safe_snapshot(),
    )
    response = _intake_review_action(request, adapter=adapter)
    assert response.execution_status == "pending_approval"
    assert len(adapter.list_actions()) == 1


def test_execute_controlled_redraft_unit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.review_queue.redraft_execution.generate_text",
        lambda *a, **k: LLMResponse(
            content="متن بازنگری.",
            provider="mock",
            model="mock-vendor-ticket-drafter",
            metadata={},
        ),
    )
    result = execute_controlled_redraft(
        operator_comment="Be more cautious.",
        workflow_state_snapshot=_safe_snapshot(),
        review_item_id="rid-unit",
        action_id="act-unit",
        operator_id="op-unit",
    )
    assert result.redraft_response == "متن بازنگری."
    assert result.redraft_summary["qa_issue_count"] >= 0
