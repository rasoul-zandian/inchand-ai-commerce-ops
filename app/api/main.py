"""FastAPI boundary for the vendor ticket LangGraph workflow (thin orchestration only)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.graph.main_graph import run_vendor_ticket_demo
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
    errors: list[dict[str, Any]] = Field(default_factory=list)
    audit_log: list[dict[str, Any]] = Field(default_factory=list)


def _serialize_state(state: CommerceAIState) -> VendorTicketRunResponse:
    errors = [e.model_dump(mode="json") if isinstance(e, ToolError) else dict(e) for e in state["errors"]]
    audit_log = [
        a.model_dump(mode="json") if isinstance(a, AuditLogEntry) else dict(a) for a in state["audit_log"]
    ]
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
        tool_results=dict(state.get("tool_results") or {}),
        errors=errors,
        audit_log=audit_log,
    )


app = FastAPI(title="Inchand AI Commerce Operations Copilot", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "inchand-ai-commerce-ops"}


@app.post("/run-vendor-ticket", response_model=VendorTicketRunResponse)
def run_vendor_ticket(request: VendorTicketRunRequest) -> VendorTicketRunResponse:
    state = run_vendor_ticket_demo(user_input=request.user_input, ticket_id=request.ticket_id)
    return _serialize_state(state)
