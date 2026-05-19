"""Shadow-only vendor ticket AI operational assist evaluator (no side effects)."""

from __future__ import annotations

from typing import Any

from app.workflows.vendor_ticket_ai_assist_models import (
    VendorTicketAIAssistActionType,
    VendorTicketAIAssistResult,
    VendorTicketAIAssistSeverity,
    VendorTicketAIAssistSuggestion,
)

_FORBIDDEN_INPUT_KEYS = frozenset(
    {
        "query",
        "user_input",
        "content",
        "transcript",
        "conversation_transcript",
        "raw_text",
        "vector",
        "vectors",
        "embedding",
        "embeddings",
        "messages",
        "results",
        "retrieved_context",
        "draft_response",
        "final_response",
        "rag_sources",
        "specialist_output",
        "tool_results",
        "audit_log",
        "customer_reply",
        "generated_response",
    }
)

_ALLOWED_INPUT_KEYS = frozenset(
    {
        "ticket_id",
        "request_id",
        "room_id",
        "ticket_label",
        "route_label",
        "review_priority",
        "assigned_department",
        "retrieval_gate_decision",
        "retrieval_scenario",
        "retrieval_policy_reasons",
        "retrieval_query_hash",
        "retrieval_result_count",
        "retrieval_metadata_filter",
        "retrieval_sandbox_only",
        "retrieval_activated",
        "downstream_consumed_retrieval",
        "retrieval_error",
        "executor_called",
    }
)

_PRIORITY_FROM_REVIEW = {
    "HIGH": "high",
    "MEDIUM": "medium",
    "LOW": "low",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "normal": "medium",
}


def _collect_keys(value: Any, keys: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(str(key).lower())
            _collect_keys(child, keys)
    elif isinstance(value, list):
        for item in value:
            _collect_keys(item, keys)


def assert_ai_assist_input_safe(payload: dict[str, Any]) -> None:
    """Fail closed if assist input may contain raw content or unsafe flags."""
    keys: set[str] = set()
    _collect_keys(payload, keys)
    forbidden = keys.intersection(_FORBIDDEN_INPUT_KEYS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"ai assist input contains forbidden keys: {joined}")
    if payload.get("retrieval_activated") is True:
        raise ValueError("retrieval_activated must be false for shadow assist")
    if payload.get("downstream_consumed_retrieval") is True:
        raise ValueError("downstream_consumed_retrieval must be false for shadow assist")


def build_ai_assist_input_from_state(state: dict[str, Any]) -> dict[str, Any]:
    """Extract allowlisted aggregate fields from workflow state for shadow assist."""
    payload: dict[str, Any] = {}
    for key in _ALLOWED_INPUT_KEYS:
        if key in state:
            payload[key] = state[key]
    if "retrieval_activated" not in payload:
        payload["retrieval_activated"] = bool(state.get("retrieval_activated", False))
    if "downstream_consumed_retrieval" not in payload:
        payload["downstream_consumed_retrieval"] = bool(
            state.get("downstream_consumed_retrieval", False),
        )
    return payload


def sanitize_ai_assist_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only allowlisted aggregate fields for shadow assist evaluation."""
    assert_ai_assist_input_safe(payload)
    sanitized: dict[str, Any] = {}
    for key in _ALLOWED_INPUT_KEYS:
        if key in payload:
            sanitized[key] = payload[key]
    return sanitized


def _norm_label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _review_priority_to_suggested(review_priority: Any) -> str:
    if review_priority is None:
        return "medium"
    key = str(review_priority).strip()
    return _PRIORITY_FROM_REVIEW.get(key, _PRIORITY_FROM_REVIEW.get(key.upper(), "medium"))


def _retrieval_summary_available(sanitized: dict[str, Any]) -> bool:
    gate = _norm_label(sanitized.get("retrieval_gate_decision"))
    count = sanitized.get("retrieval_result_count")
    if gate != "allow":
        return False
    if count is None:
        return False
    try:
        return int(count) > 0
    except (TypeError, ValueError):
        return False


def _confidence_band(
    *,
    ticket_label: str | None,
    route_label: str | None,
    retrieval_available: bool,
) -> str:
    if ticket_label and route_label and retrieval_available:
        return "high"
    if ticket_label and route_label:
        return "medium"
    if ticket_label:
        return "low"
    return "low"


def _build_suggestions(
    *,
    ticket_label: str | None,
    route_label: str | None,
    escalation_recommended: bool,
    duplicate_possible: bool,
    retrieval_available: bool,
) -> list[VendorTicketAIAssistSuggestion]:
    suggestions: list[VendorTicketAIAssistSuggestion] = []
    if ticket_label == "complaint" or route_label == "escalation_review":
        suggestions.append(
            VendorTicketAIAssistSuggestion(
                action_type=VendorTicketAIAssistActionType.ESCALATE,
                severity=VendorTicketAIAssistSeverity.HIGH,
                summary="Complaint or escalation route — prioritize human escalation review.",
                reason_codes=["ticket_label_complaint", "route_escalation_review"],
            ),
        )
    if ticket_label == "fund" or route_label == "billing_review":
        suggestions.append(
            VendorTicketAIAssistSuggestion(
                action_type=VendorTicketAIAssistActionType.BILLING_REVIEW,
                severity=VendorTicketAIAssistSeverity.MEDIUM,
                summary="Fund or billing route — route to billing specialist queue for review.",
                reason_codes=["ticket_label_fund", "route_billing_review"],
            ),
        )
    if ticket_label == "support" or route_label == "general_vendor_support":
        suggestions.append(
            VendorTicketAIAssistSuggestion(
                action_type=VendorTicketAIAssistActionType.MONITOR,
                severity=VendorTicketAIAssistSeverity.LOW,
                summary="General support route — monitor; no autonomous customer action.",
                reason_codes=["ticket_label_support", "route_general_vendor_support"],
            ),
        )
    if escalation_recommended and not any(
        s.action_type == VendorTicketAIAssistActionType.ESCALATE for s in suggestions
    ):
        suggestions.append(
            VendorTicketAIAssistSuggestion(
                action_type=VendorTicketAIAssistActionType.ESCALATE,
                severity=VendorTicketAIAssistSeverity.HIGH,
                summary="Escalation recommended based on routing signals.",
                reason_codes=["escalation_signal"],
            ),
        )
    if duplicate_possible:
        suggestions.append(
            VendorTicketAIAssistSuggestion(
                action_type=VendorTicketAIAssistActionType.DUPLICATE_CHECK,
                severity=VendorTicketAIAssistSeverity.MEDIUM,
                summary=(
                    "Pilot retrieval returned multiple matches — "
                    "operator should check for possible duplicate tickets."
                ),
                reason_codes=["retrieval_hit_count_elevated"],
            ),
        )
    if retrieval_available:
        suggestions.append(
            VendorTicketAIAssistSuggestion(
                action_type=VendorTicketAIAssistActionType.ROUTE_REVIEW,
                severity=VendorTicketAIAssistSeverity.LOW,
                summary=(
                    "Aggregate retrieval metadata available for operator review "
                    "(counts/hashes only; no hit content)."
                ),
                reason_codes=["retrieval_metadata_present"],
            ),
        )
    return suggestions[:6]


def evaluate_vendor_ticket_ai_assist_shadow(
    payload: dict[str, Any],
) -> VendorTicketAIAssistResult:
    """Produce HITL-only operator suggestions from sanitized state (no side effects)."""
    sanitized = sanitize_ai_assist_input(payload)
    ticket_label = _norm_label(sanitized.get("ticket_label"))
    route_label = _norm_label(sanitized.get("route_label"))
    review_priority = sanitized.get("review_priority")

    retrieval_available = _retrieval_summary_available(sanitized)
    result_count = sanitized.get("retrieval_result_count")
    hit_count = 0
    if result_count is not None:
        try:
            hit_count = int(result_count)
        except (TypeError, ValueError):
            hit_count = 0

    escalation_recommended = ticket_label == "complaint" or route_label == "escalation_review"
    duplicate_possible = retrieval_available and hit_count >= 3

    if escalation_recommended:
        suggested_action = VendorTicketAIAssistActionType.ESCALATE
    elif ticket_label == "fund" or route_label == "billing_review":
        suggested_action = VendorTicketAIAssistActionType.BILLING_REVIEW
    elif ticket_label == "support" or route_label == "general_vendor_support":
        suggested_action = VendorTicketAIAssistActionType.MONITOR
    elif duplicate_possible:
        suggested_action = VendorTicketAIAssistActionType.DUPLICATE_CHECK
    else:
        suggested_action = VendorTicketAIAssistActionType.MONITOR

    suggestions = _build_suggestions(
        ticket_label=ticket_label,
        route_label=route_label,
        escalation_recommended=escalation_recommended,
        duplicate_possible=duplicate_possible,
        retrieval_available=retrieval_available,
    )

    return VendorTicketAIAssistResult(
        suggested_priority=_review_priority_to_suggested(review_priority),
        escalation_recommended=escalation_recommended,
        duplicate_possible=duplicate_possible,
        suggested_action=suggested_action,
        retrieval_summary_available=retrieval_available,
        confidence_band=_confidence_band(
            ticket_label=ticket_label,
            route_label=route_label,
            retrieval_available=retrieval_available,
        ),
        assist_generated_at=VendorTicketAIAssistResult.utc_timestamp(),
        suggestions=suggestions,
        assist_shadow_only=True,
        human_review_required=True,
        retrieval_activated=False,
        downstream_consumed_retrieval=False,
    )
