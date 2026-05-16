"""In-memory no-op adapter for tests and default wiring."""

from __future__ import annotations

from app.review_queue.models import ReviewQueueItem


class NoOpReviewQueueAdapter:
    """Accepts enqueue calls without external persistence."""

    def enqueue_review_item(self, item: ReviewQueueItem) -> None:
        _ = item

    def healthcheck(self) -> bool:
        return True
