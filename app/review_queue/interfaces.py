"""Adapter boundary for future review-queue persistence backends."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.review_queue.models import ReviewQueueItem


@runtime_checkable
class ReviewQueueAdapter(Protocol):
    """Enqueue review items for operator workflows (implementations plug in later)."""

    def enqueue_review_item(self, item: ReviewQueueItem) -> None:
        """Accept a review item for durable storage or downstream processing."""
        ...

    def healthcheck(self) -> bool:
        """Return True when the backing queue/store is reachable."""
        ...
