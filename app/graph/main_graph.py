"""First executable LangGraph skeleton for the vendor ticket workflow (mock-only)."""

from __future__ import annotations

import uuid
from typing import Any, cast

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
from app.nodes.route_observability import (
    billing_review_node,
    escalation_review_node,
    general_vendor_review_node,
    qa_attention_review_node,
    route_after_vendor_ticket,
    style_guidance_review_node,
)
from app.nodes.vendor_ticket import vendor_ticket_node
from app.schemas.workflow import ApprovalStatus, EntityType, WorkflowStatus, WorkflowType
from app.state.commerce_state import CommerceAIState


def build_graph() -> CompiledStateGraph[CommerceAIState]:
    """Compile vendor ticket graph with observability-only conditional routing."""
    builder = StateGraph(CommerceAIState)

    builder.add_node("normalize_request", normalize_request)
    builder.add_node("route_workflow", route_workflow)
    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("vendor_ticket_node", vendor_ticket_node)
    builder.add_node("qa_attention_review", qa_attention_review_node)
    builder.add_node("escalation_review", escalation_review_node)
    builder.add_node("billing_review", billing_review_node)
    builder.add_node("style_guidance_review", style_guidance_review_node)
    builder.add_node("general_vendor_review", general_vendor_review_node)
    builder.add_node("validate_output", validate_output)
    builder.add_node("risk_and_approval_decision", risk_and_approval_decision)
    builder.add_node("persist_trace", persist_trace)

    _route_targets = {
        "qa_attention_review": "qa_attention_review",
        "escalation_review": "escalation_review",
        "billing_review": "billing_review",
        "style_guidance_review": "style_guidance_review",
        "general_vendor_review": "general_vendor_review",
    }

    builder.add_edge(START, "normalize_request")
    builder.add_edge("normalize_request", "route_workflow")
    builder.add_edge("route_workflow", "retrieve_context")
    builder.add_edge("retrieve_context", "vendor_ticket_node")
    builder.add_conditional_edges(
        "vendor_ticket_node",
        route_after_vendor_ticket,
        _route_targets,
    )
    for route_node in _route_targets.values():
        builder.add_edge(route_node, "validate_output")
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
def run_vendor_ticket_demo(
    user_input: str,
    ticket_id: str | None = None,
    *,
    room_id: str | None = None,
    ticket_label: str | None = None,
    ticket_subtype: str | None = None,
    workflow_state_snapshot: dict[str, Any] | None = None,
) -> CommerceAIState:
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
        "room_id": room_id,
        "ticket_label": ticket_label,
        "ticket_subtype": ticket_subtype,
        "workflow_state_snapshot": dict(workflow_state_snapshot or {}),
        "retrieved_context": {},
        "rag_sources": [],
        "tool_results": {},
        "specialist_output": {},
        "risk_score": None,
        "confidence_score": None,
        "detected_intent": None,
        "grounding_summary": None,
        "grounding_sources": [],
        "qa_passed": None,
        "qa_issues": [],
        "qa_warnings": [],
        "qa_summary": None,
        "qa_requires_human_attention": False,
        "route_label": None,
        "routing_reasons": [],
        "specialist_recommended_action": None,
        "review_category": None,
        "review_priority": None,
        "review_reason": None,
        "recommended_action": None,
        "human_approval_required": False,
        "approval_status": ApprovalStatus.NOT_REQUIRED,
        "final_response": None,
        "errors": [],
        "audit_log": [],
    }
    result = graph.invoke(initial)
    return cast(CommerceAIState, result)
