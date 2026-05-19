"""Shared LangGraph state contract for Inchand AI commerce workflows."""

from typing import Any, NotRequired, TypedDict

from app.schemas.workflow import (
    ApprovalStatus,
    AuditLogEntry,
    EntityType,
    RAGSource,
    ToolError,
    WorkflowStatus,
    WorkflowType,
)


class CommerceAIState(TypedDict):
    """Typed state passed through the graph; all keys are part of the MVP contract."""

    request_id: str
    session_id: str | None
    user_id: str | None
    user_role: str | None

    user_input: str
    workflow_type: WorkflowType
    workflow_status: WorkflowStatus

    entity_type: EntityType
    product_id: str | None
    vendor_id: str | None
    ticket_id: str | None
    application_id: str | None

    room_id: str | None
    ticket_label: str | None
    ticket_subtype: str | None
    workflow_state_snapshot: dict[str, Any]

    retrieved_context: dict[str, Any]
    rag_sources: list[RAGSource]

    tool_results: dict[str, Any]
    specialist_output: dict[str, Any]

    risk_score: float | None
    confidence_score: float | None

    detected_intent: str | None
    grounding_summary: str | None
    grounding_sources: list[str]
    qa_passed: bool | None
    qa_issues: list[str]
    qa_warnings: list[str]
    qa_summary: str | None
    qa_requires_human_attention: bool
    route_label: str | None
    routing_reasons: list[str]
    specialist_recommended_action: str | None

    review_category: str | None
    review_priority: str | None
    review_reason: str | None

    recommended_action: str | None
    human_approval_required: bool
    approval_status: ApprovalStatus

    final_response: str | None

    errors: list[ToolError]
    audit_log: list[AuditLogEntry]

    # Additive sandbox retrieval fields (Step 130; optional — not set by default graph nodes)
    retrieval_gate_decision: NotRequired[str | None]
    retrieval_scenario: NotRequired[str | None]
    retrieval_policy_reasons: NotRequired[list[str]]
    retrieval_query_hash: NotRequired[str | None]
    retrieval_result_count: NotRequired[int | None]
    retrieval_metadata_filter: NotRequired[dict[str, str] | None]
    retrieval_sandbox_only: NotRequired[bool]
    retrieval_activated: NotRequired[bool]

    # Additive shadow AI assist fields (Step 146; optional — HITL metadata only)
    ai_assist_shadow_generated: NotRequired[bool]
    ai_assist_suggested_priority: NotRequired[str | None]
    ai_assist_escalation_recommended: NotRequired[bool | None]
    ai_assist_duplicate_possible: NotRequired[bool | None]
    ai_assist_suggested_action: NotRequired[str | None]
    ai_assist_confidence_band: NotRequired[str | None]
    ai_assist_human_review_required: NotRequired[bool]
    ai_assist_shadow_only: NotRequired[bool]
