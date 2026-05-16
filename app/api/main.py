"""FastAPI boundary for the vendor ticket LangGraph workflow (thin orchestration only)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError

from app.graph.main_graph import run_vendor_ticket_demo
from app.nodes.vendor_ticket import build_qa_attention_summary, build_review_queue_metadata
from app.review_queue.action_adapters import (
    ReviewActionAdapter,
    ReviewActionPersistenceError,
    get_review_action_adapter,
)
from app.review_queue.actions import (
    OperatorReviewActionValidationError,
    ReviewActionType,
    build_operator_review_action,
)
from app.review_queue.redraft_execution import (
    ControlledRedraftExecutionError,
    ControlledRedraftValidationError,
    execute_controlled_redraft,
)
from app.schemas.workflow import AuditLogEntry, ToolError
from app.state.commerce_state import CommerceAIState

# Future: authentication (API keys, OAuth2, session).
# Future: role-based access control (marketplace admin vs vendor vs read-only).
# Future: real persistence (PostgreSQL, audit store, idempotency keys).
# Future: LangSmith tracing (LANGSMITH_* env, run metadata, feedback).
# Future: real ticket service integration (read/update tickets, never auto-send without approval).


class VendorTicketRunRequest(BaseModel):
    user_input: str
    ticket_id: str | None = None
    room_id: str | None = None
    ticket_label: str | None = None
    ticket_subtype: str | None = None
    workflow_state_snapshot: dict[str, Any] = Field(default_factory=dict)


class ReviewActionRequest(BaseModel):
    review_item_id: str
    action_type: ReviewActionType
    operator_id: str | None = None
    comment: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    execute: bool = False
    workflow_state_snapshot: dict[str, Any] = Field(default_factory=dict)


class ReviewActionResponse(BaseModel):
    accepted: bool
    action_id: str
    review_item_id: str
    action_type: str
    execution_status: str = "not_executed"
    message: str
    validation_errors: list[str] = Field(default_factory=list)
    redraft_response: str | None = None
    redraft_summary: dict[str, Any] = Field(default_factory=dict)
    redraft_result: dict[str, Any] | None = None
    redraft_audit: dict[str, Any] | None = None


class VendorTicketRunResponse(BaseModel):
    request_id: str
    session_id: str | None
    workflow_type: str
    workflow_status: str
    approval_status: str
    human_approval_required: bool
    recommended_action: str | None
    final_response: str | None
    specialist_output: dict[str, Any]
    tool_results: dict[str, Any]
    retrieval_summary: dict[str, Any] = Field(default_factory=dict)
    qa_attention_summary: dict[str, Any] = Field(default_factory=dict)
    review_queue_metadata: dict[str, Any] = Field(default_factory=dict)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    audit_log: list[dict[str, Any]] = Field(default_factory=list)


_RETRIEVAL_SUMMARY_KEYS = (
    "requested_strategy",
    "effective_strategy",
    "provider",
    "count",
    "top_k",
    "embedding_provider",
    "embedding_model",
    "rag_profile",
    "vector_store_provider",
    "pgvector_table",
    "pgvector_dimensions",
)


def _retrieval_summary_from_tool_results(tool_results: dict[str, Any]) -> dict[str, Any]:
    """Build a safe, non-secret retrieval summary for API responses."""
    rwf = tool_results.get("retrieve_for_workflow")
    if not isinstance(rwf, dict) or not rwf:
        return {}
    summary = {key: rwf[key] for key in _RETRIEVAL_SUMMARY_KEYS if key in rwf}
    if "effective_strategy" not in summary and "strategy" in rwf:
        summary["effective_strategy"] = rwf["strategy"]
    if "requested_strategy" not in summary and "strategy" in rwf:
        summary["requested_strategy"] = rwf["strategy"]
    return summary


def _serialize_state(state: CommerceAIState) -> VendorTicketRunResponse:
    errors = [
        e.model_dump(mode="json") if isinstance(e, ToolError) else dict(e) for e in state["errors"]
    ]
    audit_log = [
        a.model_dump(mode="json") if isinstance(a, AuditLogEntry) else dict(a)
        for a in state["audit_log"]
    ]
    tool_results = dict(state.get("tool_results") or {})
    return VendorTicketRunResponse(
        request_id=state["request_id"],
        session_id=state["session_id"],
        workflow_type=str(state["workflow_type"]),
        workflow_status=str(state["workflow_status"]),
        approval_status=str(state["approval_status"]),
        human_approval_required=state["human_approval_required"],
        recommended_action=state["recommended_action"],
        final_response=state["final_response"],
        specialist_output=dict(state.get("specialist_output") or {}),
        tool_results=tool_results,
        retrieval_summary=_retrieval_summary_from_tool_results(tool_results),
        qa_attention_summary=build_qa_attention_summary(state),
        review_queue_metadata=build_review_queue_metadata(state),
        errors=errors,
        audit_log=audit_log,
    )


app = FastAPI(title="Inchand AI Commerce Operations Copilot", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "inchand-ai-commerce-ops"}


def _validation_http_exception(errors: list[str]) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"validation_errors": errors},
    )


def _intake_review_action(
    request: ReviewActionRequest,
    adapter: ReviewActionAdapter | None = None,
) -> ReviewActionResponse:
    """Validate operator action; optionally run controlled redraft execution."""
    if request.execute and request.action_type != ReviewActionType.REQUEST_REDRAFT:
        raise _validation_http_exception(
            ["Only request_redraft supports execution in this version."]
        )
    if request.execute and request.action_type == ReviewActionType.REQUEST_REDRAFT:
        comment = (request.comment or "").strip()
        if not comment:
            raise _validation_http_exception(
                ["Controlled redraft execution requires a non-empty operator comment."]
            )

    try:
        action = build_operator_review_action(
            review_item_id=request.review_item_id,
            action_type=request.action_type,
            operator_id=request.operator_id,
            comment=request.comment,
            metadata=request.metadata,
        )
    except OperatorReviewActionValidationError as exc:
        raise _validation_http_exception([str(exc)]) from exc
    except ValidationError as exc:
        raise _validation_http_exception(
            [f"{err['loc']}: {err['msg']}" for err in exc.errors()]
        ) from exc

    record_adapter = adapter or get_review_action_adapter()
    try:
        record_adapter.record_action(action)
    except ReviewActionPersistenceError as exc:
        raise HTTPException(
            status_code=500,
            detail={"message": "Failed to record review action.", "error": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"message": "Failed to record review action."},
        ) from exc

    if not request.execute:
        return ReviewActionResponse(
            accepted=True,
            action_id=action.action_id,
            review_item_id=action.review_item_id,
            action_type=action.action_type.value,
            execution_status="not_executed",
            message="Review action accepted; execution not performed.",
        )

    try:
        redraft = execute_controlled_redraft(
            operator_comment=request.comment or "",
            workflow_state_snapshot=request.workflow_state_snapshot,
            review_item_id=action.review_item_id,
            action_id=action.action_id,
            operator_id=action.operator_id,
        )
    except ControlledRedraftValidationError as exc:
        raise _validation_http_exception([str(exc)]) from exc
    except ControlledRedraftExecutionError as exc:
        return ReviewActionResponse(
            accepted=False,
            action_id=action.action_id,
            review_item_id=action.review_item_id,
            action_type=action.action_type.value,
            execution_status="failed",
            message=str(exc),
            validation_errors=[str(exc)],
        )

    redraft_result_payload = (
        redraft.redraft_result.model_dump(mode="json") if redraft.redraft_result else None
    )
    redraft_audit_payload = None
    if redraft.redraft_result is not None:
        audit_meta = redraft.redraft_result.metadata.get("audit")
        redraft_audit_payload = audit_meta if isinstance(audit_meta, dict) else None

    return ReviewActionResponse(
        accepted=True,
        action_id=action.action_id,
        review_item_id=action.review_item_id,
        action_type=action.action_type.value,
        execution_status="pending_approval",
        message="Controlled redraft completed; human approval still required.",
        redraft_response=redraft.redraft_response,
        redraft_summary=redraft.redraft_summary,
        redraft_result=redraft_result_payload,
        redraft_audit=redraft_audit_payload,
    )


@app.post("/review-actions", response_model=ReviewActionResponse)
def intake_review_action(request: ReviewActionRequest) -> ReviewActionResponse:
    return _intake_review_action(request)


@app.post("/run-vendor-ticket", response_model=VendorTicketRunResponse)
def run_vendor_ticket(request: VendorTicketRunRequest) -> VendorTicketRunResponse:
    state = run_vendor_ticket_demo(
        user_input=request.user_input,
        ticket_id=request.ticket_id,
        room_id=request.room_id,
        ticket_label=request.ticket_label,
        ticket_subtype=request.ticket_subtype,
        workflow_state_snapshot=request.workflow_state_snapshot,
    )
    return _serialize_state(state)
