"""Read-only agentic sandbox graph preview for the operator console (session-only)."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any

from app.agentic_sandbox.agentic_graph import (
    NODE_ORDER,
    run_agentic_sandbox_workflow,
)
from app.agentic_sandbox.agentic_graph import (
    initial_state_from_ticket as graph_initial_from_ticket,
)
from app.agentic_sandbox.agentic_state import AgenticSandboxState
from app.config import AppSettings, get_settings
from app.evals.draft_style import resolve_draft_style_limits
from app.evals.first_turn_draft_context import ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
from app.evals.offline_draft_generation import assert_draft_reply_safe
from app.operator_console.console_models import OperatorTicket
from app.operator_console.i18n import DEFAULT_CONSOLE_LANG, t

SESSION_AGENTIC_PREVIEW_KEY = "operator_agentic_sandbox_previews"

_FORBIDDEN_PREVIEW_KEYS = frozenset(
    {
        "messages",
        "user_input",
        "gold_reference_reply",
        "conversation_transcript",
        "transcript",
        "retrieved_context",
        "retrieval_results",
        "raw_prompt",
        "raw_snippets",
        "draft_response",
        "final_response",
        "open_ticket_preview",
        "ticket_text_preview",
        "recent_context_preview",
        "latest_vendor_message",
        "full_first_vendor_message_text",
        "first_turn_extraction_text",
        "human_review_payload",
        "_generate_fn",
        "_llm_provider",
        "_llm_model",
        "knowledge_hints",
        "raw_generated_draft",
        "pre_reflection_draft",
        "final_reflected_draft",
        "final_draft_reflection_comparison",
    },
)

# Session-only preview fields — never exported via to_public_dict / reports.
_SESSION_ONLY_PREVIEW_FIELDS = frozenset(
    {
        "raw_generated_draft",
        "pre_reflection_draft",
        "final_reflected_draft",
    },
)

# Internal graph state only — strip before preview/report serialization.
_INTERNAL_PREVIEW_STATE_KEYS_TO_STRIP = frozenset(
    {
        "full_first_vendor_message_text",
        "first_turn_extraction_text",
        "first_turn_full_text",
        "full_first_turn_text",
        "raw_first_turn_text",
        "messages",
        "transcript",
        "conversation_transcript",
        "raw_prompt",
        "retrieval_results",
        "raw_snippets",
        "human_review_payload",
        "knowledge_hints",
        "knowledge_hints_for_prompt",
        "final_draft_reflection_comparison",
        "_generate_fn",
        "_llm_provider",
        "_llm_model",
    },
)

_FORBIDDEN_PREVIEW_SUBSTRINGS = (
    "conversation transcript",
    '"messages"',
    "gold_reference_reply",
    '"snippet":',
    "sk-",
    "postgresql://",
)


@dataclass(frozen=True)
class AgenticSandboxPreviewResult:
    """Safe sandbox graph output for operator console display."""

    room_id: str
    graph_status: str
    node_statuses: dict[str, str]
    node_summaries: tuple[tuple[str, str, str], ...]
    detected_intent: str | None
    conceptual_intent_fa: str | None
    suggested_action: str | None
    suggested_action_reason: str | None
    actionability_actionable: bool | None
    missing_required_entities: str | None
    actionability_validation_reason: str | None
    entity_source: str | None
    entity_extraction_source: str | None
    entity_extraction_source_char_count: int | None
    display_preview_char_count: int | None
    order_id_count: int
    product_id_count: int
    extracted_order_ids: str | None
    extracted_product_ids: str | None
    extracted_tracking_code: str | None
    extracted_tracking_carrier: str | None
    extracted_iban_masked: str | None
    entity_warnings_summary: str | None
    knowledge_hints_enabled: bool
    knowledge_hint_count: int
    knowledge_hint_document_types: tuple[str, ...]
    draft_char_count: int
    safety_status: str | None
    human_review_required: bool
    execution_allowed: bool
    customer_send_allowed: bool
    errors: tuple[str, ...]
    draft_reply: str | None = None
    draft_style: str | None = None
    draft_is_mock: bool = False
    draft_provider: str | None = None
    reflection_reviewed: bool | None = None
    reflection_rewrite_applied: bool | None = None
    reflection_issue_types: tuple[str, ...] = ()
    reflection_issue_count: int = 0
    reflection_enabled: bool | None = None
    reflection_provider: str | None = None
    reflection_comparison_available: bool = False
    reflection_runtime_shop_identity_available: bool | None = None
    reflection_runtime_shop_id_present: bool | None = None
    reflection_unnecessary_identifier_detected: bool | None = None
    multi_turn_context_enabled: bool | None = None
    multi_turn_message_count: int | None = None
    multi_turn_latest_sender_type: str | None = None
    multi_turn_pending_request_type: str | None = None
    multi_turn_pending_request_fulfilled: bool | None = None
    multi_turn_should_generate_draft: bool | None = None
    multi_turn_skip_reason: str | None = None
    tracking_verification_recommended: bool | None = None
    tracking_verification_carrier_candidate: str | None = None
    inchand_order_lookup_recommended: bool | None = None
    inchand_order_id_candidate: str | None = None
    graph_tools_enabled: bool | None = None
    graph_tools_planned: tuple[str, ...] = ()
    graph_tools_executed: tuple[str, ...] = ()
    graph_tools_blocked: tuple[str, ...] = ()
    graph_tools_blocked_reasons: dict[str, str] = field(default_factory=dict)
    shipment_delivery_decision_type: str | None = None
    multi_order_decision_type: str | None = None
    multi_order_reply_used: bool | None = None
    multi_order_summary: dict[str, Any] = field(default_factory=dict)
    multi_order_decision: dict[str, Any] = field(default_factory=dict)
    decision_used_order_lookup_result: bool | None = None
    order_lookup_result_source: str | None = None
    order_lookup_auto_triggered: bool | None = None
    tool_grounded_reply_used: bool | None = None
    order_lookup_found: bool | None = None
    order_delivered_in_inchand: bool | None = None
    parcel_tracking_code_present: bool | None = None
    iran_post_verified: bool | None = None
    policy_question_type: str | None = None
    raw_generated_draft: str | None = None
    pre_reflection_draft: str | None = None
    final_reflected_draft: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "graph_status": self.graph_status,
            "node_statuses": dict(self.node_statuses),
            "node_summaries": [
                {"node": node, "status": status, "summary": summary}
                for node, status, summary in self.node_summaries
            ],
            "detected_intent": self.detected_intent,
            "conceptual_intent_fa": self.conceptual_intent_fa,
            "suggested_action": self.suggested_action,
            "suggested_action_reason": self.suggested_action_reason,
            "actionability_actionable": self.actionability_actionable,
            "missing_required_entities": self.missing_required_entities,
            "actionability_validation_reason": self.actionability_validation_reason,
            "entity_source": self.entity_source,
            "entity_extraction_source": self.entity_extraction_source,
            "entity_extraction_source_char_count": self.entity_extraction_source_char_count,
            "display_preview_char_count": self.display_preview_char_count,
            "order_id_count": self.order_id_count,
            "product_id_count": self.product_id_count,
            "extracted_order_ids": self.extracted_order_ids,
            "extracted_product_ids": self.extracted_product_ids,
            "extracted_tracking_code": self.extracted_tracking_code,
            "extracted_tracking_carrier": self.extracted_tracking_carrier,
            "extracted_iban_masked": self.extracted_iban_masked,
            "entity_warnings_summary": self.entity_warnings_summary,
            "knowledge_hints_enabled": self.knowledge_hints_enabled,
            "knowledge_hint_count": self.knowledge_hint_count,
            "knowledge_hint_document_types": list(self.knowledge_hint_document_types),
            "draft_char_count": self.draft_char_count,
            "draft_reply": self.draft_reply,
            "draft_style": self.draft_style,
            "draft_is_mock": self.draft_is_mock,
            "draft_provider": self.draft_provider,
            "safety_status": self.safety_status,
            "human_review_required": self.human_review_required,
            "execution_allowed": self.execution_allowed,
            "customer_send_allowed": self.customer_send_allowed,
            "errors": list(self.errors),
            "reflection_reviewed": self.reflection_reviewed,
            "reflection_rewrite_applied": self.reflection_rewrite_applied,
            "reflection_issue_types": list(self.reflection_issue_types),
            "reflection_issue_count": self.reflection_issue_count,
            "reflection_enabled": self.reflection_enabled,
            "reflection_provider": self.reflection_provider,
            "reflection_comparison_available": self.reflection_comparison_available,
            "reflection_runtime_shop_identity_available": (
                self.reflection_runtime_shop_identity_available
            ),
            "reflection_runtime_shop_id_present": self.reflection_runtime_shop_id_present,
            "reflection_unnecessary_identifier_detected": (
                self.reflection_unnecessary_identifier_detected
            ),
            "multi_turn_context_enabled": self.multi_turn_context_enabled,
            "multi_turn_message_count": self.multi_turn_message_count,
            "multi_turn_latest_sender_type": self.multi_turn_latest_sender_type,
            "multi_turn_pending_request_type": self.multi_turn_pending_request_type,
            "multi_turn_pending_request_fulfilled": self.multi_turn_pending_request_fulfilled,
            "multi_turn_should_generate_draft": self.multi_turn_should_generate_draft,
            "multi_turn_skip_reason": self.multi_turn_skip_reason,
            "tracking_verification_recommended": self.tracking_verification_recommended,
            "tracking_verification_carrier_candidate": (
                self.tracking_verification_carrier_candidate
            ),
            "inchand_order_lookup_recommended": self.inchand_order_lookup_recommended,
            "inchand_order_id_candidate": self.inchand_order_id_candidate,
            "graph_tools_enabled": self.graph_tools_enabled,
            "graph_tools_planned": list(self.graph_tools_planned),
            "graph_tools_executed": list(self.graph_tools_executed),
            "graph_tools_blocked": list(self.graph_tools_blocked),
            "graph_tools_blocked_reasons": dict(self.graph_tools_blocked_reasons),
            "shipment_delivery_decision_type": self.shipment_delivery_decision_type,
            "multi_order_decision_type": self.multi_order_decision_type,
            "multi_order_reply_used": self.multi_order_reply_used,
            "multi_order_summary": dict(self.multi_order_summary),
            "multi_order_decision": dict(self.multi_order_decision),
            "decision_used_order_lookup_result": self.decision_used_order_lookup_result,
            "order_lookup_result_source": self.order_lookup_result_source,
            "order_lookup_auto_triggered": self.order_lookup_auto_triggered,
            "tool_grounded_reply_used": self.tool_grounded_reply_used,
            "order_lookup_found": self.order_lookup_found,
            "order_delivered_in_inchand": self.order_delivered_in_inchand,
            "parcel_tracking_code_present": self.parcel_tracking_code_present,
            "iran_post_verified": self.iran_post_verified,
        }


def _multi_turn_should_skip_draft_generation(initial: Mapping[str, Any]) -> bool:
    multi_meta = initial.get("multi_turn_context_metadata")
    if not isinstance(multi_meta, dict):
        return False
    return multi_meta.get("multi_turn_should_generate_draft") is False


def _build_skipped_draft_preview(
    ticket: OperatorTicket,
    initial: Mapping[str, Any],
    *,
    settings: AppSettings,
) -> AgenticSandboxPreviewResult:
    """Return a safe preview when multi-turn gating blocks draft generation (no graph run)."""
    multi_meta = initial.get("multi_turn_context_metadata")
    if not isinstance(multi_meta, dict):
        multi_meta = {}
    skip_reason = multi_meta.get("multi_turn_skip_reason")
    skip_reason_str = str(skip_reason).strip() if skip_reason else None
    node_statuses = {node: "skipped" for node in NODE_ORDER}
    summaries = (
        (
            "build_first_turn_context",
            "skipped",
            f"draft_gating:{skip_reason_str or 'unknown'}",
        ),
    )
    return AgenticSandboxPreviewResult(
        room_id=ticket.room_id,
        graph_status="skipped",
        node_statuses=node_statuses,
        node_summaries=summaries,
        detected_intent=None,
        conceptual_intent_fa=None,
        suggested_action=None,
        suggested_action_reason=None,
        actionability_actionable=None,
        missing_required_entities=None,
        actionability_validation_reason=None,
        entity_source=None,
        entity_extraction_source=initial.get("entity_extraction_source"),
        entity_extraction_source_char_count=initial.get("entity_extraction_source_char_count"),
        display_preview_char_count=initial.get("display_preview_char_count"),
        order_id_count=0,
        product_id_count=0,
        extracted_order_ids=None,
        extracted_product_ids=None,
        extracted_tracking_code=None,
        extracted_tracking_carrier=None,
        extracted_iban_masked=None,
        entity_warnings_summary=None,
        knowledge_hints_enabled=settings.operator_agentic_sandbox_knowledge_hints_enabled,
        knowledge_hint_count=0,
        knowledge_hint_document_types=(),
        draft_char_count=0,
        safety_status=None,
        human_review_required=True,
        execution_allowed=False,
        customer_send_allowed=False,
        errors=(),
        draft_reply=None,
        draft_style=None,
        draft_is_mock=False,
        draft_provider=None,
        reflection_reviewed=False,
        reflection_rewrite_applied=False,
        reflection_issue_types=(),
        reflection_issue_count=0,
        reflection_enabled=settings.final_draft_reflection_enabled,
        reflection_provider=(settings.final_draft_reflection_provider or "rule_based").strip(),
        reflection_comparison_available=False,
        multi_turn_context_enabled=multi_meta.get("multi_turn_context_enabled"),
        multi_turn_message_count=multi_meta.get("multi_turn_message_count"),
        multi_turn_latest_sender_type=_optional_str(
            multi_meta.get("multi_turn_latest_sender_type"),
        ),
        multi_turn_pending_request_type=_optional_str(
            multi_meta.get("multi_turn_pending_request_type"),
        ),
        multi_turn_pending_request_fulfilled=multi_meta.get("multi_turn_pending_request_fulfilled"),
        multi_turn_should_generate_draft=False,
        multi_turn_skip_reason=skip_reason_str,
        tracking_verification_recommended=multi_meta.get("tracking_verification_recommended"),
        tracking_verification_carrier_candidate=_optional_str(
            multi_meta.get("tracking_verification_carrier_candidate"),
        ),
        inchand_order_lookup_recommended=multi_meta.get("inchand_order_lookup_recommended"),
        inchand_order_id_candidate=_optional_str(multi_meta.get("inchand_order_id_candidate")),
        graph_tools_enabled=False,
        graph_tools_planned=(),
        graph_tools_executed=(),
        graph_tools_blocked=(),
        graph_tools_blocked_reasons={},
        shipment_delivery_decision_type=None,
        multi_order_decision_type=None,
        multi_order_reply_used=False,
        multi_order_summary={},
        multi_order_decision={},
        decision_used_order_lookup_result=None,
        order_lookup_result_source="none",
        order_lookup_auto_triggered=False,
        tool_grounded_reply_used=False,
        order_lookup_found=None,
        order_delivered_in_inchand=None,
        parcel_tracking_code_present=None,
        iran_post_verified=None,
        policy_question_type="none",
    )


def build_agentic_preview_input_from_ticket(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
    conversation_snapshot: Any | None = None,
    source_mode: str = "historical_replay",
) -> AgenticSandboxState:
    """Build sandbox initial state from HITL-safe ticket fields (first-turn only)."""
    from app.operator_console.assisted_ticket_input_builder import (
        AssistedSourceMode,
        build_assisted_graph_input_from_operator_ticket,
    )

    cfg = settings or get_settings()
    mode: AssistedSourceMode = (
        source_mode  # type: ignore[assignment]
        if source_mode in {"historical_replay", "live_api_feed", "manual_sandbox_chat"}
        else "historical_replay"
    )
    bundle = build_assisted_graph_input_from_operator_ticket(
        ticket,
        conversation_snapshot=conversation_snapshot,
        source_mode=mode,
        settings=cfg,
    )
    provider = cfg.operator_agentic_sandbox_provider.strip().lower()
    model = cfg.openai_draft_model if provider == "openai" else "mock-vendor-ticket-drafter"
    return graph_initial_from_ticket(
        bundle.ticket,
        llm_provider=provider,
        llm_model=model,
        generate_fn=None,
        knowledge_hints_enabled=cfg.operator_agentic_sandbox_knowledge_hints_enabled,
        settings=cfg,
        conversation_snapshot=bundle.conversation_snapshot,
        source_mode=mode,
    )


def _preview_runtime_settings(settings: AppSettings) -> AppSettings:
    return settings.model_copy(
        update={
            "knowledge_hints_enabled": settings.operator_agentic_sandbox_knowledge_hints_enabled,
        },
    )


def _node_statuses_from_state(state: Mapping[str, Any]) -> dict[str, str]:
    statuses = {node: "pending" for node in NODE_ORDER}
    for entry in state.get("node_results") or []:
        if not isinstance(entry, dict):
            continue
        node = entry.get("node")
        status = entry.get("status")
        if isinstance(node, str) and node in statuses and isinstance(status, str):
            statuses[node] = status
    return statuses


def _node_summaries_from_state(state: Mapping[str, Any]) -> tuple[tuple[str, str, str], ...]:
    summaries: list[tuple[str, str, str]] = []
    for entry in state.get("node_results") or []:
        if not isinstance(entry, dict):
            continue
        node = str(entry.get("node") or "")
        status = str(entry.get("status") or "unknown")
        summary = str(entry.get("summary") or "")
        if node in NODE_ORDER:
            summaries.append((node, status, summary[:120]))
    return tuple(summaries)


def _entity_display_fields(entities: Mapping[str, Any] | None) -> dict[str, Any]:
    if not entities:
        return {
            "entity_source": ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
            "order_id_count": 0,
            "product_id_count": 0,
            "extracted_order_ids": None,
            "extracted_product_ids": None,
            "extracted_tracking_code": None,
            "extracted_tracking_carrier": None,
            "extracted_iban_masked": None,
            "entity_warnings_summary": None,
        }
    orders = entities.get("order_ids") or []
    products = entities.get("product_ids") or []
    order_count = len(orders) if isinstance(orders, list) else 0
    product_count = len(products) if isinstance(products, list) else 0
    order_display = ", ".join(str(item) for item in orders) if isinstance(orders, list) else None
    product_display = (
        ", ".join(str(item) for item in products) if isinstance(products, list) else None
    )
    tracking = entities.get("tracking_code")
    return {
        "entity_source": str(entities.get("entity_source") or ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE),
        "order_id_count": order_count,
        "product_id_count": product_count,
        "extracted_order_ids": order_display or None,
        "extracted_product_ids": product_display or None,
        "extracted_tracking_code": str(tracking).strip() if tracking else None,
        "extracted_tracking_carrier": entities.get("tracking_carrier"),
        "extracted_iban_masked": entities.get("iban_masked"),
        "entity_warnings_summary": entities.get("warnings_summary"),
    }


def strip_internal_agentic_preview_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Remove internal extraction/runtime keys from graph state before preview mapping."""
    return {
        key: value
        for key, value in state.items()
        if key not in _INTERNAL_PREVIEW_STATE_KEYS_TO_STRIP
    }


def _collect_mapping_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            keys.add(str(key))
            keys |= _collect_mapping_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            keys |= _collect_mapping_keys(item)
    return keys


def _iter_string_values(obj: Any) -> list[str]:
    values: list[str] = []
    if isinstance(obj, str):
        values.append(obj)
    elif isinstance(obj, Mapping):
        for value in obj.values():
            values.extend(_iter_string_values(value))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_iter_string_values(item))
    return values


def _resolve_safe_draft_for_preview(
    safe_state: Mapping[str, Any],
    *,
    settings: AppSettings | None = None,
    llm_provider: str | None = None,
) -> tuple[str | None, str | None, bool, str | None]:
    """Return (draft_reply, draft_style, is_mock, draft_provider) when safety checks pass."""
    if safe_state.get("safety_status") != "passed":
        return None, None, False, None
    errors = safe_state.get("errors") or []
    if errors:
        return None, None, False, None
    draft = safe_state.get("draft_reply")
    if not isinstance(draft, str) or not draft.strip():
        return None, None, False, None

    cfg = settings or get_settings()
    style, _max_sent, _target, hard_max = resolve_draft_style_limits(cfg)
    try:
        assert_draft_reply_safe(draft, max_chars=hard_max)
    except ValueError:
        return None, None, False, None

    draft_provider_raw = safe_state.get("draft_provider")
    draft_provider = (
        str(draft_provider_raw).strip().lower()
        if isinstance(draft_provider_raw, str) and draft_provider_raw.strip()
        else None
    )
    llm_provider_norm = (
        (llm_provider or cfg.operator_agentic_sandbox_provider or "mock").strip().lower()
    )
    effective_provider = draft_provider or llm_provider_norm
    is_mock = effective_provider in {"mock", "mock_fallback"}
    return draft.strip(), style, is_mock, effective_provider


def sanitize_agentic_preview_result(
    state: Mapping[str, Any],
    *,
    knowledge_hints_enabled: bool,
    settings: AppSettings | None = None,
    llm_provider: str | None = None,
) -> AgenticSandboxPreviewResult:
    """Map final graph state to a console-safe preview (validated draft when allowed)."""
    safe_state = strip_internal_agentic_preview_state(state)
    actionability = safe_state.get("actionability") or {}
    if not isinstance(actionability, dict):
        actionability = {}
    entities = safe_state.get("extracted_entities") or {}
    if not isinstance(entities, dict):
        entities = {}
    entity_fields = _entity_display_fields(entities)

    hints = state.get("knowledge_hints") or []
    hint_count = len(hints) if isinstance(hints, list) else 0
    hint_types: list[str] = []
    if isinstance(hints, list):
        for item in hints:
            if isinstance(item, dict) and item.get("document_type"):
                hint_types.append(str(item["document_type"]))

    extraction_source = (
        _optional_str(safe_state.get("entity_extraction_source")) or entity_fields["entity_source"]
    )
    extraction_chars = safe_state.get("entity_extraction_source_char_count")
    preview_chars = safe_state.get("display_preview_char_count")

    draft_raw = safe_state.get("draft_reply")
    draft_chars = len(draft_raw) if isinstance(draft_raw, str) else 0
    safe_draft, draft_style, draft_is_mock, draft_provider = _resolve_safe_draft_for_preview(
        safe_state,
        settings=settings,
        llm_provider=llm_provider,
    )
    errors = tuple(str(e) for e in (safe_state.get("errors") or []) if str(e).strip())
    node_statuses = _node_statuses_from_state(safe_state)
    safety = safe_state.get("safety_status")
    graph_ok = safety == "passed" and not errors and draft_chars > 0
    reflection_metrics = safe_state.get("final_draft_reflection_metrics") or {}
    if not isinstance(reflection_metrics, dict):
        reflection_metrics = {}
    reflection_issue_types_raw = reflection_metrics.get("reflection_issue_types") or []
    reflection_issue_types = tuple(
        str(item) for item in reflection_issue_types_raw if str(item).strip()
    )
    cfg = settings or get_settings()
    comparison = state.get("final_draft_reflection_comparison") or {}
    if not isinstance(comparison, dict):
        comparison = {}
    pre_reflection = _optional_str(comparison.get("pre_reflection_draft"))
    final_reflected = _optional_str(comparison.get("final_reflected_draft")) or safe_draft
    raw_generated = _optional_str(comparison.get("raw_generated_draft"))
    reflection_enabled = comparison.get("reflection_enabled")
    if reflection_enabled is None:
        reflection_enabled = cfg.final_draft_reflection_enabled
    reflection_provider = _optional_str(comparison.get("reflection_provider")) or (
        (cfg.final_draft_reflection_provider or "rule_based").strip()
    )
    if comparison:
        from app.agentic_sandbox.final_draft_reflection import (
            assert_reflection_comparison_session_safe,
        )

        assert_reflection_comparison_session_safe(comparison)
    if safe_draft:
        if not pre_reflection:
            pre_reflection = safe_draft
        if not final_reflected:
            final_reflected = safe_draft
    reflection_comparison_available = bool((pre_reflection or "").strip())

    multi_meta = safe_state.get("multi_turn_context_metadata") or {}
    if not isinstance(multi_meta, dict):
        multi_meta = {}
    graph_tool_metadata = safe_state.get("graph_tool_metadata") or {}
    if not isinstance(graph_tool_metadata, dict):
        graph_tool_metadata = {}
    graph_tool_results = safe_state.get("graph_tool_results") or {}
    if not isinstance(graph_tool_results, dict):
        graph_tool_results = {}
    order_lookup_result = safe_state.get("order_lookup_result") or {}
    if not isinstance(order_lookup_result, dict):
        order_lookup_result = {}
    iran_result = safe_state.get("iran_post_tracking_result") or {}
    if not isinstance(iran_result, dict):
        iran_result = {}

    from app.knowledge.policy_fact_extraction import resolve_policy_question_type

    seller_text = _seller_text_from_preview_state(state)
    policy_question_type = resolve_policy_question_type(
        seller_text,
        detected_intent=_optional_str(safe_state.get("detected_intent")),
        conceptual_intent_fa=_optional_str(safe_state.get("conceptual_intent_fa")),
        suggested_action=_optional_str(safe_state.get("suggested_action")),
    )

    return AgenticSandboxPreviewResult(
        room_id=str(safe_state.get("room_id") or ""),
        graph_status="ok" if graph_ok else "failed",
        node_statuses=node_statuses,
        node_summaries=_node_summaries_from_state(safe_state),
        detected_intent=_optional_str(safe_state.get("detected_intent")),
        conceptual_intent_fa=_optional_str(safe_state.get("conceptual_intent_fa")),
        suggested_action=_optional_str(safe_state.get("suggested_action")),
        suggested_action_reason=_optional_str(safe_state.get("suggested_action_reason")),
        actionability_actionable=actionability.get("actionability_actionable"),
        missing_required_entities=_optional_str(
            actionability.get("actionability_missing_entities")
        ),
        actionability_validation_reason=_optional_str(
            actionability.get("actionability_validation_reason"),
        ),
        entity_source=entity_fields["entity_source"],
        entity_extraction_source=extraction_source,
        entity_extraction_source_char_count=(
            int(extraction_chars) if extraction_chars is not None else None
        ),
        display_preview_char_count=int(preview_chars) if preview_chars is not None else None,
        order_id_count=int(entity_fields["order_id_count"]),
        product_id_count=int(entity_fields["product_id_count"]),
        extracted_order_ids=entity_fields["extracted_order_ids"],
        extracted_product_ids=entity_fields["extracted_product_ids"],
        extracted_tracking_code=entity_fields["extracted_tracking_code"],
        extracted_tracking_carrier=_optional_str(entity_fields["extracted_tracking_carrier"]),
        extracted_iban_masked=_optional_str(entity_fields["extracted_iban_masked"]),
        entity_warnings_summary=_optional_str(entity_fields["entity_warnings_summary"]),
        knowledge_hints_enabled=knowledge_hints_enabled,
        knowledge_hint_count=hint_count,
        knowledge_hint_document_types=tuple(dict.fromkeys(hint_types)),
        draft_char_count=draft_chars,
        draft_reply=safe_draft,
        draft_style=draft_style,
        draft_is_mock=draft_is_mock,
        draft_provider=draft_provider,
        safety_status=_optional_str(safety),
        human_review_required=bool(safe_state.get("human_review_required")),
        execution_allowed=bool(safe_state.get("execution_allowed")),
        customer_send_allowed=bool(safe_state.get("customer_send_allowed")),
        errors=errors,
        reflection_reviewed=reflection_metrics.get("reflection_reviewed"),
        reflection_rewrite_applied=reflection_metrics.get("reflection_rewrite_applied"),
        reflection_issue_types=reflection_issue_types,
        reflection_issue_count=len(reflection_issue_types),
        reflection_enabled=bool(reflection_enabled),
        reflection_provider=reflection_provider,
        reflection_comparison_available=reflection_comparison_available,
        reflection_runtime_shop_identity_available=reflection_metrics.get(
            "reflection_runtime_shop_identity_available",
        ),
        reflection_runtime_shop_id_present=reflection_metrics.get(
            "reflection_runtime_shop_id_present",
        ),
        reflection_unnecessary_identifier_detected=reflection_metrics.get(
            "reflection_unnecessary_identifier_detected",
        ),
        multi_turn_context_enabled=multi_meta.get("multi_turn_context_enabled"),
        multi_turn_message_count=multi_meta.get("multi_turn_message_count"),
        multi_turn_latest_sender_type=_optional_str(
            multi_meta.get("multi_turn_latest_sender_type")
        ),
        multi_turn_pending_request_type=_optional_str(
            multi_meta.get("multi_turn_pending_request_type"),
        ),
        multi_turn_pending_request_fulfilled=multi_meta.get("multi_turn_pending_request_fulfilled"),
        multi_turn_should_generate_draft=multi_meta.get("multi_turn_should_generate_draft"),
        multi_turn_skip_reason=_optional_str(multi_meta.get("multi_turn_skip_reason")),
        tracking_verification_recommended=multi_meta.get("tracking_verification_recommended"),
        tracking_verification_carrier_candidate=_optional_str(
            multi_meta.get("tracking_verification_carrier_candidate"),
        ),
        inchand_order_lookup_recommended=multi_meta.get("inchand_order_lookup_recommended"),
        inchand_order_id_candidate=_optional_str(multi_meta.get("inchand_order_id_candidate")),
        graph_tools_enabled=safe_state.get("graph_tools_enabled"),
        graph_tools_planned=tuple(
            str(item) for item in (graph_tool_metadata.get("planned_tools") or []) if str(item)
        ),
        graph_tools_executed=tuple(
            str(item) for item in (graph_tool_metadata.get("executed_tools") or []) if str(item)
        ),
        graph_tools_blocked=tuple(
            str(item) for item in (graph_tool_metadata.get("blocked_tools") or []) if str(item)
        ),
        graph_tools_blocked_reasons={
            str(key): str(value)
            for key, value in (graph_tool_metadata.get("blocked_reasons") or {}).items()
            if str(key).strip() and str(value).strip()
        },
        shipment_delivery_decision_type=_optional_str(
            safe_state.get("shipment_delivery_decision_type"),
        ),
        multi_order_decision_type=_optional_str(safe_state.get("multi_order_decision_type")),
        multi_order_reply_used=safe_state.get("multi_order_reply_used"),
        multi_order_summary=dict(safe_state.get("multi_order_summary") or {}),
        multi_order_decision=dict(safe_state.get("multi_order_decision") or {}),
        decision_used_order_lookup_result=safe_state.get("decision_used_order_lookup_result"),
        order_lookup_result_source=_optional_str(safe_state.get("order_lookup_result_source"))
        or "none",
        order_lookup_auto_triggered=safe_state.get("order_lookup_auto_triggered"),
        tool_grounded_reply_used=safe_state.get("tool_grounded_reply_used"),
        order_lookup_found=bool(order_lookup_result.get("found")) if order_lookup_result else None,
        order_delivered_in_inchand=(
            bool(order_lookup_result.get("is_delivered_in_inchand"))
            if order_lookup_result
            else None
        ),
        parcel_tracking_code_present=(
            bool(order_lookup_result.get("primary_parcel_tracking_code"))
            if order_lookup_result
            else None
        ),
        iran_post_verified=bool(iran_result.get("verified")) if iran_result else None,
        policy_question_type=policy_question_type,
        raw_generated_draft=raw_generated,
        pre_reflection_draft=pre_reflection,
        final_reflected_draft=final_reflected,
    )


def _optional_count_display(value: int | None) -> str:
    return str(value) if value is not None else "—"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _seller_text_from_preview_state(state: Mapping[str, Any]) -> str:
    for key in (
        "full_first_vendor_message_text",
        "first_turn_text",
        "original_vendor_issue_preview",
    ):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def assert_agentic_preview_safe(result: AgenticSandboxPreviewResult) -> None:
    """Fail closed if preview violates sandbox HITL safety or leaks forbidden fields."""
    if result.execution_allowed is not False:
        raise ValueError("agentic preview requires execution_allowed=false")
    if result.customer_send_allowed is not False:
        raise ValueError("agentic preview requires customer_send_allowed=false")
    if result.human_review_required is not True:
        raise ValueError("agentic preview requires human_review_required=true")

    draft_reply = getattr(result, "draft_reply", None)
    if draft_reply:
        cfg = get_settings()
        _style, _ms, _target, hard_max = resolve_draft_style_limits(cfg)
        assert_draft_reply_safe(draft_reply, max_chars=hard_max)

    public = result.to_public_dict()
    for session_only_key in _SESSION_ONLY_PREVIEW_FIELDS:
        if session_only_key in public:
            raise ValueError(
                f"agentic preview public export must not contain session field: {session_only_key}"
            )
    for key in _collect_mapping_keys(public):
        if key in _FORBIDDEN_PREVIEW_KEYS:
            raise ValueError(f"agentic preview must not contain forbidden key: {key}")
    for text in _iter_string_values(public):
        lowered = text.lower()
        for token in _FORBIDDEN_PREVIEW_SUBSTRINGS:
            if token.lower() in lowered:
                raise ValueError(f"agentic preview must not contain forbidden token: {token}")


def run_agentic_preview_for_ticket(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
    conversation_snapshot: Any | None = None,
    source_mode: str = "historical_replay",
) -> AgenticSandboxPreviewResult:
    """Run sandbox LangGraph for one ticket; return session-safe preview metadata only."""
    cfg = settings or get_settings()
    initial = build_agentic_preview_input_from_ticket(
        ticket,
        settings=cfg,
        conversation_snapshot=conversation_snapshot,
        source_mode=source_mode,
    )
    if _multi_turn_should_skip_draft_generation(initial):
        preview = _build_skipped_draft_preview(ticket, initial, settings=cfg)
        assert_agentic_preview_safe(preview)
        return preview
    runtime_cfg = _preview_runtime_settings(cfg)
    final = run_agentic_sandbox_workflow(initial, settings=runtime_cfg)
    preview = sanitize_agentic_preview_result(
        final,
        knowledge_hints_enabled=cfg.operator_agentic_sandbox_knowledge_hints_enabled,
        settings=cfg,
        llm_provider=cfg.operator_agentic_sandbox_provider,
    )
    assert_agentic_preview_safe(preview)
    return preview


def render_agentic_preview_markdown_or_lines(
    result: AgenticSandboxPreviewResult,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
) -> list[str]:
    """Markdown lines for Streamlit (validated draft shown separately in UI)."""
    lines = [
        f"- **{t('graph_status', lang)}:** {result.graph_status}",
        f"- **{t('safety_status', lang)}:** {result.safety_status or '—'}",
        f"- **human_review_required:** {result.human_review_required}",
        f"- **execution_allowed:** {result.execution_allowed}",
        f"- **customer_send_allowed:** {result.customer_send_allowed}",
        "",
        "**Nodes**",
    ]
    for node in NODE_ORDER:
        status = result.node_statuses.get(node, "pending")
        lines.append(f"- `{node}`: {status}")
    lines.extend(
        [
            "",
            f"- **{t('detected_intent', lang)}:** {result.detected_intent or '—'}",
            f"- **policy_question_type:** {result.policy_question_type or 'none'}",
            f"- **conceptual_intent_fa:** {result.conceptual_intent_fa or '—'}",
            f"- **{t('suggested_action', lang)}:** {result.suggested_action or '—'}",
            f"- **suggested_action_reason:** {result.suggested_action_reason or '—'}",
            f"- **Actionable:** {result.actionability_actionable}",
            f"- **Missing entities:** {result.missing_required_entities or '—'}",
            f"- **Validation reason:** {result.actionability_validation_reason or '—'}",
            f"- **entity_source:** {result.entity_source or '—'}",
            f"- **entity_extraction_source:** {result.entity_extraction_source or '—'}",
            f"- **entity_extraction_source_char_count:** "
            f"{_optional_count_display(result.entity_extraction_source_char_count)}",
            f"- **display_preview_char_count:** "
            f"{_optional_count_display(result.display_preview_char_count)}",
            f"- **order_id_count:** {result.order_id_count}",
            f"- **product_id_count:** {result.product_id_count}",
        ],
    )
    if result.extracted_order_ids:
        lines.append(f"- **extracted_order_ids:** {result.extracted_order_ids}")
    if result.extracted_product_ids:
        lines.append(f"- **extracted_product_ids:** {result.extracted_product_ids}")
    if result.extracted_tracking_code:
        lines.append(f"- **extracted_tracking_code:** {result.extracted_tracking_code}")
    if result.extracted_tracking_carrier:
        lines.append(f"- **extracted_tracking_carrier:** {result.extracted_tracking_carrier}")
    if result.extracted_iban_masked:
        lines.append(f"- **extracted_iban_masked:** {result.extracted_iban_masked}")
    if result.entity_warnings_summary:
        lines.append(f"- **entity_warnings:** {result.entity_warnings_summary}")
    doc_types = ", ".join(result.knowledge_hint_document_types) or "—"
    lines.extend(
        [
            f"- **knowledge_hints_enabled:** {result.knowledge_hints_enabled}",
            f"- **knowledge_hint_count:** {result.knowledge_hint_count}",
            f"- **knowledge_hint_document_types:** {doc_types}",
            f"- **{t('draft_char_count', lang)}:** {result.draft_char_count}",
        ],
    )
    if result.draft_reply:
        lines.append(f"- **{t('internal_draft_suggestion', lang)}:** (see block below)")
    planned_tools = ", ".join(result.graph_tools_planned) if result.graph_tools_planned else "—"
    executed_tools = ", ".join(result.graph_tools_executed) if result.graph_tools_executed else "—"
    blocked_tools = ", ".join(result.graph_tools_blocked) if result.graph_tools_blocked else "—"
    lines.extend(
        [
            "",
            "**اجرای ابزارهای خواندنی در گراف / Read-only graph tool execution**",
            f"- **tools_enabled:** {result.graph_tools_enabled}",
            f"- **planned_tools:** {planned_tools}",
            f"- **executed_tools:** {executed_tools}",
            f"- **blocked_tools:** {blocked_tools}",
            f"- **blocked_reasons:** {result.graph_tools_blocked_reasons or '—'}",
            f"- **order_lookup_found:** {result.order_lookup_found}",
            f"- **order_delivered_in_inchand:** {result.order_delivered_in_inchand}",
            f"- **parcel_tracking_code_present:** {result.parcel_tracking_code_present}",
            f"- **iran_post_verified:** {result.iran_post_verified}",
            (
                "- **shipment_delivery_decision_type:** "
                f"{result.shipment_delivery_decision_type or '—'}"
            ),
            f"- **multi_order_decision_type:** {result.multi_order_decision_type or '—'}",
            f"- **multi_order_reply_used:** {result.multi_order_reply_used}",
            f"- **order_lookup_auto_triggered:** {result.order_lookup_auto_triggered}",
            f"- **order_lookup_result_source:** {result.order_lookup_result_source or 'none'}",
            (
                "- **decision_used_order_lookup_result:** "
                f"{result.decision_used_order_lookup_result}"
            ),
            f"- **grounded_reply_used:** {result.tool_grounded_reply_used}",
        ],
    )
    if result.multi_order_decision:
        summary = result.multi_order_summary or {}
        per_order = result.multi_order_decision.get("per_order") or []
        lines.extend(
            [
                "",
                "**بررسی چند سفارش / Multi-order batch decision**",
                f"- **batch_count:** {summary.get('batch_count')}",
                f"- **executed_count:** {summary.get('executed_count')}",
                f"- **skipped_count:** {summary.get('skipped_count')}",
                f"- **limit_exceeded:** {summary.get('limit_exceeded')}",
                f"- **aggregate_decision_type:** {result.multi_order_decision_type or '—'}",
                "- **reply_origin:** `multi_order_decision`",
            ],
        )
        if isinstance(per_order, list) and per_order:
            lines.extend(
                [
                    "",
                    (
                        "| order_id | found | order_status | provider_status | parcel_status | "
                        "has_tracking | delivered_in_inchand | decision_type | "
                        "lookup_error_type |"
                    ),
                    "|----------|-------|--------------|-----------------|---------------|--------------|----------------------|---------------|-------------------|",
                ],
            )
            for row in per_order:
                if not isinstance(row, dict):
                    continue
                lines.append(
                    "| "
                    f"`{row.get('order_id') or '—'}` | "
                    f"{row.get('found')} | "
                    f"{row.get('order_status') or '—'} | "
                    f"{row.get('provider_status') or '—'} | "
                    f"{row.get('parcel_status') or '—'} | "
                    f"{row.get('has_tracking')} | "
                    f"{row.get('delivered_in_inchand')} | "
                    f"`{row.get('decision_type') or '—'}` | "
                    f"`{row.get('lookup_error_type') or '—'}` |"
                )
    if result.errors:
        lines.append("")
        lines.append("**Errors**")
        for error in result.errors:
            lines.append(f"- {error[:200]}")
    return lines


def get_session_agentic_preview(
    session_state: Mapping[str, Any],
    room_id: str,
) -> AgenticSandboxPreviewResult | None:
    """Load latest session-only preview for a room."""
    bucket = session_state.get(SESSION_AGENTIC_PREVIEW_KEY, {})
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(room_id)
    if isinstance(value, AgenticSandboxPreviewResult):
        return value
    return None


def store_session_agentic_preview(
    session_state: MutableMapping[str, Any],
    result: AgenticSandboxPreviewResult,
) -> None:
    """Store preview in session only (overwrites prior preview for the room)."""
    bucket = session_state.setdefault(SESSION_AGENTIC_PREVIEW_KEY, {})
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[SESSION_AGENTIC_PREVIEW_KEY] = bucket
    bucket[result.room_id] = result
