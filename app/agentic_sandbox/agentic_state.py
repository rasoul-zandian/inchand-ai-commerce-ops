"""Typed state contract for the agentic sandbox LangGraph workflow."""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class AgenticSandboxState(TypedDict):
    """Sandbox-only orchestration state (first-turn, HITL, no execution)."""

    room_id: str
    ticket_label: str | None
    route_label: str | None
    first_turn_text: str
    full_first_vendor_message_text: NotRequired[str]
    first_turn_extraction_text: NotRequired[str]
    entity_extraction_source: NotRequired[str]
    entity_extraction_source_char_count: NotRequired[int]
    display_preview_char_count: NotRequired[int]
    detected_intent: str | None
    conceptual_intent_fa: str | None
    extracted_entities: dict[str, Any]
    suggested_action: str | None
    suggested_action_reason: str | None
    actionability: dict[str, Any]
    knowledge_hints_enabled: bool
    knowledge_hints: list[dict[str, Any]]
    knowledge_hints_for_prompt: NotRequired[list[dict[str, Any]]]
    draft_reply: str | None
    draft_provider: NotRequired[str | None]
    openai_draft_metrics: NotRequired[dict[str, Any] | None]
    operational_sufficiency_metrics: NotRequired[dict[str, Any] | None]
    safety_status: str | None
    human_review_required: bool
    execution_allowed: bool
    customer_send_allowed: bool
    human_review_payload: dict[str, Any]
    node_results: list[dict[str, Any]]
    errors: list[str]
    # Runtime-only (stripped from persisted sandbox reports)
    _llm_provider: NotRequired[str]
    _llm_model: NotRequired[str]
    _generate_fn: NotRequired[Any]


def initial_agentic_sandbox_state(
    *,
    room_id: str,
    ticket_label: str | None = None,
    route_label: str | None = None,
    first_turn_text: str = "",
    full_first_vendor_message_text: str = "",
    first_turn_extraction_text: str = "",
    entity_extraction_source: str = "",
    entity_extraction_source_char_count: int = 0,
    display_preview_char_count: int = 0,
    llm_provider: str = "mock",
    llm_model: str = "mock-vendor-ticket-drafter",
    generate_fn: Any | None = None,
    knowledge_hints_enabled: bool = False,
) -> AgenticSandboxState:
    """Build a safe initial state with execution/send disabled."""
    return {
        "room_id": room_id,
        "ticket_label": ticket_label,
        "route_label": route_label,
        "first_turn_text": first_turn_text.strip(),
        "full_first_vendor_message_text": full_first_vendor_message_text.strip(),
        "first_turn_extraction_text": (
            first_turn_extraction_text.strip()
            or full_first_vendor_message_text.strip()
            or first_turn_text.strip()
        ),
        "entity_extraction_source": entity_extraction_source,
        "entity_extraction_source_char_count": entity_extraction_source_char_count,
        "display_preview_char_count": display_preview_char_count,
        "detected_intent": None,
        "conceptual_intent_fa": None,
        "extracted_entities": {},
        "suggested_action": None,
        "suggested_action_reason": None,
        "actionability": {},
        "knowledge_hints_enabled": knowledge_hints_enabled,
        "knowledge_hints": [],
        "knowledge_hints_for_prompt": [],
        "draft_reply": None,
        "safety_status": None,
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "human_review_payload": {},
        "node_results": [],
        "errors": [],
        "_llm_provider": llm_provider,
        "_llm_model": llm_model,
        "_generate_fn": generate_fn,
    }
