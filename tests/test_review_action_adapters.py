"""Tests for review action persistence adapters."""

from __future__ import annotations

import pytest
from app.config import get_settings
from app.review_queue.action_adapters import (
    InMemoryReviewActionAdapter,
    NoOpReviewActionAdapter,
    ReviewActionAdapter,
    ReviewActionPersistenceError,
    get_review_action_adapter,
    reset_review_action_adapter_cache,
)
from app.review_queue.actions import ReviewActionType, build_operator_review_action


def test_noop_adapter_accepts_record_action() -> None:
    adapter = NoOpReviewActionAdapter()
    action = build_operator_review_action(
        review_item_id="rid-noop",
        action_type=ReviewActionType.APPROVE,
    )
    adapter.record_action(action)
    assert adapter.healthcheck() is True


def test_in_memory_adapter_stores_actions() -> None:
    adapter = InMemoryReviewActionAdapter()
    action = build_operator_review_action(
        review_item_id="rid-mem",
        action_type=ReviewActionType.REJECT,
        comment="Out of policy.",
    )
    adapter.record_action(action)
    stored = adapter.list_actions()
    assert len(stored) == 1
    assert stored[0].action_id == action.action_id
    adapter.clear()
    assert adapter.list_actions() == []


def test_factory_returns_noop_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REVIEW_ACTION_ADAPTER", raising=False)
    get_settings.cache_clear()
    reset_review_action_adapter_cache()
    adapter = get_review_action_adapter()
    assert isinstance(adapter, NoOpReviewActionAdapter)


def test_factory_memory_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_ACTION_ADAPTER", "memory")
    get_settings.cache_clear()
    reset_review_action_adapter_cache()
    adapter = get_review_action_adapter()
    assert isinstance(adapter, InMemoryReviewActionAdapter)


def test_factory_rejects_unknown_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_ACTION_ADAPTER", "postgres")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="Invalid REVIEW_ACTION_ADAPTER"):
        get_review_action_adapter()


class _FailingReviewActionAdapter:
    def record_action(self, action: object) -> None:
        _ = action
        raise ReviewActionPersistenceError("store unavailable")

    def healthcheck(self) -> bool:
        return False


def test_failing_adapter_is_review_action_adapter_shape() -> None:
    adapter = _FailingReviewActionAdapter()
    assert isinstance(adapter, ReviewActionAdapter)
