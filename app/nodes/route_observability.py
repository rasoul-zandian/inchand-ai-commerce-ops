"""LangGraph observability nodes for post-vendor-ticket conditional routing."""

from __future__ import annotations

from typing import Any, cast

from app.state.commerce_state import CommerceAIState

from .common import _append_audit, _state_dict


def route_after_vendor_ticket(state: CommerceAIState) -> str:
    """Map structured ``route_label`` to observability node name (no behavior change)."""
    label = state.get("route_label") or ""
    if label == "qa_attention":
        return "qa_attention_review"
    if label == "escalation_review":
        return "escalation_review"
    if label == "billing_review":
        return "billing_review"
    if label == "style_guidance":
        return "style_guidance_review"
    return "general_vendor_review"


def _route_observability_node(
    state: CommerceAIState,
    *,
    node_name: str,
    message: str,
) -> CommerceAIState:
    data = _state_dict(state)
    metadata: dict[str, Any] = {
        "route_label": data.get("route_label"),
        "routing_reasons": list(data.get("routing_reasons") or []),
        "qa_issue_count": len(data.get("qa_issues") or []),
        "qa_warning_count": len(data.get("qa_warnings") or []),
        "specialist_recommended_action": data.get("specialist_recommended_action"),
    }
    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name=node_name,
        message=message,
        metadata=metadata,
    )
    return cast(CommerceAIState, data)


def qa_attention_review_node(state: CommerceAIState) -> CommerceAIState:
    """Surface QA issues in audit/state before validation; does not revise the draft."""
    data = _state_dict(state)
    qa_issues = list(data.get("qa_issues") or [])
    metadata: dict[str, Any] = {
        "route_label": data.get("route_label"),
        "qa_passed": data.get("qa_passed"),
        "qa_issue_count": len(qa_issues),
        "qa_warning_count": len(data.get("qa_warnings") or []),
        "qa_issues": qa_issues,
        "specialist_recommended_action": data.get("specialist_recommended_action"),
    }
    data["qa_requires_human_attention"] = True
    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="qa_attention_review",
        message="QA attention route reviewed before validation.",
        metadata=metadata,
    )
    return cast(CommerceAIState, data)


def escalation_review_node(state: CommerceAIState) -> CommerceAIState:
    return _route_observability_node(
        state,
        node_name="escalation_review",
        message="Observability: escalation / SLA route.",
    )


def billing_review_node(state: CommerceAIState) -> CommerceAIState:
    return _route_observability_node(
        state,
        node_name="billing_review",
        message="Observability: billing discrepancy route.",
    )


def style_guidance_review_node(state: CommerceAIState) -> CommerceAIState:
    return _route_observability_node(
        state,
        node_name="style_guidance_review",
        message="Observability: style / tone guidance route.",
    )


def general_vendor_review_node(state: CommerceAIState) -> CommerceAIState:
    return _route_observability_node(
        state,
        node_name="general_vendor_review",
        message="Observability: general vendor support route.",
    )
