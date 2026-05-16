"""Tests for RedraftResult contract, hashing, and API audit exposure."""

from __future__ import annotations

import json

import pytest
from app.api.main import ReviewActionRequest, _intake_review_action
from app.llm.types import LLMResponse
from app.review_queue.redraft_execution import execute_controlled_redraft
from app.review_queue.redraft_models import (
    RedraftResult,
    build_redraft_result,
    hash_redraft_content,
)

from tests.test_controlled_redraft_execution import _safe_snapshot


def test_hash_redraft_content_deterministic() -> None:
    text = "پیش‌نویس نمونه"
    assert hash_redraft_content(text) == hash_redraft_content(text)
    assert len(hash_redraft_content(text)) == 64


def test_hashes_differ_when_drafts_differ() -> None:
    assert hash_redraft_content("draft a") != hash_redraft_content("draft b")


def test_redraft_result_model_creation() -> None:
    result = build_redraft_result(
        source_action_id="act-1",
        review_item_id="rid-1",
        previous_draft="old draft",
        redraft_text="new draft",
        operator_guidance="Soften tone.",
        qa_passed=True,
        qa_issue_count=0,
        llm_provider="mock",
        llm_model="mock-vendor-ticket-drafter",
        redraft_id="redraft-1",
    )
    assert isinstance(result, RedraftResult)
    assert result.redraft_id == "redraft-1"
    assert result.requires_human_approval is True
    assert result.metadata["audit"]["redraft_hash"] == result.redraft_hash


def test_response_includes_redraft_result_and_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.review_queue.redraft_execution.generate_text",
        lambda *a, **k: LLMResponse(
            content="پیش‌نویس بازنگری.",
            provider="mock",
            model="mock-vendor-ticket-drafter",
            metadata={},
        ),
    )
    response = _intake_review_action(
        ReviewActionRequest(
            review_item_id="rid-audit",
            action_type="request_redraft",
            comment="Remove guaranteed payment language.",
            execute=True,
            workflow_state_snapshot=_safe_snapshot(draft="پیش‌نویس قبلی"),
        ),
    )
    assert response.redraft_result is not None
    assert response.redraft_audit is not None
    assert response.redraft_result["redraft_id"]
    assert response.redraft_audit["previous_draft_hash"]
    assert response.redraft_audit["redraft_hash"]
    assert response.redraft_audit["source_action_id"] == response.action_id


def test_redraft_result_excludes_secrets_in_serialized_form() -> None:
    result = build_redraft_result(
        source_action_id="act-2",
        review_item_id="rid-2",
        previous_draft="old",
        redraft_text="new",
        operator_guidance="Fix tone",
        qa_passed=False,
        qa_issue_count=1,
        llm_provider="mock",
        llm_model="mock-m",
    )
    dumped = json.dumps(result.model_dump(mode="json"))
    assert "api_key" not in dumped
    assert "retrieved_context" not in dumped
    assert "old" not in dumped or "previous_draft_hash" in dumped


def test_execute_controlled_redraft_attaches_redraft_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.review_queue.redraft_execution.generate_text",
        lambda *a, **k: LLMResponse(
            content="متن جدید.",
            provider="mock",
            model="mock-m",
            metadata={},
        ),
    )
    outcome = execute_controlled_redraft(
        operator_comment="Be cautious.",
        workflow_state_snapshot=_safe_snapshot(),
        review_item_id="rid-unit",
        action_id="act-unit",
        operator_id="op-unit",
    )
    assert outcome.redraft_result is not None
    assert outcome.redraft_result.redraft_hash == hash_redraft_content("متن جدید.")
