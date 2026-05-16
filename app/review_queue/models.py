"""Pydantic models for review-queue persistence contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ReviewQueueItem(BaseModel):
    """Durable review-item snapshot for future operator queues (no draft text)."""

    review_item_id: str
    workflow_type: str
    workflow_run_id: str | None = None
    room_id: str | None = None
    review_category: str
    review_priority: str
    review_reason: str
    requires_human_approval: bool
    route_label: str | None = None
    qa_requires_attention: bool = False
    qa_issue_count: int = 0
    risk_score: float | None = None
    confidence_score: float | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
