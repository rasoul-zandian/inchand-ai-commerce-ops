"""Deterministic sandbox nodes orchestrating existing safe draft/HITL components."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.agentic_sandbox.final_draft_reflection import (
    FinalDraftReflectionResult,
    apply_final_draft_reflection_review,
    reflection_comparison_session_row,
    reflection_metadata_row,
)
from app.agentic_sandbox.mock_draft_templates import (
    MockOperationalDraftInput,
    generate_mock_operational_draft,
)
from app.config import AppSettings, get_settings
from app.evals.actionability_validation import (
    actionability_metadata_row,
    apply_actionability_to_draft,
    validate_actionability,
)
from app.evals.conceptual_intent_fa import (
    DraftWithConceptualIntent,
    fallback_conceptual_intent_fa,
    generate_draft_with_conceptual_intent,
)
from app.evals.draft_completion_calibration import apply_draft_completion_calibration
from app.evals.draft_evidence_wording_calibration import calibrate_photo_evidence_wording
from app.evals.draft_policy_grounding_calibration import apply_policy_grounding_calibration
from app.evals.draft_product_wording_calibration import apply_product_wording_calibration
from app.evals.draft_prompt_leakage import (
    assert_prompt_messages_safe,
    extract_forbidden_values_from_benchmark_case,
)
from app.evals.draft_style import (
    apply_draft_style_checks,
    resolve_effective_draft_style,
    resolve_effective_draft_style_limits,
)
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_FULL_FIRST_VENDOR,
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    FIRST_TURN_EXCLUDED_THREAD_FIELDS,
    build_first_turn_draft_context_from_ticket,
    intent_with_first_turn_entities,
)
from app.evals.offline_draft_generation import (
    assert_draft_reply_safe,
    build_offline_draft_messages,
)
from app.knowledge.policy_fact_extraction import hint_to_prompt_dict
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import KnowledgeHint
from app.tools.inchand.order_lookup import (
    lookup_inchand_order,
    normalize_inchand_order_id,
)
from app.tools.operational_actions_registry import (
    OperationalToolId,
    build_inchand_eligibility_context,
    build_iran_post_eligibility_context,
    evaluate_tool_eligibility,
)
from app.tools.tracking.iran_post_tracking import (
    infer_plausible_iran_post_tracking_code_from_text,
    verify_iran_post_tracking_code,
)
from app.workflows.multi_order_shipment_decision import (
    MultiOrderShipmentInput,
    decide_multi_order_shipment,
    extract_all_inchand_order_ids_with_diagnostics,
)
from app.workflows.multi_turn_ticket_context import apply_multi_turn_metadata_to_actionability
from app.workflows.operational_entity_extraction import (
    OperationalEntityExtractionResult,
    extract_operational_entities,
)
from app.workflows.operational_information_sufficiency import (
    apply_operational_sufficiency_calibration,
    apply_panel_issue_draft_calibration,
    detect_operational_scenario,
    operational_sufficiency_metrics_row,
)
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits
from app.workflows.shipment_delivery_decision import (
    ShipmentDeliveryDecisionInput,
    decide_shipment_delivery,
)
from app.workflows.suggested_action_taxonomy import map_intent_to_suggested_action
from app.workflows.vendor_ticket_intent_detection import detect_vendor_ticket_intent

# Present in workflow state for extraction only; stripped from reports, not a safety violation.
_INTERNAL_EXTRACTION_STATE_KEYS = frozenset(
    {
        "full_first_vendor_message_text",
        "first_turn_extraction_text",
        "entity_extraction_source",
        "entity_extraction_source_char_count",
        "display_preview_char_count",
    },
)

_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {
        "messages",
        "user_input",
        "gold_reference_reply",
        "conversation_transcript",
        "transcript",
        "retrieved_context",
        "draft_response",
        "final_response",
        "open_ticket_preview",
        "ticket_text_preview",
        "recent_context_preview",
        "latest_vendor_message",
        "full_first_vendor_message_text",
        "first_turn_extraction_text",
    },
)

_FORBIDDEN_DRAFT_SUBSTRINGS = (
    "conversation transcript",
    '"messages"',
    "gold_reference_reply",
    "auto-send",
    "ارسال خودکار",
)


def _append_node_result(
    state: dict[str, Any],
    *,
    node: str,
    status: str,
    summary: str,
) -> list[dict[str, Any]]:
    results = list(state.get("node_results") or [])
    results.append({"node": node, "status": status, "summary": summary})
    return results


def _entities_to_dict(
    entities: OperationalEntityExtractionResult,
    *,
    entity_extraction_source: str = ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
) -> dict[str, Any]:
    carrier = entities.primary_tracking_carrier
    return {
        "entity_source": entity_extraction_source,
        "order_ids": list(entities.order_ids),
        "product_ids": list(entities.product_ids),
        "tracking_code": entities.primary_tracking_code,
        "tracking_carrier": carrier.value if carrier else None,
        "iban_masked": entities.primary_iban_masked,
        "warnings_summary": entities.entity_warnings_summary,
    }


def _hint_to_dict(hint: KnowledgeHint) -> dict[str, Any]:
    return {
        "document_type": hint.document_type,
        "section_title": hint.section_title,
        "source_lane": hint.source_lane,
        "priority_rank": hint.priority_rank,
        "snippet_chars": len(hint.snippet or ""),
    }


def _ticket_from_state(state: dict[str, Any]) -> OperatorTicket:
    entities = state.get("extracted_entities") or {}
    order_ids = entities.get("order_ids") or []
    product_ids = entities.get("product_ids") or []
    return OperatorTicket(
        room_id=str(state["room_id"]),
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
        assigned_department=None,
        review_priority=None,
        suggested_action=state.get("suggested_action"),
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=state.get("first_turn_text") or None,
        latest_vendor_message=None,
        recent_context_preview=None,
        extracted_order_id=order_ids[0] if order_ids else None,
        extracted_order_ids=",".join(order_ids) if order_ids else None,
        extracted_tracking_code=entities.get("tracking_code"),
        extracted_product_ids=",".join(product_ids) if product_ids else None,
        extracted_tracking_carrier=entities.get("tracking_carrier"),
        extracted_iban=None,
        extracted_iban_masked=entities.get("iban_masked"),
        entity_warnings_summary=entities.get("warnings_summary"),
        detected_intent=state.get("detected_intent"),
        full_first_vendor_message_text=state.get("full_first_vendor_message_text"),
        shop_id=state.get("shop_id"),
    )


def build_first_turn_context_node(state: dict[str, Any]) -> dict[str, Any]:
    """Isolate display preview and full first-turn extraction text (no later messages)."""
    display = (state.get("first_turn_text") or "").strip()
    extraction = (state.get("first_turn_extraction_text") or display).strip()
    if not display and not extraction:
        errors = list(state.get("errors") or [])
        errors.append("build_first_turn_context: empty first_turn_text")
        return {
            "errors": errors,
            "node_results": _append_node_result(
                state,
                node="build_first_turn_context",
                status="failed",
                summary="missing first-turn text",
            ),
        }
    source = state.get("entity_extraction_source") or (
        ENTITY_SOURCE_FULL_FIRST_VENDOR
        if (state.get("full_first_vendor_message_text") or "").strip()
        else ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    )
    return {
        "first_turn_text": display,
        "first_turn_extraction_text": extraction,
        "entity_extraction_source": source,
        "entity_extraction_source_char_count": len(extraction),
        "display_preview_char_count": len(display),
        "node_results": _append_node_result(
            state,
            node="build_first_turn_context",
            status="ok",
            summary=(
                f"display_chars={len(display)} extraction_chars={len(extraction)} source={source}"
            ),
        ),
    }


def detect_intent_node(state: dict[str, Any]) -> dict[str, Any]:
    """Rule-based vendor ticket intent detection (first-turn text only)."""
    first_turn = state.get("first_turn_text") or ""
    intent = detect_vendor_ticket_intent(
        first_turn,
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
    )
    return {
        "detected_intent": intent.detected_intent,
        "node_results": _append_node_result(
            state,
            node="detect_intent",
            status="ok",
            summary=f"detected_intent={intent.detected_intent}",
        ),
    }


def extract_entities_node(state: dict[str, Any]) -> dict[str, Any]:
    """Operational entity extraction from full first seller message when available."""
    extraction_text = (
        state.get("multi_turn_extraction_text")
        or state.get("first_turn_extraction_text")
        or state.get("first_turn_text")
        or ""
    )
    source = state.get("entity_extraction_source") or ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
    entities = extract_operational_entities(extraction_text)
    entity_dict = _entities_to_dict(entities, entity_extraction_source=str(source))
    return {
        "extracted_entities": entity_dict,
        "node_results": _append_node_result(
            state,
            node="extract_entities",
            status="ok",
            summary=(
                f"orders={len(entity_dict.get('order_ids') or [])} "
                f"products={len(entity_dict.get('product_ids') or [])}"
            ),
        ),
    }


def retrieve_knowledge_hints_node(
    state: dict[str, Any],
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Sandbox knowledge hints only (no production RAG_PROFILE)."""
    cfg = settings or get_settings()
    ticket = _ticket_from_state(state)
    display = state.get("first_turn_text") or ""
    extraction = state.get("first_turn_extraction_text") or display
    intent_raw = detect_vendor_ticket_intent(
        display,
        ticket_label=ticket.ticket_label,
        route_label=ticket.route_label,
    )
    entities = extract_operational_entities(extraction)
    intent = intent_with_first_turn_entities(intent_raw, entities)

    hints: tuple[KnowledgeHint, ...] = ()
    state_hints_enabled = bool(state.get("knowledge_hints_enabled"))
    if state_hints_enabled and cfg.knowledge_hints_enabled:
        from app.operator_console.knowledge_hints import fetch_knowledge_hints_for_ticket

        hints = fetch_knowledge_hints_for_ticket(
            _ticket_from_state({**state, "detected_intent": intent.detected_intent}),
            settings=cfg,
            first_turn_only=True,
        )

    hint_dicts = [_hint_to_dict(hint) for hint in hints]
    prompt_hint_dicts = [hint_to_prompt_dict(hint) for hint in hints]
    status = "ok"
    if state_hints_enabled and not cfg.knowledge_hints_enabled:
        status = "skipped"
    return {
        "knowledge_hints": hint_dicts,
        "knowledge_hints_for_prompt": prompt_hint_dicts,
        "node_results": _append_node_result(
            state,
            node="retrieve_knowledge_hints",
            status=status,
            summary=f"hints={len(hint_dicts)} enabled={state_hints_enabled}",
        ),
    }


def suggest_action_node(state: dict[str, Any]) -> dict[str, Any]:
    """Map detected intent to suggested action via taxonomy."""
    first_turn = state.get("first_turn_text") or ""
    intent_raw = detect_vendor_ticket_intent(
        first_turn,
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
    )
    entities = extract_operational_entities(first_turn)
    intent = intent_with_first_turn_entities(intent_raw, entities)
    normalized = normalize_persian_arabic_digits(first_turn) if first_turn else ""
    mapping = map_intent_to_suggested_action(
        intent.intent,
        entities=intent,
        normalized_text=normalized,
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
    )
    return {
        "suggested_action": mapping.action.value,
        "suggested_action_reason": mapping.reason,
        "node_results": _append_node_result(
            state,
            node="suggest_action",
            status="ok",
            summary=f"suggested_action={mapping.action.value}",
        ),
    }


def validate_actionability_node(state: dict[str, Any]) -> dict[str, Any]:
    """Check required identifiers before operational draft claims."""
    first_turn = state.get("first_turn_text") or ""
    intent_raw = detect_vendor_ticket_intent(
        first_turn,
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
    )
    entities = extract_operational_entities(first_turn)
    intent = intent_with_first_turn_entities(intent_raw, entities)
    validation = validate_actionability(
        suggested_action=state.get("suggested_action") or "",
        entities=intent,
        seller_text=first_turn,
        detected_intent=state.get("detected_intent"),
    )
    if state.get("multi_turn_active"):
        multi_meta = state.get("multi_turn_context_metadata") or {}
        if isinstance(multi_meta, dict):
            validation = apply_multi_turn_metadata_to_actionability(multi_meta, validation)
    meta = actionability_metadata_row(validation)
    return {
        "actionability": meta,
        "node_results": _append_node_result(
            state,
            node="validate_actionability",
            status="ok",
            summary=(
                f"actionable={meta.get('actionability_actionable')} "
                f"missing={meta.get('actionability_missing_entities') or 'none'}"
            ),
        ),
    }


def _tool_debug_payload(
    *,
    eligible_tools: list[str],
    blocked_tools: list[str],
    blocked_reasons: dict[str, str],
    executed_tools: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "planned_tools": eligible_tools,
        "blocked_tools": blocked_tools,
        "blocked_reasons": blocked_reasons,
        "executed_tools": list(executed_tools or []),
    }


def plan_read_only_tools_node(
    state: dict[str, Any],
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    source_mode = str(state.get("source_mode") or "historical_replay")
    graph_tools_enabled = bool(
        state.get("graph_tools_enabled")
        and cfg.agentic_graph_read_only_tools_enabled
        and source_mode
        in {
            item.strip()
            for item in (cfg.agentic_graph_tool_execution_source_modes or "").split(",")
            if item.strip()
        }
    )
    entities = (
        state.get("extracted_entities") if isinstance(state.get("extracted_entities"), dict) else {}
    )
    order_ids = entities.get("order_ids") if isinstance(entities, dict) else []
    order_id_present = bool(order_ids and order_ids[0])
    tracking_code_present = (
        bool((entities.get("tracking_code") or "").strip()) if isinstance(entities, dict) else False
    )
    carrier_candidate = entities.get("tracking_carrier") if isinstance(entities, dict) else None
    detected_scenario = detect_operational_scenario(
        seller_text=state.get("response_target_seller_text") or state.get("first_turn_text") or "",
        detected_intent=state.get("detected_intent"),
        suggested_action=state.get("suggested_action"),
        conceptual_intent_fa=state.get("conceptual_intent_fa"),
    )
    inchand_eval = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            cfg,
            source_mode=source_mode,
            order_id_present=order_id_present,
            sandbox_auto_enabled=cfg.agentic_graph_order_lookup_enabled and graph_tools_enabled,
            detected_scenario=detected_scenario,
            scenario_auto_eligible=True,
        ),
    )
    iran_eval = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        build_iran_post_eligibility_context(
            cfg,
            source_mode=source_mode,
            tracking_code_present=tracking_code_present,
            carrier_candidate=str(carrier_candidate or "iran_post"),
            order_delivered_in_inchand=bool(state.get("order_delivered_in_inchand")),
            sandbox_auto_enabled=cfg.agentic_graph_iran_post_verify_enabled and graph_tools_enabled,
        ),
    )
    eligible_tools: list[str] = []
    blocked_tools: list[str] = []
    blocked_reasons: dict[str, str] = {}
    for result in (inchand_eval, iran_eval):
        key = result.tool_id.value
        if result.sandbox_auto_allowed:
            eligible_tools.append(key)
        else:
            blocked_tools.append(key)
            if result.blocked_reason:
                blocked_reasons[key] = result.blocked_reason
    if not graph_tools_enabled:
        blocked_reasons["graph_guardrail"] = "graph_read_only_tools_disabled_or_source_blocked"
    return {
        "graph_tools_enabled": graph_tools_enabled,
        "graph_tool_execution_mode": "sandbox_auto" if graph_tools_enabled else "disabled",
        "graph_tool_metadata": _tool_debug_payload(
            eligible_tools=eligible_tools,
            blocked_tools=blocked_tools,
            blocked_reasons=blocked_reasons,
        ),
        "node_results": _append_node_result(
            state,
            node="plan_read_only_tools",
            status="ok",
            summary=f"tools_enabled={graph_tools_enabled};planned={len(eligible_tools)}",
        ),
    }


def execute_order_lookup_node(
    state: dict[str, Any],
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    metadata = dict(state.get("graph_tool_metadata") or {})
    planned = set(metadata.get("planned_tools") or [])
    executed = list(metadata.get("executed_tools") or [])
    if (
        not state.get("graph_tools_enabled")
        or OperationalToolId.INCHAND_ORDER_LOOKUP.value not in planned
    ):
        return {
            "node_results": _append_node_result(
                state,
                node="execute_order_lookup",
                status="skipped",
                summary="not_planned_or_disabled",
            ),
        }
    text = (state.get("response_target_seller_text") or state.get("first_turn_text") or "").strip()
    extraction = extract_all_inchand_order_ids_with_diagnostics(text)
    multi_order_ids = list(extraction.normalized_order_ids)
    entities = (
        state.get("extracted_entities") if isinstance(state.get("extracted_entities"), dict) else {}
    )
    order_ids = entities.get("order_ids") if isinstance(entities, dict) else []
    if not multi_order_ids and order_ids:
        normalized_from_entities = [
            normalized for raw in order_ids if (normalized := normalize_inchand_order_id(str(raw)))
        ]
        multi_order_ids = list(dict.fromkeys(normalized_from_entities))
    order_id = multi_order_ids[0] if multi_order_ids else None
    if not order_id:
        return {
            "graph_tool_errors": [*list(state.get("graph_tool_errors") or []), "missing_order_id"],
            "multi_order_ids": [],
            "multi_order_batch_count": 0,
            "node_results": _append_node_result(
                state,
                node="execute_order_lookup",
                status="failed",
                summary="missing_order_id",
            ),
        }
    max_auto = int(cfg.multi_order_batch_max_auto_lookup)
    multi_enabled = bool(
        cfg.multi_order_batch_enabled
        and state.get("graph_tools_enabled")
        and str(state.get("source_mode") or "historical_replay") == "manual_sandbox_chat"
        and len(multi_order_ids) >= 2
    )
    limit_exceeded = multi_enabled and len(multi_order_ids) > max_auto
    lookup_ids = multi_order_ids[:max_auto] if multi_enabled else ([order_id] if order_id else [])
    lookup_results: dict[str, dict[str, Any]] = {}
    for idx, lookup_order_id in enumerate(lookup_ids):
        result = lookup_inchand_order(lookup_order_id, settings=cfg)
        safe = result.to_safe_dict()
        lookup_results[lookup_order_id] = safe
        if idx == 0:
            metadata.setdefault("primary_order_lookup_id", lookup_order_id)
    if lookup_results:
        executed.append(OperationalToolId.INCHAND_ORDER_LOOKUP.value)
        metadata["executed_tools"] = list(dict.fromkeys(executed))
    primary_lookup = lookup_results.get(order_id) if order_id else None
    if primary_lookup is None and lookup_results:
        first_key = next(iter(lookup_results.keys()))
        primary_lookup = lookup_results[first_key]
    tool_results = dict(state.get("graph_tool_results") or {})
    tool_results[OperationalToolId.INCHAND_ORDER_LOOKUP.value] = {
        "found": bool((primary_lookup or {}).get("found")),
        "is_delivered_in_inchand": bool((primary_lookup or {}).get("is_delivered_in_inchand")),
        "primary_parcel_tracking_code": (primary_lookup or {}).get("primary_parcel_tracking_code"),
        "order_status": (primary_lookup or {}).get("order_status"),
        "primary_provider_status": (primary_lookup or {}).get("primary_provider_status"),
        "primary_parcel_status_name": (primary_lookup or {}).get("primary_parcel_status_name"),
    }
    metadata["multi_order_candidates_found"] = list(extraction.candidates_found)
    metadata["multi_order_rejected_candidates"] = list(extraction.rejected_candidates)
    metadata["multi_order_duplicate_count"] = int(extraction.duplicate_count)
    metadata["multi_order_batch_limit_exceeded"] = limit_exceeded
    return {
        "order_lookup_result": primary_lookup,
        "multi_order_ids": multi_order_ids,
        "multi_order_lookup_results": lookup_results,
        "multi_order_batch_enabled": multi_enabled,
        "multi_order_batch_count": len(multi_order_ids),
        "multi_order_batch_limit_exceeded": limit_exceeded,
        "graph_tool_results": tool_results,
        "graph_tool_metadata": metadata,
        "node_results": _append_node_result(
            state,
            node="execute_order_lookup",
            status="ok",
            summary=(
                f"orders={len(multi_order_ids)} executed={len(lookup_results)} "
                f"limit_exceeded={limit_exceeded}"
            ),
        ),
    }


def _shipment_decision_from_state(state: dict[str, Any]) -> dict[str, Any] | None:
    text = (state.get("response_target_seller_text") or state.get("first_turn_text") or "").strip()
    entities = (
        state.get("extracted_entities") if isinstance(state.get("extracted_entities"), dict) else {}
    )
    order_ids = entities.get("order_ids") if isinstance(entities, dict) else []
    order_id = normalize_inchand_order_id(str(order_ids[0])) if order_ids else None
    tracking_code = (
        (entities.get("tracking_code") or "").strip() if isinstance(entities, dict) else None
    )
    tracking_code = tracking_code or infer_plausible_iran_post_tracking_code_from_text(text)
    decision = decide_shipment_delivery(
        ShipmentDeliveryDecisionInput(
            seller_text=text,
            detected_scenario=detect_operational_scenario(
                seller_text=text,
                detected_intent=state.get("detected_intent"),
                suggested_action=state.get("suggested_action"),
                conceptual_intent_fa=state.get("conceptual_intent_fa"),
            ),
            order_id=order_id,
            order_lookup_result=state.get("order_lookup_result"),
            order_lookup_attempted=state.get("order_lookup_result") is not None,
            seller_provided_tracking_code=tracking_code,
            seller_provided_carrier=(
                entities.get("tracking_carrier") if isinstance(entities, dict) else None
            ),
            iran_post_tracking_result=state.get("iran_post_tracking_result"),
            source_mode=str(state.get("source_mode") or "historical_replay"),
            tool_execution_mode=str(state.get("graph_tool_execution_mode") or "disabled"),
            ticket_label=state.get("ticket_label"),
            prior_optional_postal_tracking_request_asked=bool(
                (state.get("multi_turn_context_metadata") or {}).get(
                    "multi_turn_tracking_optional"
                ),
            ),
            seller_replied_after_optional_postal_tracking_request=bool(
                (state.get("multi_turn_context_metadata") or {}).get(
                    "multi_turn_pending_request_fulfilled"
                ),
            ),
        ),
    )
    return decision.to_safe_dict()


def shipment_delivery_decision_node(state: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(state.get("graph_tool_metadata") or {})
    executed_tools = {str(item) for item in (metadata.get("executed_tools") or []) if str(item)}
    lookup_result = state.get("order_lookup_result")
    lookup_present = isinstance(lookup_result, dict)
    lookup_found = bool(lookup_result.get("found")) if lookup_present else False
    lookup_delivered = (
        bool(lookup_result.get("is_delivered_in_inchand")) if lookup_present else False
    )
    lookup_executed = OperationalToolId.INCHAND_ORDER_LOOKUP.value in executed_tools
    lookup_source = "none"
    if lookup_executed:
        lookup_source = "graph_auto"
    elif lookup_present:
        lookup_source = "session_cache"
    metadata.update(
        {
            "order_lookup_executed": lookup_executed,
            "order_lookup_result_present_before_decision": lookup_present,
            "order_lookup_found_before_decision": lookup_found,
            "order_lookup_delivered_before_decision": lookup_delivered,
            "order_lookup_result_source": lookup_source,
        },
    )
    multi_order_ids = list(state.get("multi_order_ids") or [])
    multi_enabled = bool(state.get("multi_order_batch_enabled"))
    multi_decision: dict[str, Any] | None = None
    if multi_enabled and len(multi_order_ids) >= 2:
        aggregate = decide_multi_order_shipment(
            MultiOrderShipmentInput(
                seller_text=(
                    state.get("response_target_seller_text") or state.get("first_turn_text") or ""
                ),
                source_mode=str(state.get("source_mode") or "historical_replay"),
                graph_tools_enabled=bool(state.get("graph_tools_enabled")),
                detected_intent=state.get("detected_intent"),
                suggested_action=state.get("suggested_action"),
                conceptual_intent_fa=state.get("conceptual_intent_fa"),
                preloaded_lookup_results=dict(state.get("multi_order_lookup_results") or {}),
                settings=get_settings(),
            ),
        )
        multi_decision = aggregate.to_safe_dict()
        decision = {
            "decision_type": aggregate.decision_type,
            "recommended_reply_fa": aggregate.recommended_reply_fa,
            "should_override_draft": True,
            "data_sources": ["seller_message", "inchand_order_lookup"],
            "tool_recommendations": {
                "order_lookup_recommended": False,
                "iran_post_verification_recommended": False,
                "skip_iran_post_reason": "multi_order_aggregate",
            },
            "order_delivered_in_inchand": aggregate.decision_type == "multi_order_all_delivered",
            "tracking_verification_status": None,
        }
    else:
        decision = _shipment_decision_from_state(state)
    if decision is None:
        return {
            "graph_tool_metadata": metadata,
            "node_results": _append_node_result(
                state,
                node="shipment_delivery_decision",
                status="skipped",
                summary="decision_unavailable",
            ),
        }
    decision_sources = tuple(
        str(item) for item in (decision.get("data_sources") or []) if str(item)
    )
    decision_used_lookup = "inchand_order_lookup" in decision_sources
    tool_results = dict(state.get("graph_tool_results") or {})
    tool_results["shipment_delivery_decision"] = {
        "decision_type": decision.get("decision_type"),
        "order_delivered_in_inchand": bool(decision.get("order_delivered_in_inchand")),
        "tracking_verification_status": decision.get("tracking_verification_status"),
        "decision_used_order_lookup_result": decision_used_lookup,
    }
    return {
        "shipment_delivery_decision": decision,
        "shipment_delivery_decision_type": decision.get("decision_type"),
        "multi_order_decision": multi_decision,
        "multi_order_decision_type": (multi_decision or {}).get("decision_type"),
        "multi_order_summary": (multi_decision or {}).get("summary"),
        "grounded_decision_reply": decision.get("recommended_reply_fa"),
        "order_delivered_in_inchand": bool(decision.get("order_delivered_in_inchand")),
        "decision_used_order_lookup_result": decision_used_lookup,
        "order_lookup_result_source": lookup_source,
        "order_lookup_auto_triggered": lookup_executed,
        "graph_tool_metadata": metadata,
        "graph_tool_results": tool_results,
        "node_results": _append_node_result(
            state,
            node="shipment_delivery_decision",
            status="ok",
            summary=f"type={decision.get('decision_type')}",
        ),
    }


def execute_iran_post_tracking_node(
    state: dict[str, Any],
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    cfg = settings or get_settings()
    decision = state.get("shipment_delivery_decision")
    if not isinstance(decision, dict):
        return {
            "node_results": _append_node_result(
                state,
                node="execute_iran_post_tracking",
                status="skipped",
                summary="no_decision",
            ),
        }
    recommend = bool(
        (decision.get("tool_recommendations") or {}).get("iran_post_verification_recommended")
    )
    if not recommend:
        return {
            "node_results": _append_node_result(
                state,
                node="execute_iran_post_tracking",
                status="skipped",
                summary="not_recommended",
            ),
        }
    entities = (
        state.get("extracted_entities") if isinstance(state.get("extracted_entities"), dict) else {}
    )
    tracking_code = (
        (entities.get("tracking_code") or "").strip() if isinstance(entities, dict) else ""
    )
    if not tracking_code:
        tracking_code = (
            infer_plausible_iran_post_tracking_code_from_text(
                state.get("response_target_seller_text") or state.get("first_turn_text") or "",
            )
            or ""
        )
    eval_result = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        build_iran_post_eligibility_context(
            cfg,
            source_mode=str(state.get("source_mode") or "historical_replay"),
            tracking_code_present=bool(tracking_code),
            carrier_candidate=str(entities.get("tracking_carrier") or "iran_post"),
            order_delivered_in_inchand=bool(decision.get("order_delivered_in_inchand")),
            sandbox_auto_enabled=bool(
                state.get("graph_tools_enabled") and cfg.agentic_graph_iran_post_verify_enabled
            ),
        ),
    )
    if not eval_result.sandbox_auto_allowed:
        metadata = dict(state.get("graph_tool_metadata") or {})
        blocked = dict(metadata.get("blocked_reasons") or {})
        blocked[OperationalToolId.IRAN_POST_TRACKING_VERIFICATION.value] = (
            eval_result.blocked_reason or "eligibility_blocked"
        )
        metadata["blocked_reasons"] = blocked
        return {
            "graph_tool_metadata": metadata,
            "node_results": _append_node_result(
                state,
                node="execute_iran_post_tracking",
                status="skipped",
                summary="eligibility_blocked",
            ),
        }
    result = verify_iran_post_tracking_code(tracking_code, settings=cfg)
    safe = result.to_safe_dict()
    metadata = dict(state.get("graph_tool_metadata") or {})
    executed = list(metadata.get("executed_tools") or [])
    executed.append(OperationalToolId.IRAN_POST_TRACKING_VERIFICATION.value)
    metadata["executed_tools"] = executed
    tool_results = dict(state.get("graph_tool_results") or {})
    tool_results[OperationalToolId.IRAN_POST_TRACKING_VERIFICATION.value] = {
        "verified": bool(safe.get("verified")),
        "status_description": safe.get("status_description"),
        "last_event_description": safe.get("last_event_description"),
        "event_count": safe.get("event_count"),
    }
    return {
        "iran_post_tracking_result": safe,
        "graph_tool_metadata": metadata,
        "graph_tool_results": tool_results,
        "node_results": _append_node_result(
            state,
            node="execute_iran_post_tracking",
            status="ok",
            summary=f"verified={bool(safe.get('verified'))}",
        ),
    }


def shipment_delivery_decision_after_tracking_node(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("multi_order_decision"):
        return {
            "node_results": _append_node_result(
                state,
                node="shipment_delivery_decision_after_tracking",
                status="skipped",
                summary="multi_order_already_decided",
            ),
        }
    decision = _shipment_decision_from_state(state)
    if decision is None:
        return {
            "node_results": _append_node_result(
                state,
                node="shipment_delivery_decision_after_tracking",
                status="skipped",
                summary="decision_unavailable",
            ),
        }
    decision_sources = tuple(
        str(item) for item in (decision.get("data_sources") or []) if str(item)
    )
    decision_used_lookup = "inchand_order_lookup" in decision_sources
    tool_results = dict(state.get("graph_tool_results") or {})
    tool_results["shipment_delivery_decision_after_tracking"] = {
        "decision_type": decision.get("decision_type"),
        "tracking_verification_status": decision.get("tracking_verification_status"),
        "decision_used_order_lookup_result": decision_used_lookup,
    }
    return {
        "shipment_delivery_decision": decision,
        "shipment_delivery_decision_type": decision.get("decision_type"),
        "grounded_decision_reply": decision.get("recommended_reply_fa"),
        "order_delivered_in_inchand": bool(decision.get("order_delivered_in_inchand")),
        "decision_used_order_lookup_result": decision_used_lookup,
        "graph_tool_results": tool_results,
        "node_results": _append_node_result(
            state,
            node="shipment_delivery_decision_after_tracking",
            status="ok",
            summary=f"type={decision.get('decision_type')}",
        ),
    }


def generate_draft_node(
    state: dict[str, Any],
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Internal first-turn draft generation with style + actionability post-processing."""
    multi_meta = state.get("multi_turn_context_metadata") or {}
    if isinstance(multi_meta, dict) and multi_meta.get("multi_turn_should_generate_draft") is False:
        return {
            **state,
            "draft_reply": None,
            "node_results": [
                *list(state.get("node_results") or []),
                {
                    "node": "generate_draft",
                    "status": "skipped",
                    "summary": (
                        f"draft_gating:{multi_meta.get('multi_turn_skip_reason') or 'unknown'}"
                    ),
                },
            ],
        }
    cfg = settings or get_settings()
    ticket = _ticket_from_state(state)
    full = (state.get("full_first_vendor_message_text") or "").strip()
    if full:
        ticket = replace(ticket, full_first_vendor_message_text=full)
    ctx = build_first_turn_draft_context_from_ticket(ticket, settings=cfg)
    case_payload = {
        "room_id": state["room_id"],
        "case_id": f"{state['room_id']}__first_vendor_turn",
        "ticket_label": state.get("ticket_label"),
        "route_label": state.get("route_label"),
        "snapshot_before_reply": {
            "original_vendor_issue_preview": state.get("first_turn_text"),
        },
    }
    policy_hints = ctx.first_turn_policy_hints
    messages = build_offline_draft_messages(
        case_payload,
        intent_result=ctx.first_turn_intent,
        suggested_action=ctx.suggested_action,
        policy_hints=policy_hints,
        first_turn_context=ctx,
        settings=cfg,
    )
    forbidden = extract_forbidden_values_from_benchmark_case(case_payload)
    assert_prompt_messages_safe(
        messages,
        forbidden_values=forbidden,
        first_turn_text=ctx.first_turn_text,
        ticket=ticket,
    )
    provider = str(state.get("_llm_provider") or "mock")
    model = str(state.get("_llm_model") or "mock-vendor-ticket-drafter")
    generate_fn = state.get("_generate_fn")
    _style, _max_sent, _target, hard_max = resolve_effective_draft_style_limits(
        cfg,
        seller_text=ctx.first_turn_text,
        detected_intent=ctx.first_turn_intent.detected_intent,
        suggested_action=ctx.suggested_action,
    )
    max_chars = min(cfg.operator_draft_max_chars, hard_max)

    try:
        draft_provider_label = "mock"
        openai_meta: dict[str, Any] = {}
        panel_metrics: dict[str, Any] = {}

        if provider == "mock" and generate_fn is None:
            entities = ctx.first_turn_entities
            order_ids = tuple(entities.order_ids) if entities else ()
            product_ids = tuple(entities.product_ids) if entities else ()
            tracking = getattr(entities, "primary_tracking_code", None) if entities else None
            draft_text = generate_mock_operational_draft(
                MockOperationalDraftInput(
                    detected_intent=state.get("detected_intent")
                    or ctx.first_turn_intent.detected_intent,
                    conceptual_intent_fa=state.get("conceptual_intent_fa"),
                    suggested_action=ctx.suggested_action,
                    suggested_action_reason=ctx.suggested_action_reason,
                    seller_text=ctx.first_turn_text,
                    order_ids=order_ids,
                    product_ids=product_ids,
                    tracking_code=tracking,
                    actionability=state.get("actionability"),
                    shop_id=state.get("shop_id"),
                ),
                max_chars=max_chars,
            )
            conceptual_fa = state.get("conceptual_intent_fa") or fallback_conceptual_intent_fa(
                ctx.first_turn_intent.detected_intent,
                source_text=ctx.first_turn_text,
            )
            draft_result = DraftWithConceptualIntent(
                draft_reply=draft_text,
                conceptual_intent_fa=conceptual_fa,
            )
        elif provider == "openai":
            from app.agentic_sandbox.openai_draft_provider import (
                generate_openai_draft_for_sandbox_state,
                openai_draft_metrics_row,
            )

            draft_result, openai_generation = generate_openai_draft_for_sandbox_state(
                state,
                ctx,
                settings=cfg,
                generate_fn=generate_fn,
            )
            draft_provider_label = openai_generation.draft_provider
            openai_meta = openai_draft_metrics_row(openai_generation)
            if openai_generation.fallback_warning:
                errors = list(state.get("errors") or [])
                errors.append(openai_generation.fallback_warning)
                state = {**state, "errors": errors}
        else:
            draft_provider_label = provider
            draft_result = generate_draft_with_conceptual_intent(
                messages,
                detected_intent=ctx.first_turn_intent.detected_intent,
                provider=provider,
                model=model,
                generate_fn=generate_fn,
                max_chars=max_chars,
                source_text=ctx.first_turn_text,
            )
        completion = apply_draft_completion_calibration(
            draft_result.draft_reply,
            seller_text=ctx.first_turn_text,
            suggested_action=ctx.suggested_action,
            detected_intent=ctx.first_turn_intent.detected_intent,
            entity_warnings_summary=ctx.first_turn_intent.entity_warnings_summary,
        )
        validation = validate_actionability(
            suggested_action=ctx.suggested_action,
            entities=ctx.first_turn_intent,
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
        )
        draft_text, validation = apply_actionability_to_draft(
            completion.draft_reply,
            validation,
            seller_text=ctx.first_turn_text,
        )
        raw_generated_draft = draft_text.strip()
        entities = ctx.first_turn_entities
        order_ids = tuple(entities.order_ids) if entities and entities.order_ids else ()
        product_ids = tuple(entities.product_ids) if entities and entities.product_ids else ()
        tracking = getattr(entities, "primary_tracking_code", None) if entities else None
        extracted_iban = (
            entities.primary_iban
            if entities and entities.primary_iban
            else ctx.first_turn_intent.extracted_iban
        )
        has_incomplete_iban_entity = entities.has_incomplete_iban_candidate if entities else False
        entity_warnings_summary = (
            entities.entity_warnings_summary if entities else None
        ) or ctx.first_turn_intent.entity_warnings_summary
        draft_text, sufficiency = apply_operational_sufficiency_calibration(
            draft_text,
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
            order_ids=order_ids,
            product_ids=product_ids,
            tracking_code=tracking,
            conceptual_intent_fa=draft_result.conceptual_intent_fa,
            shop_id=state.get("shop_id"),
        )
        draft_text, panel_metrics = apply_panel_issue_draft_calibration(
            draft_text,
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
            conceptual_intent_fa=draft_result.conceptual_intent_fa,
            order_ids=order_ids,
            product_ids=product_ids,
            shop_id=state.get("shop_id"),
        )
        draft_text, _photo_calibrated, _unnecessary_photo = calibrate_photo_evidence_wording(
            draft_text,
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
            conceptual_intent_fa=draft_result.conceptual_intent_fa,
            missing_entities=validation.missing_required_entities,
            product_ids=product_ids,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )
        effective_style = resolve_effective_draft_style(
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
            conceptual_intent_fa=draft_result.conceptual_intent_fa,
        )
        prompt_hints = state.get("knowledge_hints_for_prompt") or ctx.first_turn_policy_hints
        grounding = apply_policy_grounding_calibration(
            draft_text,
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
            draft_style=effective_style,
            hints=tuple(prompt_hints),
            conceptual_intent_fa=draft_result.conceptual_intent_fa,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
        )
        draft_text = grounding.draft_reply
        draft_text, product_wording = apply_product_wording_calibration(
            draft_text,
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
            conceptual_intent_fa=draft_result.conceptual_intent_fa,
            draft_style=effective_style,
            product_ids=product_ids,
        )
        sufficiency_meta = operational_sufficiency_metrics_row(
            sufficiency,
            panel_metrics=panel_metrics,
        )
        if product_wording.product_wording_normalized:
            sufficiency_meta["product_wording_normalized"] = True
        pre_reflection_draft = draft_text.strip()
        multi_meta = state.get("multi_turn_context_metadata") or {}
        if not isinstance(multi_meta, dict):
            multi_meta = {}
        reflection_seller_text = (
            state.get("response_target_seller_text") or ctx.first_turn_text or ""
        )
        draft_text, reflection_result = apply_final_draft_reflection_review(
            draft_text,
            seller_text=reflection_seller_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
            conceptual_intent_fa=draft_result.conceptual_intent_fa,
            draft_style=effective_style,
            order_ids=order_ids,
            product_ids=product_ids,
            tracking_code=tracking,
            extracted_iban=extracted_iban,
            has_incomplete_iban_entity=has_incomplete_iban_entity,
            entity_warnings_summary=entity_warnings_summary,
            shop_id=state.get("shop_id"),
            policy_hints=tuple(prompt_hints),
            draft_provider=draft_provider_label,
            pending_request_type=(
                str(multi_meta.get("multi_turn_pending_request_type") or "").strip() or None
            ),
            pending_request_fulfilled=bool(
                multi_meta.get("multi_turn_pending_request_fulfilled"),
            ),
            tracking_optional=bool(multi_meta.get("multi_turn_tracking_optional")),
            context_order_ids=order_ids,
            context_product_ids=product_ids,
            context_tracking_codes=(tracking,) if tracking else (),
            context_ibans=(extracted_iban,) if extracted_iban else (),
            runtime_shop_identity_available=bool(
                state.get("shop_identity_available")
                or state.get("shop_id")
                or state.get("seller_id")
                or state.get("shop_name")
            ),
            runtime_shop_id_present=bool(state.get("shop_id")),
            settings=cfg,
        )
        reflection_meta = reflection_metadata_row(reflection_result)
        reflection_comparison = reflection_comparison_session_row(
            raw_generated_draft=raw_generated_draft,
            pre_reflection_draft=pre_reflection_draft,
            final_reflected_draft=draft_text.strip(),
            result=reflection_result,
            reflection_enabled=cfg.final_draft_reflection_enabled,
            reflection_provider=cfg.final_draft_reflection_provider,
        )
        assert_draft_reply_safe(draft_text, max_chars=max_chars)
        apply_draft_style_checks(
            draft_text,
            cfg,
            seller_text=ctx.first_turn_text,
            detected_intent=ctx.first_turn_intent.detected_intent,
            suggested_action=ctx.suggested_action,
        )
        node_summary = f"draft_chars={len(draft_text)};draft_provider={draft_provider_label}"
        if openai_meta:
            node_summary += f";quality_ok={openai_meta.get('draft_quality_ok')}"
        if sufficiency.over_questioning:
            node_summary += ";over_questioning=true"

        return {
            "draft_reply": draft_text,
            "conceptual_intent_fa": draft_result.conceptual_intent_fa,
            "draft_provider": draft_provider_label,
            "extracted_entities": _entities_to_dict(
                ctx.first_turn_entities,
                entity_extraction_source=ctx.entity_extraction_source,
            ),
            "entity_extraction_source": ctx.entity_extraction_source,
            "entity_extraction_source_char_count": ctx.entity_extraction_source_char_count,
            "display_preview_char_count": ctx.display_preview_char_count,
            "actionability": actionability_metadata_row(validation),
            "suggested_action": ctx.suggested_action,
            "suggested_action_reason": ctx.suggested_action_reason,
            "detected_intent": ctx.first_turn_intent.detected_intent,
            "openai_draft_metrics": openai_meta or None,
            "operational_sufficiency_metrics": sufficiency_meta,
            "final_draft_reflection_metrics": reflection_meta,
            "final_draft_reflection_comparison": reflection_comparison,
            "node_results": _append_node_result(
                state,
                node="generate_draft",
                status="ok",
                summary=node_summary,
            ),
        }
    except Exception as exc:  # noqa: BLE001
        errors = list(state.get("errors") or [])
        errors.append(f"generate_draft: {exc}")
        failure_update: dict[str, Any] = {
            "errors": errors,
            "node_results": _append_node_result(
                state,
                node="generate_draft",
                status="failed",
                summary=str(exc),
            ),
        }
        existing_draft = state.get("draft_reply")
        if isinstance(existing_draft, str) and existing_draft.strip():
            draft_stripped = existing_draft.strip()
            failure_result = FinalDraftReflectionResult(
                original_draft=draft_stripped,
                final_draft=draft_stripped,
                reviewed=False,
            )
            failure_update["final_draft_reflection_metrics"] = reflection_metadata_row(
                failure_result,
            )
            failure_update["final_draft_reflection_comparison"] = reflection_comparison_session_row(
                raw_generated_draft=draft_stripped,
                pre_reflection_draft=draft_stripped,
                final_reflected_draft=draft_stripped,
                result=failure_result,
                reflection_enabled=cfg.final_draft_reflection_enabled,
                reflection_provider=cfg.final_draft_reflection_provider,
            )
        return failure_update


def grounded_reply_node(state: dict[str, Any]) -> dict[str, Any]:
    """Prefer deterministic grounded reply when shipment decision requires override."""
    decision = state.get("shipment_delivery_decision")
    if not isinstance(decision, dict):
        return {
            "node_results": _append_node_result(
                state,
                node="grounded_reply",
                status="skipped",
                summary="no_shipment_decision",
            ),
        }
    grounded = (decision.get("recommended_reply_fa") or "").strip()
    should_override = bool(decision.get("should_override_draft")) and bool(grounded)
    if not should_override:
        return {
            "tool_grounded_reply_used": False,
            "node_results": _append_node_result(
                state,
                node="grounded_reply",
                status="skipped",
                summary="no_override",
            ),
        }
    reflection_metrics = state.get("final_draft_reflection_metrics")
    if not isinstance(reflection_metrics, dict):
        reflection_metrics = {}
    reflection_metrics = {
        **reflection_metrics,
        "grounded_reply_forced": True,
    }
    if state.get("multi_order_decision_type"):
        reflection_metrics["multi_order_decision_type"] = state.get("multi_order_decision_type")
        reflection_metrics["multi_order_reply_used"] = True
    comparison = state.get("final_draft_reflection_comparison")
    if isinstance(comparison, dict):
        comparison = {
            **comparison,
            "final_reflected_draft": grounded,
        }
    return {
        "draft_reply": grounded,
        "grounded_decision_reply": grounded,
        "tool_grounded_reply_used": True,
        "multi_order_reply_used": bool(state.get("multi_order_decision")),
        "final_draft_reflection_metrics": reflection_metrics,
        "final_draft_reflection_comparison": comparison,
        "node_results": _append_node_result(
            state,
            node="grounded_reply",
            status="ok",
            summary="grounded_reply_applied",
        ),
    }


def safety_gate_node(state: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on forbidden fields, auto-send language, and execution flags."""
    issues: list[str] = []
    if state.get("execution_allowed") is not False:
        issues.append("execution_allowed must be false")
    if state.get("customer_send_allowed") is not False:
        issues.append("customer_send_allowed must be false")
    if state.get("human_review_required") is not True:
        issues.append("human_review_required must be true")

    draft = state.get("draft_reply")
    if isinstance(draft, str):
        lowered = draft.lower()
        for marker in _FORBIDDEN_DRAFT_SUBSTRINGS:
            if marker.lower() in lowered:
                issues.append(f"draft contains forbidden marker: {marker}")

    for field in FIRST_TURN_EXCLUDED_THREAD_FIELDS:
        if field in (state.get("first_turn_text") or ""):
            issues.append(f"first_turn_text references excluded field: {field}")

    for key in state.keys():
        key_str = str(key)
        if key_str in _INTERNAL_EXTRACTION_STATE_KEYS:
            continue
        if key_str.lower() in _FORBIDDEN_OUTPUT_KEYS:
            issues.append(f"forbidden state key present: {key}")

    status = "passed" if not issues else "failed"
    if issues:
        errors = list(state.get("errors") or [])
        errors.extend(issues)
        return {
            "safety_status": status,
            "errors": errors,
            "node_results": _append_node_result(
                state,
                node="safety_gate",
                status="failed",
                summary="; ".join(issues[:3]),
            ),
        }
    return {
        "safety_status": status,
        "node_results": _append_node_result(
            state,
            node="safety_gate",
            status="ok",
            summary="sandbox safety checks passed",
        ),
    }


def human_review_handoff_node(state: dict[str, Any]) -> dict[str, Any]:
    """Prepare read-only operator review payload (no transcript, no send)."""
    hints = state.get("knowledge_hints") or []
    entities = state.get("extracted_entities") or {}
    entity_source = state.get("entity_extraction_source")
    if not entity_source and isinstance(entities, dict):
        entity_source = entities.get("entity_source")
    payload: dict[str, Any] = {
        "room_id": state["room_id"],
        "ticket_label": state.get("ticket_label"),
        "route_label": state.get("route_label"),
        "detected_intent": state.get("detected_intent"),
        "conceptual_intent_fa": state.get("conceptual_intent_fa"),
        "suggested_action": state.get("suggested_action"),
        "suggested_action_reason": state.get("suggested_action_reason"),
        "extracted_entities": entities if isinstance(entities, dict) else {},
        "actionability": state.get("actionability") or {},
        "knowledge_hint_document_types": [
            str(item.get("document_type"))
            for item in hints
            if isinstance(item, dict) and item.get("document_type")
        ],
        "draft_reply": state.get("draft_reply"),
        "safety_status": state.get("safety_status"),
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "entity_source": str(entity_source or ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE),
        "entity_extraction_source": state.get("entity_extraction_source"),
        "entity_extraction_source_char_count": state.get("entity_extraction_source_char_count"),
        "display_preview_char_count": state.get("display_preview_char_count"),
        "first_turn_only": True,
        "graph_tools_enabled": state.get("graph_tools_enabled"),
        "graph_tool_metadata": state.get("graph_tool_metadata") or {},
        "shipment_delivery_decision_type": state.get("shipment_delivery_decision_type"),
        "multi_order_decision_type": state.get("multi_order_decision_type"),
        "multi_order_reply_used": state.get("multi_order_reply_used"),
        "multi_order_summary": state.get("multi_order_summary"),
        "multi_order_decision": state.get("multi_order_decision"),
        "decision_used_order_lookup_result": state.get("decision_used_order_lookup_result"),
        "order_lookup_result_source": state.get("order_lookup_result_source"),
        "order_lookup_auto_triggered": state.get("order_lookup_auto_triggered"),
        "tool_grounded_reply_used": state.get("tool_grounded_reply_used"),
        "order_lookup_found": (
            (state.get("order_lookup_result") or {}).get("found")
            if isinstance(state.get("order_lookup_result"), dict)
            else None
        ),
        "order_delivered_in_inchand": (
            (state.get("order_lookup_result") or {}).get("is_delivered_in_inchand")
            if isinstance(state.get("order_lookup_result"), dict)
            else None
        ),
        "iran_post_verified": (
            (state.get("iran_post_tracking_result") or {}).get("verified")
            if isinstance(state.get("iran_post_tracking_result"), dict)
            else None
        ),
    }
    _handoff_internal_only = frozenset(
        {
            "full_first_vendor_message_text",
            "first_turn_extraction_text",
            "first_turn_full_text",
            "full_first_turn_text",
            "raw_first_turn_text",
        },
    )
    for key in payload:
        if key in _handoff_internal_only:
            raise ValueError(f"handoff payload contains internal-only key: {key}")
        if str(key).lower() in _FORBIDDEN_OUTPUT_KEYS:
            raise ValueError(f"handoff payload contains forbidden key: {key}")

    return {
        "human_review_payload": payload,
        "human_review_required": True,
        "execution_allowed": False,
        "customer_send_allowed": False,
        "node_results": _append_node_result(
            state,
            node="human_review_handoff",
            status="ok",
            summary="read_only_handoff_ready",
        ),
    }
