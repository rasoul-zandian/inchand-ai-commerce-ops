"""Helpers for additive shadow AI assist fields on CommerceAIState (no execution)."""

from __future__ import annotations

from typing import Any

from app.state.commerce_state import CommerceAIState
from app.workflows.vendor_ticket_ai_assist_models import VendorTicketAIAssistResult
from app.workflows.vendor_ticket_ai_assist_shadow import build_ai_assist_input_from_state

AI_ASSIST_STATE_DEFAULTS: dict[str, Any] = {
    "ai_assist_shadow_generated": False,
    "ai_assist_human_review_required": True,
    "ai_assist_shadow_only": True,
}

_AI_ASSIST_STATE_KEYS = frozenset(
    {
        "ai_assist_shadow_generated",
        "ai_assist_suggested_priority",
        "ai_assist_escalation_recommended",
        "ai_assist_duplicate_possible",
        "ai_assist_suggested_action",
        "ai_assist_confidence_band",
        "ai_assist_human_review_required",
        "ai_assist_shadow_only",
    }
)

_FORBIDDEN_SNAPSHOT_KEYS = frozenset(
    {
        "user_input",
        "query",
        "content",
        "transcript",
        "results",
        "draft_response",
        "final_response",
        "suggestions",
        "retrieved_context",
    }
)


def default_ai_assist_state_values() -> dict[str, Any]:
    """Safe defaults for additive AI assist fields."""
    return {
        "ai_assist_shadow_generated": False,
        "ai_assist_suggested_priority": None,
        "ai_assist_escalation_recommended": None,
        "ai_assist_duplicate_possible": None,
        "ai_assist_suggested_action": None,
        "ai_assist_confidence_band": None,
        **AI_ASSIST_STATE_DEFAULTS,
    }


def sanitize_ai_assist_state_snapshot(state: CommerceAIState) -> dict[str, Any]:
    """Aggregate-safe assist snapshot for audit (no raw text or retrieval hits)."""
    snapshot: dict[str, Any] = {}
    for key in _AI_ASSIST_STATE_KEYS:
        if key in state:
            snapshot[key] = state[key]
    forbidden = {str(k).lower() for k in snapshot.keys()}.intersection(_FORBIDDEN_SNAPSHOT_KEYS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"ai assist snapshot contains forbidden keys: {joined}")
    return snapshot


def apply_ai_assist_result_to_state(
    state: CommerceAIState,
    result: VendorTicketAIAssistResult,
) -> CommerceAIState:
    """Write aggregate-safe assist metadata into state (HITL-only; not consumed downstream)."""
    state["ai_assist_shadow_generated"] = True
    state["ai_assist_suggested_priority"] = result.suggested_priority
    state["ai_assist_escalation_recommended"] = result.escalation_recommended
    state["ai_assist_duplicate_possible"] = result.duplicate_possible
    state["ai_assist_suggested_action"] = result.suggested_action.value
    state["ai_assist_confidence_band"] = result.confidence_band
    state["ai_assist_human_review_required"] = result.human_review_required
    state["ai_assist_shadow_only"] = result.assist_shadow_only
    sanitize_ai_assist_state_snapshot(state)
    return state


def build_sanitized_ai_assist_payload(state: CommerceAIState) -> dict[str, Any]:
    """Build evaluator input from state without reading user_input or hit content."""
    return build_ai_assist_input_from_state(state)
