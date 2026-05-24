"""Deterministic sandbox nodes orchestrating existing safe draft/HITL components."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

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
from app.workflows.operational_entity_extraction import (
    OperationalEntityExtractionResult,
    extract_operational_entities,
)
from app.workflows.operational_information_sufficiency import (
    apply_operational_sufficiency_calibration,
    operational_sufficiency_metrics_row,
)
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits
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
    extraction_text = state.get("first_turn_extraction_text") or state.get("first_turn_text") or ""
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


def generate_draft_node(
    state: dict[str, Any],
    *,
    settings: AppSettings | None = None,
) -> dict[str, Any]:
    """Internal first-turn draft generation with style + actionability post-processing."""
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
        sufficiency_meta = operational_sufficiency_metrics_row(sufficiency)
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
        return {
            "errors": errors,
            "node_results": _append_node_result(
                state,
                node="generate_draft",
                status="failed",
                summary=str(exc),
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
