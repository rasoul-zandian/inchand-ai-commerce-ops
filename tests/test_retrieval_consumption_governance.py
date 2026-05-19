"""Tests for non-shadow retrieval consumption governance plan helpers."""

from __future__ import annotations

import pytest
from app.corpus_planning.retrieval_consumption_governance import (
    RetrievalConsumptionDecision,
    RetrievalConsumptionReadinessPlan,
    retrieval_consumption_ready_for_hitl,
)
from pydantic import ValidationError


def _ready_plan(**overrides: object) -> RetrievalConsumptionReadinessPlan:
    base: dict[str, object] = {
        "status": RetrievalConsumptionDecision.READY_FOR_HITL_VISIBILITY_REVIEW,
        "shadow_metrics_reviewed": True,
        "shadow_replay_total_rows": 166,
        "shadow_retrieval_error_count": 0,
        "shadow_retrieval_activated_true_count": 0,
        "shadow_downstream_consumed_true_count": 0,
        "human_reviewer_signoff": True,
        "hitl_safe_output_contract_defined": True,
        "rollback_plan_documented": True,
        "production_or_customer_facing": False,
        "draft_assist_enabled": False,
        "autonomous_drafting_enabled": False,
        "unrestricted_vector_only": False,
    }
    base.update(overrides)
    return RetrievalConsumptionReadinessPlan.model_validate(base)


def test_ready_for_hitl_when_gates_satisfied() -> None:
    assert retrieval_consumption_ready_for_hitl(_ready_plan()) is True


def test_not_ready_when_shadow_metrics_not_reviewed() -> None:
    assert retrieval_consumption_ready_for_hitl(_ready_plan(shadow_metrics_reviewed=False)) is False


def test_not_ready_when_draft_assist_enabled() -> None:
    assert retrieval_consumption_ready_for_hitl(_ready_plan(draft_assist_enabled=True)) is False


def test_not_ready_when_production_or_customer_facing() -> None:
    plan = _ready_plan(production_or_customer_facing=True)
    assert retrieval_consumption_ready_for_hitl(plan) is False


def test_not_ready_when_status_blocked() -> None:
    assert (
        retrieval_consumption_ready_for_hitl(
            _ready_plan(status=RetrievalConsumptionDecision.BLOCKED),
        )
        is False
    )


def test_plan_rejects_nonzero_activated_count() -> None:
    with pytest.raises(ValidationError, match="retrieval_activated_true_count"):
        _ready_plan(shadow_retrieval_activated_true_count=1)
