"""Aggregate-safe models for shadow vendor-ticket AI operational assist (HITL-only)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class VendorTicketAIAssistSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VendorTicketAIAssistActionType(StrEnum):
    MONITOR = "monitor"
    ROUTE_REVIEW = "route_review"
    ESCALATE = "escalate"
    BILLING_REVIEW = "billing_review"
    DUPLICATE_CHECK = "duplicate_check"


class VendorTicketAIAssistSuggestion(BaseModel):
    """Single operator-facing assist hint (no retrieval content or customer text)."""

    model_config = ConfigDict(extra="forbid")

    action_type: VendorTicketAIAssistActionType
    severity: VendorTicketAIAssistSeverity
    summary: str = Field(..., max_length=240)
    reason_codes: list[str] = Field(default_factory=list, max_length=8)


class VendorTicketAIAssistResult(BaseModel):
    """Shadow AI assist output for HITL/operator review only."""

    model_config = ConfigDict(extra="forbid")

    suggested_priority: str = Field(..., max_length=32)
    escalation_recommended: bool
    duplicate_possible: bool
    suggested_action: VendorTicketAIAssistActionType
    retrieval_summary_available: bool
    confidence_band: str = Field(..., pattern=r"^(low|medium|high)$")
    assist_generated_at: str
    suggestions: list[VendorTicketAIAssistSuggestion] = Field(default_factory=list, max_length=6)
    assist_shadow_only: bool = True
    human_review_required: bool = True
    retrieval_activated: bool = False
    downstream_consumed_retrieval: bool = False

    @staticmethod
    def utc_timestamp() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
