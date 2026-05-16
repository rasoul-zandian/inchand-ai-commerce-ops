"""Tests for operator review action contract (schema-only)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from app.review_queue.actions import (
    OperatorReviewAction,
    OperatorReviewActionValidationError,
    ReviewActionType,
    build_operator_review_action,
    validate_operator_review_action,
)
from pydantic import ValidationError


def test_operator_review_action_model_creation() -> None:
    action = OperatorReviewAction(
        action_id="act-1",
        review_item_id="rid-1",
        action_type=ReviewActionType.APPROVE,
        operator_id="op-42",
        comment=None,
        metadata={"source": "unit_test"},
    )
    assert action.action_id == "act-1"
    assert action.action_type == ReviewActionType.APPROVE
    assert action.created_at.tzinfo is not None


def test_build_operator_review_action_generates_id_and_timestamp() -> None:
    action = build_operator_review_action(
        review_item_id="rid-2",
        action_type=ReviewActionType.REJECT,
        operator_id="op-1",
        comment="Policy mismatch on settlement timeline.",
    )
    assert action.action_id
    assert action.review_item_id == "rid-2"
    assert action.action_type == ReviewActionType.REJECT
    assert action.comment == "Policy mismatch on settlement timeline."
    assert action.created_at.tzinfo == UTC


def test_approve_allows_empty_comment() -> None:
    action = build_operator_review_action(
        review_item_id="rid-3",
        action_type=ReviewActionType.APPROVE,
    )
    validate_operator_review_action(action)
    assert action.comment is None


def test_request_clarification_requires_comment() -> None:
    with pytest.raises(OperatorReviewActionValidationError, match="REQUEST_CLARIFICATION"):
        build_operator_review_action(
            review_item_id="rid-4",
            action_type=ReviewActionType.REQUEST_CLARIFICATION,
        )


def test_request_clarification_preserves_comment() -> None:
    action = build_operator_review_action(
        review_item_id="rid-5",
        action_type=ReviewActionType.REQUEST_CLARIFICATION,
        comment="Please confirm invoice period.",
    )
    assert action.comment == "Please confirm invoice period."


def test_request_redraft_allows_optional_comment() -> None:
    action = build_operator_review_action(
        review_item_id="rid-6",
        action_type=ReviewActionType.REQUEST_REDRAFT,
    )
    validate_operator_review_action(action)
    assert action.comment is None


def test_invalid_action_type_rejected() -> None:
    with pytest.raises(OperatorReviewActionValidationError, match="Invalid action_type"):
        build_operator_review_action(
            review_item_id="rid-7",
            action_type="auto_approve",
        )


def test_invalid_enum_value_rejected_by_model() -> None:
    with pytest.raises(ValidationError):
        OperatorReviewAction(
            action_id="act-bad",
            review_item_id="rid-8",
            action_type="not_a_real_action",  # type: ignore[arg-type]
        )


def test_metadata_excludes_draft_and_secrets() -> None:
    with pytest.raises(ValidationError, match="excluded key"):
        OperatorReviewAction(
            action_id="act-meta",
            review_item_id="rid-9",
            action_type=ReviewActionType.APPROVE,
            metadata={"draft_response": "secret draft"},
        )

    action = build_operator_review_action(
        review_item_id="rid-10",
        action_type=ReviewActionType.APPROVE,
        metadata={"routing_tag": "billing"},
    )
    dumped = json.dumps(action.model_dump(mode="json"))
    assert "draft_response" not in dumped
    assert action.metadata == {"routing_tag": "billing"}


def test_request_redraft_short_comment_rejected() -> None:
    with pytest.raises(OperatorReviewActionValidationError, match="at least 3 characters"):
        build_operator_review_action(
            review_item_id="rid-11",
            action_type=ReviewActionType.REQUEST_REDRAFT,
            comment="no",
        )


def test_build_with_explicit_timestamp() -> None:
    ts = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    action = build_operator_review_action(
        review_item_id="rid-12",
        action_type=ReviewActionType.APPROVE,
        created_at=ts,
        action_id="act-fixed",
    )
    assert action.created_at == ts
    assert action.action_id == "act-fixed"
