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
    shop_id: NotRequired[str | None]
    seller_id: NotRequired[str | None]
    shop_name: NotRequired[str | None]
    shop_identity_available: NotRequired[bool]
    source_mode: NotRequired[str]
    graph_tools_enabled: NotRequired[bool]
    graph_tool_execution_mode: NotRequired[str | None]
    graph_tool_results: NotRequired[dict[str, Any]]
    graph_tool_metadata: NotRequired[dict[str, Any]]
    graph_tool_errors: NotRequired[list[str]]
    order_lookup_result: NotRequired[dict[str, Any] | None]
    multi_order_ids: NotRequired[list[str]]
    multi_order_lookup_results: NotRequired[dict[str, dict[str, Any]]]
    multi_order_decision: NotRequired[dict[str, Any] | None]
    multi_order_summary: NotRequired[dict[str, Any] | None]
    multi_order_batch_enabled: NotRequired[bool]
    multi_order_batch_count: NotRequired[int]
    multi_order_batch_limit_exceeded: NotRequired[bool]
    multi_order_decision_type: NotRequired[str | None]
    multi_order_reply_used: NotRequired[bool]
    iran_post_tracking_result: NotRequired[dict[str, Any] | None]
    shipment_delivery_decision: NotRequired[dict[str, Any] | None]
    shipment_delivery_decision_type: NotRequired[str | None]
    decision_used_order_lookup_result: NotRequired[bool]
    order_lookup_result_source: NotRequired[str]
    order_lookup_auto_triggered: NotRequired[bool]
    grounded_decision_reply: NotRequired[str | None]
    tool_grounded_reply_used: NotRequired[bool]
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
    final_draft_reflection_metrics: NotRequired[dict[str, Any] | None]
    final_draft_reflection_comparison: NotRequired[dict[str, Any] | None]
    multi_turn_context_metadata: NotRequired[dict[str, Any] | None]
    multi_turn_active: NotRequired[bool]
    response_target_seller_text: NotRequired[str]
    multi_turn_extraction_text: NotRequired[str]
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
    shop_id: str | None = None,
    seller_id: str | None = None,
    shop_name: str | None = None,
    shop_identity_available: bool = False,
    source_mode: str = "historical_replay",
    graph_tools_enabled: bool = False,
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
        "shop_id": (shop_id.strip() if shop_id else None),
        "seller_id": (seller_id.strip() if seller_id else None),
        "shop_name": (shop_name.strip() if shop_name else None),
        "shop_identity_available": bool(shop_identity_available),
        "source_mode": source_mode,
        "graph_tools_enabled": graph_tools_enabled,
        "graph_tool_execution_mode": None,
        "graph_tool_results": {},
        "graph_tool_metadata": {},
        "graph_tool_errors": [],
        "order_lookup_result": None,
        "multi_order_ids": [],
        "multi_order_lookup_results": {},
        "multi_order_decision": None,
        "multi_order_summary": None,
        "multi_order_batch_enabled": False,
        "multi_order_batch_count": 0,
        "multi_order_batch_limit_exceeded": False,
        "multi_order_decision_type": None,
        "multi_order_reply_used": False,
        "iran_post_tracking_result": None,
        "shipment_delivery_decision": None,
        "shipment_delivery_decision_type": None,
        "decision_used_order_lookup_result": False,
        "order_lookup_result_source": "none",
        "order_lookup_auto_triggered": False,
        "grounded_decision_reply": None,
        "tool_grounded_reply_used": False,
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
