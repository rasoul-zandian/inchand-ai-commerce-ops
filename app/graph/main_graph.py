"""First executable LangGraph skeleton for the vendor ticket workflow (mock-only)."""

from __future__ import annotations

import uuid
from typing import cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langsmith import traceable

from app.nodes.common import (
    normalize_request,
    persist_trace,
    retrieve_context,
    risk_and_approval_decision,
    route_workflow,
    validate_output,
)
from app.nodes.vendor_ticket import vendor_ticket_node
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState


def build_graph() -> CompiledStateGraph[CommerceAIState]:
    """Compile the vendor ticket linear skeleton (no checkpointer)."""
    builder = StateGraph(CommerceAIState)

    builder.add_node("normalize_request", normalize_request)
    builder.add_node("route_workflow", route_workflow)
    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("vendor_ticket_node", vendor_ticket_node)
    builder.add_node("validate_output", validate_output)
    builder.add_node("risk_and_approval_decision", risk_and_approval_decision)
    builder.add_node("persist_trace", persist_trace)

    builder.add_edge(START, "normalize_request")
    builder.add_edge("normalize_request", "route_workflow")
    builder.add_edge("route_workflow", "retrieve_context")
    builder.add_edge("retrieve_context", "vendor_ticket_node")
    builder.add_edge("vendor_ticket_node", "validate_output")
    builder.add_edge("validate_output", "risk_and_approval_decision")
    builder.add_edge("risk_and_approval_decision", "persist_trace")
    builder.add_edge("persist_trace", END)

    return builder.compile()


graph = build_graph()


@traceable(
    name="run_vendor_ticket_demo",
    run_type="chain",
    tags=["inchand", "vendor_ticket", "mvp"],
    metadata={
        "workflow": "vendor_ticket",
        "system": "inchand-ai-commerce-ops",
    },
)
def run_vendor_ticket_demo(user_input: str, ticket_id: str | None = None) -> CommerceAIState:
    """Run the compiled graph with a minimal initial state (mock path)."""
    request_id = str(uuid.uuid4())
    initial: CommerceAIState = {
        "request_id": request_id,
        "session_id": None,
        "user_id": None,
        "user_role": None,
        "user_input": user_input,
        "workflow_type": WorkflowType.UNKNOWN,
        "workflow_status": WorkflowStatus.STARTED,
        "entity_type": EntityType.UNKNOWN,
        "product_id": None,
        "vendor_id": None,
        "ticket_id": ticket_id,
        "application_id": None,
        "retrieved_context": {},
        "rag_sources": [],
        "tool_results": {},
        "specialist_output": {},
        "risk_score": None,
        "confidence_score": None,
        "recommended_action": None,
        "human_approval_required": False,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "final_response": None,
        "errors": [],
        "audit_log": [],
    }
    result = graph.invoke(initial)
    return cast(CommerceAIState, result)
