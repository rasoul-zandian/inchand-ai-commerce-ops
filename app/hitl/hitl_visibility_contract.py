"""Read-only HITL visibility contract models (governance only; no UI implementation)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

# --- Allowlisted aggregate fields (v1) ---

AI_ASSIST_VISIBLE_FIELDS = frozenset(
    {
        "ai_assist_shadow_generated",
        "ai_assist_suggested_priority",
        "ai_assist_escalation_recommended",
        "ai_assist_duplicate_possible",
        "ai_assist_suggested_action",
        "ai_assist_suggested_action_reason",
        "ai_assist_confidence_band",
        "ai_assist_human_review_required",
        "ai_assist_shadow_only",
        "seller_notification_detected",
        "seller_intent_type",
        "seller_notification_type",
        "seller_operational_request_type",
        "extracted_order_id",
        "extracted_order_ids",
        "extracted_tracking_code",
        "extracted_product_ids",
        "extracted_tracking_carrier",
        "entity_warnings_summary",
        "seller_notification_shipment_status",
        "detected_intent",
        "intent_confidence_band",
        "intent_reasons_summary",
        "intent_related_document_types",
    },
)

RETRIEVAL_METADATA_VISIBLE_FIELDS = frozenset(
    {
        "retrieval_gate_decision",
        "retrieval_scenario",
        "retrieval_result_count",
        "retrieval_metadata_filter",
        "retrieval_sandbox_only",
        "retrieval_activated",
    },
)

TICKET_METADATA_VISIBLE_FIELDS = frozenset(
    {
        "room_id",
        "ticket_label",
        "route_label",
        "review_priority",
        "assigned_department",
    },
)

TICKET_TEXT_PREVIEW_VISIBLE_FIELDS = frozenset({"ticket_text_preview"})

OPEN_TICKET_SNAPSHOT_VISIBLE_FIELDS = frozenset(
    {
        "open_ticket_preview",
        "original_vendor_issue_preview",
        "latest_vendor_message",
        "recent_context_preview",
    },
)

ALLOWED_HITL_VISIBLE_FIELDS = (
    AI_ASSIST_VISIBLE_FIELDS
    | RETRIEVAL_METADATA_VISIBLE_FIELDS
    | TICKET_METADATA_VISIBLE_FIELDS
    | TICKET_TEXT_PREVIEW_VISIBLE_FIELDS
    | OPEN_TICKET_SNAPSHOT_VISIBLE_FIELDS
)

FORBIDDEN_HITL_VISIBLE_FIELDS = frozenset(
    {
        "user_input",
        "query",
        "messages",
        "content",
        "transcript",
        "conversation_transcript",
        "raw_text",
        "results",
        "retrieved_context",
        "retrieval_query_hash",
        "retrieval_policy_reasons",
        "draft_response",
        "final_response",
        "customer_reply",
        "generated_response",
        "vector",
        "vectors",
        "embedding",
        "embeddings",
        "rag_sources",
        "specialist_output",
        "tool_results",
        "audit_log",
        "suggestions",
    },
)

ALLOWED_HITL_REVIEWER_ACTIONS = frozenset(
    {
        "view",
        "acknowledge",
        "mark_helpful",
        "mark_noisy",
        "request_human_followup",
        "add_internal_note",
    },
)

FORBIDDEN_HITL_REVIEWER_ACTIONS = frozenset(
    {
        "auto_send",
        "approve_customer_response",
        "modify_final_response",
        "trigger_retrieval",
        "override_policy_gate",
        "expose_externally",
        "draft_from_assist",
        "send_customer_message",
    },
)


class HITLVisibleField(StrEnum):
    """Aggregate fields that may appear in a read-only HITL payload."""

    AI_ASSIST_SHADOW_GENERATED = "ai_assist_shadow_generated"
    AI_ASSIST_SUGGESTED_PRIORITY = "ai_assist_suggested_priority"
    AI_ASSIST_ESCALATION_RECOMMENDED = "ai_assist_escalation_recommended"
    AI_ASSIST_DUPLICATE_POSSIBLE = "ai_assist_duplicate_possible"
    AI_ASSIST_SUGGESTED_ACTION = "ai_assist_suggested_action"
    AI_ASSIST_CONFIDENCE_BAND = "ai_assist_confidence_band"
    AI_ASSIST_HUMAN_REVIEW_REQUIRED = "ai_assist_human_review_required"
    AI_ASSIST_SHADOW_ONLY = "ai_assist_shadow_only"
    RETRIEVAL_GATE_DECISION = "retrieval_gate_decision"
    RETRIEVAL_SCENARIO = "retrieval_scenario"
    RETRIEVAL_RESULT_COUNT = "retrieval_result_count"
    RETRIEVAL_METADATA_FILTER = "retrieval_metadata_filter"
    RETRIEVAL_SANDBOX_ONLY = "retrieval_sandbox_only"
    RETRIEVAL_ACTIVATED = "retrieval_activated"
    ROOM_ID = "room_id"
    TICKET_LABEL = "ticket_label"
    ROUTE_LABEL = "route_label"
    REVIEW_PRIORITY = "review_priority"
    ASSIGNED_DEPARTMENT = "assigned_department"
    TICKET_TEXT_PREVIEW = "ticket_text_preview"


class HITLForbiddenField(StrEnum):
    """Fields that must never appear in HITL visibility payloads."""

    USER_INPUT = "user_input"
    QUERY = "query"
    MESSAGES = "messages"
    CONTENT = "content"
    TRANSCRIPT = "transcript"
    RESULTS = "results"
    RETRIEVED_CONTEXT = "retrieved_context"
    RETRIEVAL_QUERY_HASH = "retrieval_query_hash"
    DRAFT_RESPONSE = "draft_response"
    FINAL_RESPONSE = "final_response"
    VECTOR = "vector"
    VECTORS = "vectors"
    EMBEDDING = "embedding"
    EMBEDDINGS = "embeddings"
    RAG_SOURCES = "rag_sources"
    SPECIALIST_OUTPUT = "specialist_output"
    TOOL_RESULTS = "tool_results"


class HITLReviewerAction(StrEnum):
    """Reviewer actions recorded by HITL tooling (audit only in v1)."""

    VIEW = "view"
    ACKNOWLEDGE = "acknowledge"
    MARK_HELPFUL = "mark_helpful"
    MARK_NOISY = "mark_noisy"
    REQUEST_HUMAN_FOLLOWUP = "request_human_followup"
    ADD_INTERNAL_NOTE = "add_internal_note"


class HITLVisibilityDecision(StrEnum):
    """Governance approval state for HITL read-only UI."""

    NOT_READY = "not_ready"
    READY_FOR_UI_REVIEW = "ready_for_ui_review"
    APPROVED_READ_ONLY = "approved_read_only"
    BLOCKED = "blocked"


class HITLReadOnlyVisibilityContract(BaseModel):
    """Checklist contract for whether read-only HITL UI may be implemented."""

    model_config = ConfigDict(extra="forbid")

    decision: HITLVisibilityDecision = HITLVisibilityDecision.NOT_READY
    visibility_mode: str = "read_only"
    customer_facing: bool = False
    auto_send_allowed: bool = False
    draft_consumption_allowed: bool = False
    retrieval_content_visible: bool = False
    human_review_required: bool = True
    contract_documented: bool = False
    metrics_report_reviewed: bool = False
    human_governance_signoff: bool = False
    rollback_plan_documented: bool = False
    feature_flag_default_off: bool = True

    @field_validator("visibility_mode")
    @classmethod
    def visibility_mode_must_be_read_only(cls, value: str) -> str:
        if value != "read_only":
            raise ValueError("visibility_mode must be read_only for this contract")
        return value


def _collect_keys(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            _collect_keys(child, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_keys(item, keys)


def assert_hitl_visible_payload_safe(payload: dict[str, Any]) -> None:
    """Fail closed if a HITL visibility payload contains forbidden or unknown keys."""
    from app.hitl.ticket_text_preview import assert_ticket_text_preview_safe

    keys: set[str] = set()
    _collect_keys(payload, keys)

    forbidden = keys.intersection(FORBIDDEN_HITL_VISIBLE_FIELDS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"HITL payload contains forbidden keys: {joined}")

    unknown = keys - ALLOWED_HITL_VISIBLE_FIELDS
    if unknown:
        joined = ", ".join(sorted(unknown))
        raise ValueError(f"HITL payload contains unsupported keys: {joined}")

    if payload.get("retrieval_activated") is True:
        raise ValueError("retrieval_activated must be false in HITL read-only payloads")

    preview = payload.get("ticket_text_preview")
    if preview is not None:
        if not isinstance(preview, str):
            raise ValueError("ticket_text_preview must be a string when present")
        assert_ticket_text_preview_safe(preview)

    if any(payload.get(field) is not None for field in OPEN_TICKET_SNAPSHOT_VISIBLE_FIELDS):
        from app.live_feed.open_ticket_snapshot import assert_open_ticket_snapshot_safe

        assert_open_ticket_snapshot_safe(
            {
                "original_vendor_issue_preview": payload.get("original_vendor_issue_preview"),
                "latest_vendor_message": payload.get("latest_vendor_message"),
                "recent_context_preview": payload.get("recent_context_preview"),
                "open_ticket_preview": payload.get("open_ticket_preview"),
            },
        )


def assert_hitl_reviewer_action_allowed(action: str) -> None:
    """Reject reviewer actions outside the read-only contract."""
    normalized = action.strip().lower()
    if normalized in FORBIDDEN_HITL_REVIEWER_ACTIONS:
        raise ValueError(f"HITL reviewer action forbidden: {normalized}")
    if normalized not in ALLOWED_HITL_REVIEWER_ACTIONS:
        raise ValueError(f"HITL reviewer action not allowlisted: {normalized}")


def hitl_visibility_ready_for_ui(contract: HITLReadOnlyVisibilityContract) -> bool:
    """True only when contract satisfies read-only HITL UI preconditions (no enablement)."""
    if contract.visibility_mode != "read_only":
        return False
    if contract.customer_facing:
        return False
    if contract.auto_send_allowed:
        return False
    if contract.draft_consumption_allowed:
        return False
    if contract.retrieval_content_visible:
        return False
    if not contract.human_review_required:
        return False
    return True
