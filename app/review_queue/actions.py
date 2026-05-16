"""Operator review action contract (validation only; no execution)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator

_EXCLUDED_METADATA_KEYS = frozenset(
    {
        "draft_response",
        "final_response",
        "api_key",
        "secret",
        "retrieved_context",
        "tool_results",
        "specialist_output",
        "rag_sources",
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewActionType(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CLARIFICATION = "request_clarification"
    REQUEST_REDRAFT = "request_redraft"


class OperatorReviewActionValidationError(ValueError):
    """Raised when an operator action fails contract validation."""


class OperatorReviewAction(BaseModel):
    """Typed operator decision on a review queue item (no side effects)."""

    action_id: str
    review_item_id: str
    action_type: ReviewActionType
    operator_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    comment: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _reject_excluded_metadata_keys(cls, value: dict[str, Any]) -> dict[str, Any]:
        for key in value:
            if key in _EXCLUDED_METADATA_KEYS:
                raise ValueError(f"metadata must not include excluded key: {key}")
        return value


def compact_operator_action_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Keep operator metadata operational; strip excluded keys if present."""
    if not metadata:
        return {}
    compact = {k: v for k, v in metadata.items() if k not in _EXCLUDED_METADATA_KEYS}
    for key in compact:
        if key in _EXCLUDED_METADATA_KEYS:
            raise ValueError(f"metadata must not include excluded key: {key}")
    return compact


def validate_operator_review_action(action: OperatorReviewAction) -> None:
    """Deterministic validation for operator actions (no LLM, no execution)."""
    comment = (action.comment or "").strip()
    if action.action_type == ReviewActionType.REQUEST_CLARIFICATION and not comment:
        raise OperatorReviewActionValidationError(
            "REQUEST_CLARIFICATION requires a non-empty comment describing what to clarify."
        )
    if action.action_type == ReviewActionType.REQUEST_REDRAFT and comment and len(comment) < 3:
        raise OperatorReviewActionValidationError(
            "REQUEST_REDRAFT comment must be at least 3 characters when provided."
        )


def build_operator_review_action(
    *,
    review_item_id: str,
    action_type: ReviewActionType | str,
    operator_id: str | None = None,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
    action_id: str | None = None,
    created_at: datetime | None = None,
    validate: bool = True,
) -> OperatorReviewAction:
    """Factory for operator review actions with generated id and UTC timestamp."""
    if isinstance(action_type, str):
        try:
            action_type = ReviewActionType(action_type)
        except ValueError as exc:
            raise OperatorReviewActionValidationError(
                f"Invalid action_type: {action_type!r}"
            ) from exc

    action = OperatorReviewAction(
        action_id=action_id or str(uuid.uuid4()),
        review_item_id=review_item_id,
        action_type=action_type,
        operator_id=operator_id,
        created_at=created_at or _utc_now(),
        comment=comment,
        metadata=compact_operator_action_metadata(metadata),
    )
    if validate:
        validate_operator_review_action(action)
    return action
