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
    RECORD_UPDATE = "record_update"
    HUMAN_FOLLOWUP = "human_followup"
    REVIEW_PRODUCT_STATUS = "review_product_status"
    CHECK_ORDER_STATUS = "check_order_status"
    UPDATE_DELIVERY_STATUS = "update_delivery_status"
    CHECK_PRODUCT_APPROVAL = "check_product_approval"
    REVIEW_PRODUCT_EDIT = "review_product_edit"
    ANSWER_POLICY_QUESTION = "answer_policy_question"
    CHECK_RETURN_REQUEST = "check_return_request"
    REQUEST_MISSING_INFO = "request_missing_info"
    CHECK_SETTLEMENT_STATUS = "check_settlement_status"


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
    suggested_action_reason: str | None = Field(
        default=None,
        max_length=128,
        description="Short advisory reason for suggested_action (taxonomy v1).",
    )
    retrieval_summary_available: bool
    confidence_band: str = Field(..., pattern=r"^(low|medium|high)$")
    assist_generated_at: str
    suggestions: list[VendorTicketAIAssistSuggestion] = Field(default_factory=list, max_length=6)
    assist_shadow_only: bool = True
    human_review_required: bool = True
    retrieval_activated: bool = False
    downstream_consumed_retrieval: bool = False
    seller_notification_detected: bool = False
    seller_intent_type: str | None = Field(default=None, max_length=64)
    seller_notification_type: str | None = Field(default=None, max_length=64)
    seller_operational_request_type: str | None = Field(default=None, max_length=64)
    extracted_order_id: str | None = Field(default=None, max_length=32)
    extracted_order_ids: str | None = Field(
        default=None,
        max_length=128,
        description="Comma-separated safe order IDs (max 8).",
    )
    extracted_tracking_code: str | None = Field(default=None, max_length=32)
    extracted_product_ids: str | None = Field(
        default=None,
        max_length=128,
        description="Comma-separated safe product IDs (8 digits).",
    )
    extracted_tracking_carrier: str | None = Field(default=None, max_length=32)
    extracted_iban: str | None = Field(
        default=None,
        max_length=32,
        description="Normalized Sheba/IBAN (internal calibration; not for customer send).",
    )
    extracted_iban_masked: str | None = Field(
        default=None,
        max_length=48,
        description="Masked Sheba/IBAN when console masking is enabled.",
    )
    entity_warnings_summary: str | None = Field(default=None, max_length=128)
    seller_notification_shipment_status: str | None = Field(default=None, max_length=64)
    detected_intent: str | None = Field(default=None, max_length=64)
    intent_confidence_band: str | None = Field(default=None, pattern=r"^(low|medium|high)$")
    intent_reasons_summary: str | None = Field(default=None, max_length=128)
    intent_related_document_types: str | None = Field(
        default=None,
        max_length=128,
        description="Comma-separated knowledge document types for operator policy lookup.",
    )

    @staticmethod
    def utc_timestamp() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat()
