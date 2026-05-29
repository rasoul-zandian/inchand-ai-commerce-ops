"""LangGraph sandbox workflow — linear orchestration of safe draft components."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agentic_sandbox.agentic_nodes import (
    build_first_turn_context_node,
    detect_intent_node,
    execute_iran_post_tracking_node,
    execute_order_lookup_node,
    extract_entities_node,
    generate_draft_node,
    grounded_reply_node,
    human_review_handoff_node,
    plan_read_only_tools_node,
    retrieve_knowledge_hints_node,
    safety_gate_node,
    shipment_delivery_decision_after_tracking_node,
    shipment_delivery_decision_node,
    suggest_action_node,
    validate_actionability_node,
)
from app.agentic_sandbox.agentic_state import (
    AgenticSandboxState,
    initial_agentic_sandbox_state,
)
from app.config import AppSettings, get_settings
from app.evals.first_turn_draft_context import resolve_first_turn_text_sources_from_ticket
from app.operator_console.console_loader import load_operator_tickets
from app.operator_console.console_models import OperatorTicket

NODE_ORDER = (
    "build_first_turn_context",
    "detect_intent",
    "extract_entities",
    "retrieve_knowledge_hints",
    "suggest_action",
    "validate_actionability",
    "plan_read_only_tools",
    "execute_order_lookup",
    "shipment_delivery_decision",
    "execute_iran_post_tracking",
    "shipment_delivery_decision_after_tracking",
    "generate_draft",
    "grounded_reply",
    "safety_gate",
    "human_review_handoff",
)

_FORBIDDEN_REPORT_KEYS = frozenset(
    {
        "messages",
        "user_input",
        "gold_reference_reply",
        "conversation_transcript",
        "transcript",
        "retrieved_context",
        "draft_response",
        "final_response",
        "full_first_vendor_message_text",
        "first_turn_extraction_text",
        "first_turn_full_text",
        "full_first_turn_text",
        "raw_first_turn_text",
        "raw_prompt",
        "retrieval_results",
        "raw_snippets",
        "knowledge_hints_for_prompt",
        "prompt_snippet",
        "_generate_fn",
        "_llm_provider",
        "_llm_model",
    },
)


def _strip_forbidden_report_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if key not in _FORBIDDEN_REPORT_KEYS}


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def build_agentic_sandbox_graph(
    *,
    settings: AppSettings | None = None,
) -> CompiledStateGraph[AgenticSandboxState]:
    """Compile sandbox graph with gated read-only tool nodes."""
    cfg = settings or get_settings()

    def _retrieve(state: AgenticSandboxState) -> dict[str, Any]:
        return retrieve_knowledge_hints_node(state, settings=cfg)

    def _generate(state: AgenticSandboxState) -> dict[str, Any]:
        return generate_draft_node(state, settings=cfg)

    def _plan_tools(state: AgenticSandboxState) -> dict[str, Any]:
        return plan_read_only_tools_node(state, settings=cfg)

    def _order_lookup(state: AgenticSandboxState) -> dict[str, Any]:
        return execute_order_lookup_node(state, settings=cfg)

    def _iran_post(state: AgenticSandboxState) -> dict[str, Any]:
        return execute_iran_post_tracking_node(state, settings=cfg)

    builder = StateGraph(AgenticSandboxState)
    builder.add_node("build_first_turn_context", build_first_turn_context_node)
    builder.add_node("detect_intent", detect_intent_node)
    builder.add_node("extract_entities", extract_entities_node)
    builder.add_node("retrieve_knowledge_hints", _retrieve)
    builder.add_node("suggest_action", suggest_action_node)
    builder.add_node("validate_actionability", validate_actionability_node)
    builder.add_node("plan_read_only_tools", _plan_tools)
    builder.add_node("execute_order_lookup", _order_lookup)
    builder.add_node("shipment_delivery_decision", shipment_delivery_decision_node)
    builder.add_node("execute_iran_post_tracking", _iran_post)
    builder.add_node(
        "shipment_delivery_decision_after_tracking",
        shipment_delivery_decision_after_tracking_node,
    )
    builder.add_node("generate_draft", _generate)
    builder.add_node("grounded_reply", grounded_reply_node)
    builder.add_node("safety_gate", safety_gate_node)
    builder.add_node("human_review_handoff", human_review_handoff_node)

    builder.add_edge(START, "build_first_turn_context")
    builder.add_edge("build_first_turn_context", "detect_intent")
    builder.add_edge("detect_intent", "extract_entities")
    builder.add_edge("extract_entities", "retrieve_knowledge_hints")
    builder.add_edge("retrieve_knowledge_hints", "suggest_action")
    builder.add_edge("suggest_action", "validate_actionability")
    builder.add_edge("validate_actionability", "plan_read_only_tools")
    builder.add_edge("plan_read_only_tools", "execute_order_lookup")
    builder.add_edge("execute_order_lookup", "shipment_delivery_decision")
    builder.add_edge("shipment_delivery_decision", "execute_iran_post_tracking")
    builder.add_edge("execute_iran_post_tracking", "shipment_delivery_decision_after_tracking")
    builder.add_edge("shipment_delivery_decision_after_tracking", "generate_draft")
    builder.add_edge("generate_draft", "grounded_reply")
    builder.add_edge("grounded_reply", "safety_gate")
    builder.add_edge("safety_gate", "human_review_handoff")
    builder.add_edge("human_review_handoff", END)

    return builder.compile()


def build_safe_run_report(
    state: Mapping[str, Any],
    *,
    tracing_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Serialize sandbox run output without runtime-only or forbidden fields."""
    handoff_raw = state.get("human_review_payload")
    handoff = (
        _strip_forbidden_report_fields(handoff_raw) if isinstance(handoff_raw, Mapping) else {}
    )
    report: dict[str, Any] = _strip_forbidden_report_fields(
        {
            "generated_at_utc": _utc_now_iso(),
            "room_id": state.get("room_id"),
            "node_order": list(NODE_ORDER),
            "node_results": state.get("node_results") or [],
            "safety_status": state.get("safety_status"),
            "human_review_required": state.get("human_review_required"),
            "execution_allowed": state.get("execution_allowed"),
            "customer_send_allowed": state.get("customer_send_allowed"),
            "detected_intent": state.get("detected_intent"),
            "conceptual_intent_fa": state.get("conceptual_intent_fa"),
            "suggested_action": state.get("suggested_action"),
            "entity_extraction_source": state.get("entity_extraction_source"),
            "entity_extraction_source_char_count": state.get("entity_extraction_source_char_count"),
            "display_preview_char_count": state.get("display_preview_char_count"),
            "actionability": state.get("actionability"),
            "extracted_entities": state.get("extracted_entities"),
            "knowledge_hints": state.get("knowledge_hints"),
            "draft_reply": state.get("draft_reply"),
            "graph_tools_enabled": state.get("graph_tools_enabled"),
            "graph_tool_metadata": state.get("graph_tool_metadata"),
            "graph_tool_results": state.get("graph_tool_results"),
            "shipment_delivery_decision_type": state.get("shipment_delivery_decision_type"),
            "multi_order_decision_type": state.get("multi_order_decision_type"),
            "multi_order_reply_used": state.get("multi_order_reply_used"),
            "multi_order_summary": state.get("multi_order_summary"),
            "decision_used_order_lookup_result": state.get("decision_used_order_lookup_result"),
            "order_lookup_result_source": state.get("order_lookup_result_source"),
            "order_lookup_auto_triggered": state.get("order_lookup_auto_triggered"),
            "tool_grounded_reply_used": state.get("tool_grounded_reply_used"),
            "order_lookup_found": (state.get("order_lookup_result", {}) or {}).get("found")
            if isinstance(state.get("order_lookup_result"), Mapping)
            else None,
            "order_delivered_in_inchand": (state.get("order_lookup_result", {}) or {}).get(
                "is_delivered_in_inchand"
            )
            if isinstance(state.get("order_lookup_result"), Mapping)
            else None,
            "iran_post_verified": (state.get("iran_post_tracking_result", {}) or {}).get("verified")
            if isinstance(state.get("iran_post_tracking_result"), Mapping)
            else None,
            "human_review_payload": handoff,
            "errors": state.get("errors") or [],
        },
    )
    if tracing_metadata:
        report.update(_strip_forbidden_report_fields(dict(tracing_metadata)))
    text = json.dumps(report, ensure_ascii=False)
    lowered = text.lower()
    for token in (
        "conversation transcript",
        "gold_reference_reply",
        '"messages"',
        "conversation_transcript",
    ):
        if token in lowered:
            raise ValueError(f"report contains forbidden token: {token}")
    return report


def resolve_ticket_for_sandbox(
    room_id: str,
    *,
    replay_jsonl: Path | str,
    redacted_jsonl: Path | str | None = None,
) -> OperatorTicket:
    """Load ticket by room_id; prefer replay row, enrich first-turn from redacted if needed."""
    tickets = load_operator_tickets(replay_jsonl)
    match = next((ticket for ticket in tickets if ticket.room_id == room_id), None)
    if match is None:
        raise ValueError(f"room_id not found in replay JSONL: {room_id}")

    if match.original_vendor_issue_preview and str(match.original_vendor_issue_preview).strip():
        return match

    if redacted_jsonl is not None:
        redacted = load_operator_tickets(redacted_jsonl)
        red_match = next((ticket for ticket in redacted if ticket.room_id == room_id), None)
        if red_match is not None and red_match.original_vendor_issue_preview:
            return OperatorTicket(
                room_id=match.room_id,
                ticket_label=match.ticket_label or red_match.ticket_label,
                route_label=match.route_label or red_match.route_label,
                assigned_department=match.assigned_department,
                review_priority=match.review_priority,
                suggested_action=match.suggested_action,
                suggested_priority=match.suggested_priority,
                escalation_recommended=match.escalation_recommended,
                duplicate_possible=match.duplicate_possible,
                confidence_band=match.confidence_band,
                retrieval_gate_decision=match.retrieval_gate_decision,
                retrieval_result_count=match.retrieval_result_count,
                ticket_text_preview=None,
                open_ticket_preview=None,
                original_vendor_issue_preview=red_match.original_vendor_issue_preview,
                latest_vendor_message=None,
                recent_context_preview=None,
                extracted_order_id=match.extracted_order_id,
                extracted_order_ids=match.extracted_order_ids,
                extracted_tracking_code=match.extracted_tracking_code,
                extracted_product_ids=match.extracted_product_ids,
                extracted_tracking_carrier=match.extracted_tracking_carrier,
                extracted_iban=match.extracted_iban,
                extracted_iban_masked=match.extracted_iban_masked,
                entity_warnings_summary=match.entity_warnings_summary,
                detected_intent=match.detected_intent,
                shop_id=match.shop_id,
                seller_id=match.seller_id,
                shop_name=match.shop_name,
                shop_identity_available=match.shop_identity_available,
            )
    raise ValueError(
        f"room_id {room_id} has no original_vendor_issue_preview; provide --redacted-jsonl",
    )


def run_agentic_sandbox_workflow(
    initial: AgenticSandboxState,
    *,
    settings: AppSettings | None = None,
) -> AgenticSandboxState:
    """Invoke compiled sandbox graph."""
    graph = build_agentic_sandbox_graph(settings=settings)
    result = graph.invoke(initial)
    return cast(AgenticSandboxState, result)


def write_agentic_sandbox_report(
    state: AgenticSandboxState,
    output_path: Path | str,
    *,
    tracing_metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write safe JSON report for one sandbox run."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = build_safe_run_report(state, tracing_metadata=tracing_metadata)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def initial_state_from_ticket(
    ticket: OperatorTicket,
    *,
    llm_provider: str = "mock",
    llm_model: str = "mock-vendor-ticket-drafter",
    generate_fn: Any | None = None,
    knowledge_hints_enabled: bool = False,
    settings: AppSettings | None = None,
    conversation_snapshot: Any | None = None,
    source_mode: str = "historical_replay",
) -> AgenticSandboxState:
    """Build initial sandbox state from an operator ticket."""
    from app.config import get_settings
    from app.tickets.conversation_models import ConversationTicketSnapshot
    from app.workflows.multi_turn_ticket_context import (
        build_multi_turn_context,
        multi_turn_context_metadata_row,
        resolve_extraction_text_for_context,
        resolve_response_target_text,
    )

    cfg = settings or get_settings()
    sources = resolve_first_turn_text_sources_from_ticket(ticket)
    display_text = sources.display_text
    extraction_text = sources.extraction_text

    multi_meta: dict[str, Any] | None = None
    multi_active = False
    response_target = ""
    multi_extraction = extraction_text

    snapshot: ConversationTicketSnapshot | None = None
    if isinstance(conversation_snapshot, ConversationTicketSnapshot):
        snapshot = conversation_snapshot

    if cfg.multi_turn_context_enabled and snapshot is not None:
        multi_ctx = build_multi_turn_context(snapshot, settings=cfg)
        multi_meta = multi_turn_context_metadata_row(multi_ctx)
        multi_active = True
        response_target = resolve_response_target_text(
            context=multi_ctx,
            fallback_first_turn=display_text,
            multi_turn_enabled=True,
        )
        multi_extraction = resolve_extraction_text_for_context(
            context=multi_ctx,
            fallback_extraction=extraction_text,
            multi_turn_enabled=True,
        )
        if response_target:
            display_text = response_target

    state = initial_agentic_sandbox_state(
        room_id=ticket.room_id,
        ticket_label=ticket.ticket_label,
        route_label=ticket.route_label,
        first_turn_text=display_text,
        full_first_vendor_message_text=(ticket.full_first_vendor_message_text or ""),
        first_turn_extraction_text=multi_extraction,
        entity_extraction_source=sources.entity_extraction_source,
        entity_extraction_source_char_count=len(multi_extraction),
        display_preview_char_count=len(display_text),
        llm_provider=llm_provider,
        llm_model=llm_model,
        generate_fn=generate_fn,
        knowledge_hints_enabled=knowledge_hints_enabled,
        shop_id=ticket.shop_id,
        seller_id=ticket.seller_id,
        shop_name=ticket.shop_name,
        shop_identity_available=bool(
            ticket.shop_identity_available
            if ticket.shop_identity_available is not None
            else (ticket.shop_id or ticket.seller_id or ticket.shop_name)
        ),
        source_mode=source_mode,
        graph_tools_enabled=bool(
            cfg.agentic_graph_read_only_tools_enabled
            and source_mode
            in {
                item.strip()
                for item in (cfg.agentic_graph_tool_execution_source_modes or "").split(",")
                if item.strip()
            }
        ),
    )
    if multi_meta is not None:
        state["multi_turn_context_metadata"] = multi_meta
        state["multi_turn_active"] = multi_active
        state["response_target_seller_text"] = response_target
        state["multi_turn_extraction_text"] = multi_extraction
    return state
