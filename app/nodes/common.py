"""Shared LangGraph nodes: normalization, routing, retrieval, validation, risk, trace."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from app.schemas.workflow import (
    ApprovalStatus,
    AuditLogEntry,
    EntityType,
    ToolError,
    WorkflowStatus,
    WorkflowType,
)
from app.state.commerce_state import CommerceAIState
from app.tools.mock_tools import (
    get_ticket,
    get_vendor_profile,
    search_previous_ticket_responses,
    search_support_policy,
)


def _append_audit(
    existing: Sequence[AuditLogEntry],
    *,
    node_name: str,
    message: str,
    metadata: dict[str, Any] | None = None,
) -> list[AuditLogEntry]:
    return [
        *existing,
        AuditLogEntry(
            node_name=node_name,
            message=message,
            metadata=dict(metadata or {}),
        ),
    ]


def _append_errors(
    existing: Sequence[ToolError],
    *errors: ToolError,
) -> list[ToolError]:
    return [*existing, *errors]


def _state_dict(state: CommerceAIState) -> dict[str, Any]:
    return dict(state)


def normalize_request(state: CommerceAIState) -> CommerceAIState:
    """Ensure identifiers exist, mark workflow in progress, and record audit."""
    data = _state_dict(state)
    request_id = (data.get("request_id") or "").strip() or str(uuid.uuid4())
    session_raw = data.get("session_id")
    session_id = session_raw if (session_raw is not None and str(session_raw).strip()) else request_id

    data["request_id"] = request_id
    data["session_id"] = session_id
    data["workflow_status"] = WorkflowStatus.IN_PROGRESS
    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="normalize_request",
        message="Request normalized; workflow marked in progress.",
        metadata={"request_id": request_id, "session_id": session_id},
    )
    return cast(CommerceAIState, data)


def route_workflow(state: CommerceAIState) -> CommerceAIState:
    """Step 3: always route to vendor ticket workflow."""
    data = _state_dict(state)
    data["workflow_type"] = WorkflowType.VENDOR_TICKET
    data["entity_type"] = EntityType.TICKET
    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="route_workflow",
        message="Routed to vendor ticket workflow.",
        metadata={"workflow_type": WorkflowType.VENDOR_TICKET.value},
    )
    return cast(CommerceAIState, data)


def retrieve_context(state: CommerceAIState) -> CommerceAIState:
    """Load context via mock tools (no real integrations)."""
    data = _state_dict(state)
    ticket_id = (data.get("ticket_id") or "").strip() or "demo-ticket-001"
    query = (data.get("user_input") or "").strip() or "support"

    ticket = get_ticket(ticket_id)
    vendor_id = ticket.get("vendor_id") or "demo-vendor-001"
    vendor = get_vendor_profile(vendor_id)
    policy = search_support_policy(query)
    previous_cases = search_previous_ticket_responses(query)

    data["ticket_id"] = ticket_id
    data["vendor_id"] = vendor_id

    data["retrieved_context"] = {
        "ticket": ticket,
        "vendor": vendor,
        "policy_context": policy,
        "previous_cases": previous_cases,
    }

    data["tool_results"] = {
        "get_ticket": {"ok": True, "ticket_id": ticket_id},
        "get_vendor_profile": {"ok": True, "vendor_id": vendor_id},
        "search_support_policy": {"ok": True},
        "search_previous_ticket_responses": {"ok": True, "count": len(previous_cases)},
    }

    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="retrieve_context",
        message="Retrieved mock ticket, vendor, policy, and prior cases via tools.",
        metadata={"ticket_id": ticket_id, "vendor_id": vendor_id},
    )
    return cast(CommerceAIState, data)


def _has_valid_specialist_output(specialist_output: dict[str, Any]) -> bool:
    if not specialist_output:
        return False
    draft = specialist_output.get("draft_response")
    return isinstance(draft, str) and bool(draft.strip())


def _has_valid_final_response(final_response: str | None) -> bool:
    return isinstance(final_response, str) and bool(final_response.strip())


def validate_output(state: CommerceAIState) -> CommerceAIState:
    """Validate specialist output and final response; record errors or audit on success."""
    data = _state_dict(state)
    specialist_ok = _has_valid_specialist_output(data.get("specialist_output") or {})
    final_ok = _has_valid_final_response(data.get("final_response"))

    if not specialist_ok or not final_ok:
        errors: list[ToolError] = []
        if not specialist_ok:
            errors.append(
                ToolError(
                    tool_name="validate_output",
                    error_type="validation_error",
                    message="specialist_output is missing or lacks a non-empty draft_response.",
                    retryable=False,
                )
            )
        if not final_ok:
            errors.append(
                ToolError(
                    tool_name="validate_output",
                    error_type="validation_error",
                    message="final_response is missing or empty.",
                    retryable=False,
                )
            )
        data["errors"] = _append_errors(data["errors"], *errors)
        data["audit_log"] = _append_audit(
            data["audit_log"],
            node_name="validate_output",
            message="Validation failed; errors were added to state.",
            metadata={
                "error_count": len(data["errors"]),
                "has_specialist_output": specialist_ok,
                "has_final_response": final_ok,
            },
        )
        return cast(CommerceAIState, data)

    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="validate_output",
        message="Specialist output and final response validated.",
        metadata={},
    )
    return cast(CommerceAIState, data)


def risk_and_approval_decision(state: CommerceAIState) -> CommerceAIState:
    """Set approval gates on success, or fail closed when errors are already present."""
    data = _state_dict(state)
    errors = data.get("errors") or []
    if errors:
        data["workflow_status"] = WorkflowStatus.FAILED
        data["approval_status"] = ApprovalStatus.NOT_REQUIRED
        data["human_approval_required"] = False
        data["recommended_action"] = "fix_workflow_errors"
        data["audit_log"] = _append_audit(
            data["audit_log"],
            node_name="risk_and_approval_decision",
            message="Workflow failed before approval due to validation or tool errors.",
            metadata={"error_count": len(errors)},
        )
        return cast(CommerceAIState, data)

    data["human_approval_required"] = True
    data["approval_status"] = ApprovalStatus.REQUIRED
    data["workflow_status"] = WorkflowStatus.AWAITING_APPROVAL
    data["recommended_action"] = "review_ticket_reply_draft"
    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="risk_and_approval_decision",
        message="Human approval required for vendor ticket draft.",
        metadata={
            "recommended_action": data["recommended_action"],
            "risk_score": data.get("risk_score"),
            "confidence_score": data.get("confidence_score"),
        },
    )
    return cast(CommerceAIState, data)


def persist_trace(state: CommerceAIState) -> CommerceAIState:
    """Mock persistence only; preserve workflow_status (e.g. awaiting approval)."""
    data = _state_dict(state)
    data["audit_log"] = _append_audit(
        data["audit_log"],
        node_name="persist_trace",
        message="Trace persistence mocked (no database write).",
        metadata={"workflow_status": data.get("workflow_status")},
    )
    return cast(CommerceAIState, data)
