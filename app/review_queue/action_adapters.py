"""Persistence adapter boundary for operator review actions (no DB by default)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.config import get_settings
from app.review_queue.actions import OperatorReviewAction

_ALLOWED_REVIEW_ACTION_ADAPTERS = frozenset({"noop", "memory"})


class ReviewActionPersistenceError(RuntimeError):
    """Raised when a review action adapter cannot record an action."""


@runtime_checkable
class ReviewActionAdapter(Protocol):
    """Record accepted operator actions for future operator tooling."""

    def record_action(self, action: OperatorReviewAction) -> None:
        """Persist or hand off an accepted action (implementations plug in later)."""
        ...

    def healthcheck(self) -> bool:
        """Return True when the backing store is reachable."""
        ...


class NoOpReviewActionAdapter:
    """Default adapter: accepts record_action without external persistence."""

    def record_action(self, action: OperatorReviewAction) -> None:
        _ = action

    def healthcheck(self) -> bool:
        return True


class InMemoryReviewActionAdapter:
    """Test/dev adapter: stores actions in process memory only."""

    def __init__(self) -> None:
        self._actions: list[OperatorReviewAction] = []

    def record_action(self, action: OperatorReviewAction) -> None:
        self._actions.append(action)

    def healthcheck(self) -> bool:
        return True

    def list_actions(self) -> list[OperatorReviewAction]:
        return list(self._actions)

    def clear(self) -> None:
        self._actions.clear()


_memory_adapter: InMemoryReviewActionAdapter | None = None


def get_review_action_adapter() -> ReviewActionAdapter:
    """Return the configured review-action adapter (default: noop)."""
    name = get_settings().review_action_adapter.strip().lower()
    if name not in _ALLOWED_REVIEW_ACTION_ADAPTERS:
        allowed = ", ".join(sorted(_ALLOWED_REVIEW_ACTION_ADAPTERS))
        raise ValueError(f"Invalid REVIEW_ACTION_ADAPTER {name!r}; allowed values: {allowed}")
    if name == "memory":
        global _memory_adapter
        if _memory_adapter is None:
            _memory_adapter = InMemoryReviewActionAdapter()
        return _memory_adapter
    return NoOpReviewActionAdapter()


def reset_review_action_adapter_cache() -> None:
    """Clear in-memory adapter singleton (tests only)."""
    global _memory_adapter
    _memory_adapter = None
