"""Tests for review action intake API (accept-only; no execution)."""

from __future__ import annotations

import json

import pytest
from app.api.main import ReviewActionRequest, _intake_review_action, app
from app.review_queue.action_adapters import (
    InMemoryReviewActionAdapter,
    ReviewActionPersistenceError,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_approve_accepted_not_executed(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-approve-1",
            "action_type": "approve",
            "operator_id": "op-1",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body["execution_status"] == "not_executed"
    assert body["action_id"]
    assert body["review_item_id"] == "rid-approve-1"
    assert body["action_type"] == "approve"
    assert body["validation_errors"] == []


def test_request_redraft_accepted_not_executed(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-redraft-1",
            "action_type": "request_redraft",
            "comment": "Tone down settlement certainty.",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["accepted"] is True
    assert body["execution_status"] == "not_executed"


def test_request_clarification_without_comment_rejected(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-clarify-1",
            "action_type": "request_clarification",
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "validation_errors" in detail
    assert any("REQUEST_CLARIFICATION" in err for err in detail["validation_errors"])


def test_invalid_action_type_rejected(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-bad-type",
            "action_type": "auto_approve",
        },
    )
    assert res.status_code == 422


def test_excluded_metadata_keys_stripped_from_intake(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-meta-1",
            "action_type": "approve",
            "metadata": {"draft_response": "secret draft", "source_panel": "ops"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("redraft_response") is None
    dumped = json.dumps(body)
    assert "secret draft" not in dumped


def test_safe_metadata_accepted(client: TestClient) -> None:
    res = client.post(
        "/review-actions",
        json={
            "review_item_id": "rid-meta-2",
            "action_type": "approve",
            "metadata": {"source_panel": "operator_console"},
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body.get("redraft_response") is None
    assert "sk-" not in json.dumps(body)


def test_intake_does_not_run_vendor_ticket_graph(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("run_vendor_ticket_demo must not be called by /review-actions")

    monkeypatch.setattr("app.api.main.run_vendor_ticket_demo", _fail_if_called)
    res = client.post(
        "/review-actions",
        json={"review_item_id": "rid-no-graph", "action_type": "approve"},
    )
    assert res.status_code == 200


def test_endpoint_records_action_via_adapter() -> None:
    adapter = InMemoryReviewActionAdapter()
    request = ReviewActionRequest(
        review_item_id="rid-record-1",
        action_type="approve",
        operator_id="op-9",
    )
    response = _intake_review_action(request, adapter=adapter)
    assert response.accepted is True
    assert response.execution_status == "not_executed"
    assert len(adapter.list_actions()) == 1
    assert adapter.list_actions()[0].review_item_id == "rid-record-1"


def test_adapter_failure_returns_500() -> None:
    class _FailingAdapter:
        def record_action(self, action: object) -> None:
            _ = action
            raise ReviewActionPersistenceError("disk full")

        def healthcheck(self) -> bool:
            return False

    request = ReviewActionRequest(review_item_id="rid-fail", action_type="approve")
    with pytest.raises(HTTPException) as exc_info:
        _intake_review_action(request, adapter=_FailingAdapter())
    assert exc_info.value.status_code == 500


def test_vendor_ticket_endpoint_unchanged(client: TestClient) -> None:
    res = client.post(
        "/run-vendor-ticket",
        json={"user_input": "سلام", "ticket_id": "t-intake-unchanged"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["human_approval_required"] is True
    assert "review_queue_metadata" in body
