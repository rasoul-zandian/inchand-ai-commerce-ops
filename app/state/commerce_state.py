"""Shared LangGraph state contract for Inchand AI commerce workflows."""

from typing import Any, TypedDict

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

    retrieved_context: dict[str, Any]
    rag_sources: list[RAGSource]

    tool_results: dict[str, Any]
    specialist_output: dict[str, Any]

    risk_score: float | None
    confidence_score: float | None

    recommended_action: str | None
    human_approval_required: bool
    approval_status: ApprovalStatus

    final_response: str | None

    errors: list[ToolError]
    audit_log: list[AuditLogEntry]
