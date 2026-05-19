"""Governance models for non-shadow retrieval consumption readiness.

Plan only; no runtime activation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator


class RetrievalConsumptionDecision(StrEnum):
    """Approval state for consuming sandbox retrieval metadata outside shadow mode."""

    NOT_READY = "not_ready"
    READY_FOR_HITL_VISIBILITY_REVIEW = "ready_for_hitl_visibility_review"
    APPROVED_FOR_HITL_VISIBILITY = "approved_for_hitl_visibility"
    BLOCKED = "blocked"


class RetrievalConsumptionReadinessPlan(BaseModel):
    """Checklist inputs for whether HITL-only visibility may be reviewed (not implemented)."""

    model_config = ConfigDict(extra="forbid")

    status: RetrievalConsumptionDecision = RetrievalConsumptionDecision.NOT_READY
    shadow_metrics_reviewed: bool = False
    shadow_replay_total_rows: int | None = None
    shadow_retrieval_error_count: int | None = None
    shadow_retrieval_activated_true_count: int | None = None
    shadow_downstream_consumed_true_count: int | None = None
    human_reviewer_signoff: bool = False
    hitl_safe_output_contract_defined: bool = False
    rollback_plan_documented: bool = False
    production_or_customer_facing: bool = False
    draft_assist_enabled: bool = False
    autonomous_drafting_enabled: bool = False
    unrestricted_vector_only: bool = False

    @field_validator("shadow_retrieval_activated_true_count")
    @classmethod
    def activated_must_be_zero_when_set(cls, value: int | None) -> int | None:
        if value is not None and value != 0:
            msg = "shadow_retrieval_activated_true_count must be 0 until explicitly approved"
            raise ValueError(msg)
        return value

    @field_validator("shadow_downstream_consumed_true_count")
    @classmethod
    def downstream_must_be_zero_when_set(cls, value: int | None) -> int | None:
        if value is not None and value != 0:
            msg = "shadow_downstream_consumed_true_count must be 0 until explicitly approved"
            raise ValueError(msg)
        return value


def retrieval_consumption_ready_for_hitl(plan: RetrievalConsumptionReadinessPlan) -> bool:
    """True only when plan satisfies HITL-only visibility review gates (does not enable runtime)."""
    if plan.status not in (
        RetrievalConsumptionDecision.READY_FOR_HITL_VISIBILITY_REVIEW,
        RetrievalConsumptionDecision.APPROVED_FOR_HITL_VISIBILITY,
    ):
        return False
    if not plan.shadow_metrics_reviewed:
        return False
    if not plan.human_reviewer_signoff:
        return False
    if not plan.hitl_safe_output_contract_defined:
        return False
    if not plan.rollback_plan_documented:
        return False
    if plan.production_or_customer_facing:
        return False
    if plan.draft_assist_enabled:
        return False
    if plan.autonomous_drafting_enabled:
        return False
    if plan.unrestricted_vector_only:
        return False
    if plan.shadow_retrieval_error_count is not None and plan.shadow_retrieval_error_count != 0:
        return False
    activated = plan.shadow_retrieval_activated_true_count
    if activated is not None and activated != 0:
        return False
    downstream = plan.shadow_downstream_consumed_true_count
    if downstream is not None and downstream != 0:
        return False
    return True
