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
    extract_entities_node,
    generate_draft_node,
    human_review_handoff_node,
    retrieve_knowledge_hints_node,
    safety_gate_node,
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
    "generate_draft",
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
    """Compile linear sandbox graph (no conditional tool execution)."""
    cfg = settings or get_settings()

    def _retrieve(state: AgenticSandboxState) -> dict[str, Any]:
        return retrieve_knowledge_hints_node(state, settings=cfg)

    def _generate(state: AgenticSandboxState) -> dict[str, Any]:
        return generate_draft_node(state, settings=cfg)

    builder = StateGraph(AgenticSandboxState)
    builder.add_node("build_first_turn_context", build_first_turn_context_node)
    builder.add_node("detect_intent", detect_intent_node)
    builder.add_node("extract_entities", extract_entities_node)
    builder.add_node("retrieve_knowledge_hints", _retrieve)
    builder.add_node("suggest_action", suggest_action_node)
    builder.add_node("validate_actionability", validate_actionability_node)
    builder.add_node("generate_draft", _generate)
    builder.add_node("safety_gate", safety_gate_node)
    builder.add_node("human_review_handoff", human_review_handoff_node)

    builder.add_edge(START, "build_first_turn_context")
    builder.add_edge("build_first_turn_context", "detect_intent")
    builder.add_edge("detect_intent", "extract_entities")
    builder.add_edge("extract_entities", "retrieve_knowledge_hints")
    builder.add_edge("retrieve_knowledge_hints", "suggest_action")
    builder.add_edge("suggest_action", "validate_actionability")
    builder.add_edge("validate_actionability", "generate_draft")
    builder.add_edge("generate_draft", "safety_gate")
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
) -> AgenticSandboxState:
    """Build initial sandbox state from an operator ticket."""
    sources = resolve_first_turn_text_sources_from_ticket(ticket)
    return initial_agentic_sandbox_state(
        room_id=ticket.room_id,
        ticket_label=ticket.ticket_label,
        route_label=ticket.route_label,
        first_turn_text=sources.display_text,
        full_first_vendor_message_text=(ticket.full_first_vendor_message_text or ""),
        first_turn_extraction_text=sources.extraction_text,
        entity_extraction_source=sources.entity_extraction_source,
        entity_extraction_source_char_count=sources.entity_extraction_source_char_count,
        display_preview_char_count=sources.display_preview_char_count,
        llm_provider=llm_provider,
        llm_model=llm_model,
        generate_fn=generate_fn,
        knowledge_hints_enabled=knowledge_hints_enabled,
    )
