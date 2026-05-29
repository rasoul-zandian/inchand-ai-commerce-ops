"""Manual sandbox shipment/delivery decision integration (session-only)."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.config import AppSettings, get_settings
from app.operator_console.agentic_assisted_mode import AgenticAssistedPackage
from app.operator_console.manual_chat_models import (
    SHIPMENT_DELIVERY_DECISION_SOURCE,
    ManualChatMessage,
    utc_now_iso,
)
from app.operator_console.manual_sandbox_auto_tracking import (
    get_tracking_result_for_message,
    latest_seller_message_id,
    manual_sandbox_auto_tracking_verify_enabled,
)
from app.tools.inchand.order_lookup import (
    looks_like_inchand_order_id,
    lookup_inchand_order,
    normalize_inchand_order_id,
)
from app.tools.operational_actions_registry import (
    OperationalToolEligibilityResult,
    OperationalToolId,
    build_inchand_eligibility_context,
    build_iran_post_eligibility_context,
    evaluate_tool_eligibility,
)
from app.workflows.operational_information_sufficiency import (
    detect_operational_scenario,
    is_delivery_completed_seller_message,
    is_shipment_seller_message,
)
from app.workflows.shipment_delivery_decision import (
    ShipmentDeliveryDecision,
    ShipmentDeliveryDecisionInput,
    ShipmentDeliveryDecisionType,
    assert_safe_shipment_decision_payload,
    decide_shipment_delivery,
    is_optional_postal_tracking_request_text,
    is_shipment_or_delivery_case,
)
from app.workflows.vendor_ticket_intent_detection import VendorTicketIntent

SOURCE_MANUAL_SANDBOX_CHAT = "manual_sandbox_chat"

SESSION_MANUAL_SHIPMENT_DECISION_BY_MESSAGE_ID = "manual_sandbox_shipment_decisions_by_message_id"
SESSION_MANUAL_LAST_ORDER_LOOKUP_MESSAGE_ID = "manual_sandbox_last_order_lookup_message_id"
SESSION_MANUAL_ORDER_LOOKUP_BY_ORDER_ID = "manual_sandbox_order_lookup_results_by_order_id"
SESSION_MANUAL_ORCHESTRATION_META = "manual_sandbox_orchestration_meta"

_AUTO_LOOKUP_SCENARIOS = frozenset(
    {
        "delivery_completed",
        "shipment_reshipment",
        "seller_notification",
        "shipment_tracking",
        "delivery_tracking",
    },
)

_SHIPMENT_TRACKING_INTENTS = frozenset(
    {
        VendorTicketIntent.TRACKING_CODE_NOTIFICATION.value,
        "tracking_code_notification",
        "seller_notification",
    },
)

_DELIVERY_TRACKING_INTENTS = frozenset(
    {
        VendorTicketIntent.DELIVERY_CONFIRMATION_REQUEST.value,
        "delivery_confirmation_request",
    },
)


@dataclass(frozen=True)
class ManualOrderLookupOutcome:
    """Outcome of optional auto Inchand lookup (manual sandbox only)."""

    payload: dict[str, Any] | None = None
    cache_hit: bool = False
    auto_triggered: bool = False
    api_called: bool = False


@dataclass(frozen=True)
class ManualShipmentDecisionOutcome:
    decision: ShipmentDeliveryDecision | None = None
    chat_reply: str | None = None
    order_lookup_attempted: bool = False
    order_lookup_stored: bool = False
    order_lookup_cache_hit: bool = False
    order_lookup_auto_triggered: bool = False
    order_lookup_result_source: str = "none"
    decision_used_order_lookup_result: bool = False
    iran_post_auto_attempted: bool = False
    reply_origin: str | None = None


def shipment_delivery_decision_enabled(settings: AppSettings | None = None) -> bool:
    cfg = settings or get_settings()
    return bool(cfg.shipment_delivery_decision_enabled)


def is_manual_sandbox_auto_order_lookup_enabled(settings: AppSettings | None = None) -> bool:
    """True when controlled auto Inchand lookup is allowed in manual sandbox."""
    cfg = settings or get_settings()
    context = build_inchand_eligibility_context(
        cfg,
        source_mode=SOURCE_MANUAL_SANDBOX_CHAT,
        order_id_present=True,
        sandbox_auto_enabled=cfg.manual_sandbox_auto_order_lookup_enabled,
        scenario_auto_eligible=True,
    )
    result = evaluate_tool_eligibility(OperationalToolId.INCHAND_ORDER_LOOKUP, context)
    return result.sandbox_auto_allowed


def manual_sandbox_auto_order_lookup_enabled(settings: AppSettings | None = None) -> bool:
    """Alias for :func:`is_manual_sandbox_auto_order_lookup_enabled`."""
    return is_manual_sandbox_auto_order_lookup_enabled(settings)


def _has_inchand_token(cfg: AppSettings) -> bool:
    from app.tools.inchand.order_lookup import resolve_inchand_api_token

    return bool(resolve_inchand_api_token(cfg))


def inchand_order_lookup_session_key(room_id: str) -> str:
    return f"inchand_order_lookup_result_{room_id}"


def order_lookup_cache_bucket(session_state: MutableMapping[str, Any]) -> dict[str, Any]:
    bucket = session_state.get(SESSION_MANUAL_ORDER_LOOKUP_BY_ORDER_ID)
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[SESSION_MANUAL_ORDER_LOOKUP_BY_ORDER_ID] = bucket
    return bucket


def get_cached_order_lookup_by_id(
    session_state: Mapping[str, Any],
    order_id: str,
) -> dict[str, Any] | None:
    normalized = normalize_inchand_order_id(order_id)
    if not normalized:
        return None
    bucket = session_state.get(SESSION_MANUAL_ORDER_LOOKUP_BY_ORDER_ID)
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(normalized)
    return value if isinstance(value, dict) else None


def store_order_lookup_in_session(
    session_state: MutableMapping[str, Any],
    room_id: str,
    payload: Mapping[str, Any],
    *,
    order_id: str | None = None,
) -> None:
    safe = dict(payload)
    session_state[inchand_order_lookup_session_key(room_id)] = safe
    normalized = normalize_inchand_order_id(order_id or str(payload.get("order_id") or ""))
    if normalized:
        order_lookup_cache_bucket(session_state)[normalized] = safe


def get_order_lookup_from_session(
    session_state: Mapping[str, Any],
    room_id: str,
) -> dict[str, Any] | None:
    stored = session_state.get(inchand_order_lookup_session_key(room_id))
    return stored if isinstance(stored, dict) else None


def is_auto_order_lookup_eligible_scenario(
    scenario: str | None,
    *,
    seller_text: str,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    ticket_label: str | None = None,
) -> bool:
    """True when Inchand auto lookup may run for this seller turn."""
    normalized_scenario = (scenario or "").strip()
    if normalized_scenario in _AUTO_LOOKUP_SCENARIOS:
        if normalized_scenario == "seller_notification":
            return is_shipment_seller_message(seller_text) or is_delivery_completed_seller_message(
                seller_text,
            )
        return True
    if (ticket_label or "").strip().lower() == "shipment":
        return True
    intent = (detected_intent or "").strip().lower()
    if intent in _SHIPMENT_TRACKING_INTENTS and is_shipment_seller_message(seller_text):
        return True
    if intent in _DELIVERY_TRACKING_INTENTS and (
        is_delivery_completed_seller_message(seller_text) or is_shipment_seller_message(seller_text)
    ):
        return True
    if is_delivery_completed_seller_message(seller_text):
        return True
    if is_shipment_seller_message(seller_text):
        return True
    action = (suggested_action or "").strip().lower()
    if action in {"record_update", "update_delivery_status", "check_order_status"}:
        if is_shipment_seller_message(seller_text) or is_delivery_completed_seller_message(
            seller_text,
        ):
            return True
    return False


def should_trigger_manual_sandbox_auto_order_lookup(
    *,
    source_mode: str,
    order_id: str | None,
    seller_text: str,
    detected_scenario: str | None,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    ticket_label: str | None = None,
    settings: AppSettings | None = None,
) -> bool:
    cfg = settings or get_settings()
    normalized_order = normalize_inchand_order_id(order_id or "")
    if not normalized_order or not looks_like_inchand_order_id(normalized_order):
        return False
    scenario_ok = is_auto_order_lookup_eligible_scenario(
        detected_scenario,
        seller_text=seller_text,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        ticket_label=ticket_label,
    )
    context = build_inchand_eligibility_context(
        cfg,
        source_mode=source_mode,
        order_id_present=True,
        sandbox_auto_enabled=cfg.manual_sandbox_auto_order_lookup_enabled,
        detected_scenario=detected_scenario,
        scenario_auto_eligible=scenario_ok,
    )
    result = evaluate_tool_eligibility(OperationalToolId.INCHAND_ORDER_LOOKUP, context)
    return result.sandbox_auto_allowed


def try_manual_sandbox_auto_order_lookup(
    *,
    order_id: str,
    room_id: str,
    seller_message_id: str,
    session_state: MutableMapping[str, Any],
    settings: AppSettings | None = None,
    source_mode: str = SOURCE_MANUAL_SANDBOX_CHAT,
    seller_text: str = "",
    detected_scenario: str | None = None,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    ticket_label: str | None = None,
    force_refresh: bool = False,
) -> ManualOrderLookupOutcome:
    """Read-only Inchand lookup for manual sandbox (cache by order id; no raw payload stored)."""
    cfg = settings or get_settings()
    if not should_trigger_manual_sandbox_auto_order_lookup(
        source_mode=source_mode,
        order_id=order_id,
        seller_text=seller_text,
        detected_scenario=detected_scenario,
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        ticket_label=ticket_label,
        settings=cfg,
    ):
        return ManualOrderLookupOutcome()

    normalized_order = normalize_inchand_order_id(order_id)
    if not normalized_order:
        return ManualOrderLookupOutcome()

    if not force_refresh:
        cached = get_cached_order_lookup_by_id(session_state, normalized_order)
        if cached is not None:
            store_order_lookup_in_session(
                session_state,
                room_id,
                cached,
                order_id=normalized_order,
            )
            session_state[SESSION_MANUAL_LAST_ORDER_LOOKUP_MESSAGE_ID] = seller_message_id
            return ManualOrderLookupOutcome(
                payload=cached,
                cache_hit=True,
                auto_triggered=True,
                api_called=False,
            )

    result = lookup_inchand_order(normalized_order, settings=cfg)
    payload = result.to_safe_dict()
    store_order_lookup_in_session(
        session_state,
        room_id,
        payload,
        order_id=normalized_order,
    )
    session_state[SESSION_MANUAL_LAST_ORDER_LOOKUP_MESSAGE_ID] = seller_message_id
    return ManualOrderLookupOutcome(
        payload=payload,
        cache_hit=False,
        auto_triggered=True,
        api_called=True,
    )


def store_orchestration_meta(
    session_state: MutableMapping[str, Any],
    *,
    order_lookup_auto_triggered: bool = False,
    order_lookup_result_source: str = "none",
    order_lookup_cache_hit: bool = False,
    decision_used_order_lookup_result: bool = False,
    iran_post_auto_attempted: bool = False,
    reply_origin: str | None = None,
    decision_type: str | None = None,
    tools_debug: Mapping[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "order_lookup_auto_triggered": order_lookup_auto_triggered,
        "order_lookup_result_source": order_lookup_result_source,
        "order_lookup_cache_hit": order_lookup_cache_hit,
        "decision_used_order_lookup_result": decision_used_order_lookup_result,
        "iran_post_auto_attempted": iran_post_auto_attempted,
        "reply_origin": reply_origin,
        "decision_type": decision_type,
    }
    if tools_debug:
        payload.update(
            {
                "eligible_tools": list(tools_debug.get("eligible_tools") or []),
                "blocked_tools": list(tools_debug.get("blocked_tools") or []),
                "blocked_reason": dict(tools_debug.get("blocked_reason") or {}),
                "tool_execution_mode": dict(tools_debug.get("tool_execution_mode") or {}),
                "tool_risk_level": dict(tools_debug.get("tool_risk_level") or {}),
            },
        )
    session_state[SESSION_MANUAL_ORCHESTRATION_META] = payload


def get_orchestration_meta(session_state: Mapping[str, Any]) -> dict[str, Any]:
    raw = session_state.get(SESSION_MANUAL_ORCHESTRATION_META)
    return dict(raw) if isinstance(raw, dict) else {}


def decision_bucket(session_state: MutableMapping[str, Any]) -> dict[str, Any]:
    bucket = session_state.get(SESSION_MANUAL_SHIPMENT_DECISION_BY_MESSAGE_ID)
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[SESSION_MANUAL_SHIPMENT_DECISION_BY_MESSAGE_ID] = bucket
    return bucket


def get_decision_for_message(
    session_state: Mapping[str, Any],
    seller_message_id: str,
) -> dict[str, Any] | None:
    bucket = session_state.get(SESSION_MANUAL_SHIPMENT_DECISION_BY_MESSAGE_ID)
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(seller_message_id)
    return value if isinstance(value, dict) else None


def store_decision_for_message(
    session_state: MutableMapping[str, Any],
    seller_message_id: str,
    decision: ShipmentDeliveryDecision,
) -> dict[str, Any]:
    payload = decision.to_safe_dict()
    assert_safe_shipment_decision_payload(payload)
    decision_bucket(session_state)[seller_message_id] = payload
    return payload


def derive_optional_postal_tracking_context(
    messages: Sequence[ManualChatMessage],
    *,
    seller_message_id: str,
) -> tuple[bool, bool]:
    """Return (prior_optional_asked, seller_replied_after_optional_ask)."""
    ask_index: int | None = None
    seller_index: int | None = None
    for index, message in enumerate(messages):
        if message.message_id == seller_message_id and message.sender_type == "seller":
            seller_index = index
        if message.sender_type != "support_agent":
            continue
        if is_optional_postal_tracking_request_text(message.text):
            ask_index = index
    prior_asked = ask_index is not None
    seller_replied_after = (
        prior_asked
        and ask_index is not None
        and seller_index is not None
        and seller_index > ask_index
    )
    return prior_asked, seller_replied_after


def build_shipment_decision_input(
    package: AgenticAssistedPackage,
    *,
    seller_text: str,
    source_mode: str,
    order_lookup_result: Mapping[str, Any] | None,
    order_lookup_attempted: bool,
    iran_post_tracking_result: Mapping[str, Any] | None,
    tool_execution_mode: str,
    ticket_label: str | None = None,
    messages: Sequence[ManualChatMessage] | None = None,
    seller_message_id: str | None = None,
) -> ShipmentDeliveryDecisionInput:
    graph = package.graph
    order_id = (graph.inchand_order_id_candidate or graph.extracted_order_ids or "").strip()
    if order_id and "," in order_id:
        order_id = order_id.split(",")[0].strip()
    prior_optional_asked = False
    seller_replied_after_optional = False
    if messages and seller_message_id:
        (
            prior_optional_asked,
            seller_replied_after_optional,
        ) = derive_optional_postal_tracking_context(
            messages,
            seller_message_id=seller_message_id,
        )
    return ShipmentDeliveryDecisionInput(
        seller_text=seller_text,
        detected_scenario=detect_operational_scenario(
            seller_text=seller_text,
            detected_intent=graph.detected_intent,
            suggested_action=graph.suggested_action,
            conceptual_intent_fa=graph.conceptual_intent_fa,
        ),
        order_id=order_id or None,
        order_lookup_result=order_lookup_result,
        order_lookup_attempted=order_lookup_attempted,
        seller_provided_tracking_code=graph.extracted_tracking_code,
        seller_provided_carrier=graph.extracted_tracking_carrier,
        iran_post_tracking_result=iran_post_tracking_result,
        source_mode=source_mode,
        tool_execution_mode=tool_execution_mode,
        ticket_label=ticket_label,
        prior_optional_postal_tracking_request_asked=prior_optional_asked,
        seller_replied_after_optional_postal_tracking_request=seller_replied_after_optional,
    )


def should_compute_shipment_delivery_decision(
    decision_input: ShipmentDeliveryDecisionInput,
    *,
    settings: AppSettings | None = None,
) -> bool:
    """Limit decision work to shipment/delivery tickets or when order lookup exists."""
    if not shipment_delivery_decision_enabled(settings):
        return False
    if is_shipment_or_delivery_case(decision_input):
        return True
    return bool(decision_input.order_lookup_attempted and decision_input.order_lookup_result)


def _tools_debug_from_results(
    *results: OperationalToolEligibilityResult,
) -> dict[str, Any]:
    eligible_tools: list[str] = []
    blocked_tools: list[str] = []
    blocked_reason: dict[str, str] = {}
    tool_execution_mode: dict[str, str | None] = {}
    tool_risk_level: dict[str, str | None] = {}
    for result in results:
        key = result.tool_id.value
        tool_risk_level[key] = result.tool_risk_level.value if result.tool_risk_level else None
        tool_execution_mode[key] = (
            result.tool_execution_mode.value if result.tool_execution_mode else None
        )
        if result.eligible:
            eligible_tools.append(key)
        else:
            blocked_tools.append(key)
            if result.blocked_reason:
                blocked_reason[key] = result.blocked_reason
    return {
        "eligible_tools": eligible_tools,
        "blocked_tools": blocked_tools,
        "blocked_reason": blocked_reason,
        "tool_execution_mode": tool_execution_mode,
        "tool_risk_level": tool_risk_level,
    }


def should_use_decision_chat_reply(decision: ShipmentDeliveryDecision) -> bool:
    if decision.decision_type == ShipmentDeliveryDecisionType.NOT_SHIPMENT_OR_DELIVERY_CASE:
        return False
    if not decision.should_override_draft:
        return False
    return bool((decision.recommended_reply_fa or "").strip())


def try_manual_sandbox_shipment_decision(
    package: AgenticAssistedPackage,
    *,
    seller_text: str,
    seller_message_id: str,
    room_id: str,
    session_state: MutableMapping[str, Any],
    source_mode: str,
    settings: AppSettings | None = None,
    ticket_label: str | None = None,
    messages: Sequence[ManualChatMessage] | None = None,
) -> ManualShipmentDecisionOutcome:
    cfg = settings or get_settings()
    if not shipment_delivery_decision_enabled(cfg):
        return ManualShipmentDecisionOutcome()

    graph = package.graph
    lookup_cache_hit = False
    lookup_auto_triggered = False
    order_lookup_result_source = "none"

    if source_mode != SOURCE_MANUAL_SANDBOX_CHAT:
        order_lookup = get_order_lookup_from_session(session_state, room_id)
        order_attempted = order_lookup is not None
        if order_attempted:
            order_lookup_result_source = "session_cache"
        tool_mode = "disabled"
    else:
        order_lookup = get_order_lookup_from_session(session_state, room_id)
        order_attempted = order_lookup is not None
        if order_attempted:
            order_lookup_result_source = "manual_button"
        detected_scenario = detect_operational_scenario(
            seller_text=seller_text,
            detected_intent=graph.detected_intent,
            suggested_action=graph.suggested_action,
            conceptual_intent_fa=graph.conceptual_intent_fa,
        )
        candidate = (graph.inchand_order_id_candidate or "").strip()
        if not candidate and graph.extracted_order_ids:
            candidate = graph.extracted_order_ids.split(",")[0].strip()
        if candidate and is_manual_sandbox_auto_order_lookup_enabled(cfg):
            lookup_outcome = try_manual_sandbox_auto_order_lookup(
                order_id=candidate,
                room_id=room_id,
                seller_message_id=seller_message_id,
                session_state=session_state,
                settings=cfg,
                source_mode=source_mode,
                seller_text=seller_text,
                detected_scenario=detected_scenario,
                detected_intent=graph.detected_intent,
                suggested_action=graph.suggested_action,
                ticket_label=ticket_label,
            )
            if lookup_outcome.payload is not None:
                order_lookup = lookup_outcome.payload
                order_attempted = True
                lookup_cache_hit = lookup_outcome.cache_hit
                lookup_auto_triggered = lookup_outcome.auto_triggered
                order_lookup_result_source = (
                    "session_cache" if lookup_outcome.cache_hit else "manual_button"
                )
        lookup_eligibility = evaluate_tool_eligibility(
            OperationalToolId.INCHAND_ORDER_LOOKUP,
            build_inchand_eligibility_context(
                cfg,
                source_mode=source_mode,
                order_id_present=bool(candidate),
                sandbox_auto_enabled=cfg.manual_sandbox_auto_order_lookup_enabled,
                detected_scenario=detected_scenario,
                scenario_auto_eligible=is_auto_order_lookup_eligible_scenario(
                    detected_scenario,
                    seller_text=seller_text,
                    detected_intent=graph.detected_intent,
                    suggested_action=graph.suggested_action,
                    ticket_label=ticket_label,
                ),
            ),
        )
        tool_mode = "sandbox_auto" if lookup_eligibility.sandbox_auto_allowed else "manual"

    iran_post = get_tracking_result_for_message(session_state, seller_message_id)
    iran_post_auto = bool(
        source_mode == SOURCE_MANUAL_SANDBOX_CHAT
        and manual_sandbox_auto_tracking_verify_enabled(cfg)
        and iran_post is not None,
    )

    decision_input = build_shipment_decision_input(
        package,
        seller_text=seller_text,
        source_mode=source_mode,
        order_lookup_result=order_lookup,
        order_lookup_attempted=order_attempted,
        iran_post_tracking_result=iran_post,
        tool_execution_mode=tool_mode,
        ticket_label=ticket_label,
        messages=messages,
        seller_message_id=seller_message_id,
    )
    if not should_compute_shipment_delivery_decision(decision_input, settings=cfg):
        return ManualShipmentDecisionOutcome()

    decision = decide_shipment_delivery(decision_input)
    store_decision_for_message(session_state, seller_message_id, decision)

    chat_reply = None
    reply_origin = None
    if should_use_decision_chat_reply(decision):
        chat_reply = (decision.recommended_reply_fa or "").strip()
        reply_origin = "shipment_delivery_decision"

    order_delivered = bool(
        isinstance(order_lookup, dict) and order_lookup.get("is_delivered_in_inchand"),
    )
    tracking_code = (graph.extracted_tracking_code or "").strip()
    inchand_eval = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            cfg,
            source_mode=source_mode,
            order_id_present=bool(decision_input.order_id),
            manual_trigger=True,
            sandbox_auto_enabled=cfg.manual_sandbox_auto_order_lookup_enabled,
            detected_scenario=decision_input.detected_scenario,
            scenario_auto_eligible=True,
        ),
    )
    iran_eval = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        build_iran_post_eligibility_context(
            cfg,
            source_mode=source_mode,
            tracking_code_present=bool(tracking_code),
            carrier_candidate=graph.extracted_tracking_carrier or "iran_post",
            order_delivered_in_inchand=order_delivered,
            manual_trigger=True,
            sandbox_auto_enabled=cfg.manual_sandbox_auto_tracking_verify_enabled,
        ),
    )
    tools_debug = _tools_debug_from_results(inchand_eval, iran_eval)

    store_orchestration_meta(
        session_state,
        order_lookup_auto_triggered=lookup_auto_triggered,
        order_lookup_result_source=order_lookup_result_source,
        order_lookup_cache_hit=lookup_cache_hit,
        decision_used_order_lookup_result=(
            "inchand_order_lookup" in {source.value for source in decision.data_sources}
        ),
        iran_post_auto_attempted=iran_post_auto,
        reply_origin=reply_origin,
        decision_type=decision.decision_type.value,
        tools_debug=tools_debug,
    )

    return ManualShipmentDecisionOutcome(
        decision=decision,
        chat_reply=chat_reply,
        order_lookup_attempted=order_attempted,
        order_lookup_stored=order_lookup is not None,
        order_lookup_cache_hit=lookup_cache_hit,
        order_lookup_auto_triggered=lookup_auto_triggered,
        order_lookup_result_source=order_lookup_result_source,
        decision_used_order_lookup_result=(
            "inchand_order_lookup" in {source.value for source in decision.data_sources}
        ),
        iran_post_auto_attempted=iran_post_auto,
        reply_origin=reply_origin,
    )


def append_shipment_decision_ai_reply(
    messages: list[ManualChatMessage],
    reply_text: str,
    *,
    message_id: str | None = None,
    created_at: str | None = None,
) -> ManualChatMessage:
    cleaned = reply_text.strip()
    if not cleaned:
        raise ValueError("shipment decision reply must be non-empty")
    message = ManualChatMessage(
        message_id=message_id or f"m{len(messages) + 1}",
        sender_type="support_agent",
        text=cleaned,
        created_at=created_at or utc_now_iso(),
        source=SHIPMENT_DELIVERY_DECISION_SOURCE,
        is_ai_generated=True,
        draft_provider="shipment_delivery_decision",
    )
    messages.append(message)
    return message


def replace_shipment_decision_ai_reply(
    messages: list[ManualChatMessage],
    index: int,
    reply_text: str,
) -> ManualChatMessage:
    cleaned = reply_text.strip()
    if not cleaned:
        raise ValueError("shipment decision reply must be non-empty")
    message = ManualChatMessage(
        message_id=messages[index].message_id,
        sender_type="support_agent",
        text=cleaned,
        created_at=utc_now_iso(),
        source=SHIPMENT_DELIVERY_DECISION_SOURCE,
        is_ai_generated=True,
        draft_provider="shipment_delivery_decision",
    )
    messages[index] = message
    return message


def render_manual_sandbox_shipment_decision_panel(
    streamlit: Any,
    session_state: Mapping[str, Any],
    messages: Sequence[ManualChatMessage],
    *,
    title: str = "تصمیم عملیاتی ارسال/تحویل",
) -> None:
    seller_id = latest_seller_message_id(messages)
    if not seller_id:
        return
    stored = get_decision_for_message(session_state, seller_id)
    orch = get_orchestration_meta(session_state)
    if not isinstance(stored, dict) and not orch:
        return

    streamlit.markdown(f"##### {title}")
    if orch:
        streamlit.markdown("**ارکستراسیون سندباکس**")
        streamlit.markdown(
            f"- **استعلام خودکار سفارش:** "
            f"{'بله' if orch.get('order_lookup_auto_triggered') else 'خیر'}",
        )
        streamlit.markdown(
            f"- **منبع نتیجه استعلام سفارش:** `{orch.get('order_lookup_result_source') or 'none'}`",
        )
        streamlit.markdown(
            f"- **کش استعلام سفارش:** "
            f"{'برخورد' if orch.get('order_lookup_cache_hit') else 'عدم برخورد / —'}",
        )
        streamlit.markdown(
            f"- **تصمیم از نتیجه استعلام سفارش استفاده کرد:** "
            f"{'بله' if orch.get('decision_used_order_lookup_result') else 'خیر'}",
        )
        streamlit.markdown(
            f"- **استعلام خودکار پست:** {'بله' if orch.get('iran_post_auto_attempted') else 'خیر'}",
        )
        if orch.get("reply_origin"):
            streamlit.markdown(f"- **منبع پاسخ:** `{orch['reply_origin']}`")
        if orch.get("decision_type"):
            streamlit.markdown(f"- **نوع تصمیم (آخر):** `{orch['decision_type']}`")
        if orch.get("eligible_tools"):
            streamlit.markdown(f"- **ابزارهای مجاز:** {', '.join(orch['eligible_tools'])}")
        if orch.get("blocked_tools"):
            streamlit.markdown(f"- **ابزارهای مسدود:** {', '.join(orch['blocked_tools'])}")
        blocked_reason = orch.get("blocked_reason")
        if isinstance(blocked_reason, dict) and blocked_reason:
            streamlit.markdown(f"- **دلیل مسدودیت:** `{blocked_reason}`")

    if not isinstance(stored, dict):
        return
    assert_safe_shipment_decision_payload(stored)

    streamlit.markdown(f"- **نوع تصمیم:** `{stored.get('decision_type', '—')}`")
    if stored.get("reasons"):
        streamlit.markdown(f"- **دلایل:** {', '.join(stored['reasons'])}")
    if stored.get("order_id"):
        streamlit.markdown(f"- **شماره سفارش:** `{stored['order_id']}`")
    streamlit.markdown(
        f"- **تحویل در اینچند:** {'بله' if stored.get('order_delivered_in_inchand') else 'خیر'}",
    )
    if stored.get("order_tracking_code"):
        streamlit.markdown(f"- **کد رهگیری مرسوله:** `{stored['order_tracking_code']}`")
    if stored.get("carrier"):
        streamlit.markdown(f"- **شرکت حمل:** {stored['carrier']}")
    if stored.get("carrier_candidate"):
        streamlit.markdown(f"- **شرکت حمل (احتمالی):** {stored['carrier_candidate']}")
    streamlit.markdown(
        f"- **استعلام پست ایران:** {'بله' if stored.get('iran_post_verification_used') else 'خیر'}",
    )
    streamlit.markdown(
        f"- **رد استعلام پست:** {'بله' if stored.get('skip_iran_post_verification') else 'خیر'}",
    )
    if stored.get("tracking_verification_status"):
        streamlit.markdown(f"- **وضعیت رهگیری:** {stored['tracking_verification_status']}")
    if stored.get("recommended_reply_fa"):
        streamlit.info(stored["recommended_reply_fa"])
