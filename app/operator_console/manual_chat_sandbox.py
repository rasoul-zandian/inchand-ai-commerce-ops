"""Manual sandbox chat room for operator console (session-only; no live API writes)."""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.config import AppSettings, get_settings
from app.operator_console.agentic_assisted_mode import (
    AgenticAssistedPackage,
    build_agentic_assisted_package,
)
from app.operator_console.assisted_ticket_input_builder import (
    build_assisted_graph_input_from_operator_ticket,
    build_conversation_snapshot_from_manual_messages,
    build_operator_ticket_from_manual_chat,
    build_operator_ticket_from_open_snapshot,
)
from app.operator_console.console_models import OperatorTicket
from app.operator_console.manual_chat_models import (
    AI_ASSISTED_DRAFT_SOURCE,
    ManualChatMessage,
    utc_now_iso,
)
from app.operator_console.manual_sandbox_auto_tracking import (
    VerifyTrackingFn,
    append_tracking_verification_ai_reply,
    clear_manual_tracking_session,
    replace_tracking_verification_ai_reply,
    try_manual_sandbox_auto_tracking_verify,
)
from app.operator_console.manual_sandbox_shipment_decision import (
    append_shipment_decision_ai_reply,
    get_order_lookup_from_session,
    replace_shipment_decision_ai_reply,
    store_orchestration_meta,
    try_manual_sandbox_shipment_decision,
)
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot
from app.workflows.multi_turn_ticket_context import latest_meaningful_sender

SOURCE_MANUAL_SANDBOX_CHAT = "manual_sandbox_chat"
SESSION_MANUAL_CHAT_MESSAGES = "manual_sandbox_chat_messages"
SESSION_MANUAL_TICKET_LABEL = "manual_sandbox_ticket_label"
SESSION_MANUAL_ROOM_ID = "manual_sandbox_room_id"
SESSION_MANUAL_SHOP_ID = "manual_sandbox_shop_id"
SESSION_MANUAL_ASSISTED_PACKAGES = "manual_sandbox_assisted_packages"
SESSION_MANUAL_LAST_AUTO_RUN_MESSAGE_ID = "manual_sandbox_last_auto_run_message_id"
SESSION_MANUAL_LAST_AI_REPLY_FOR_MESSAGE_ID = "manual_sandbox_last_ai_reply_for_message_id"
SESSION_MANUAL_LAST_GENERATION_ERROR = "manual_sandbox_last_generation_error"

TICKET_LABEL_AUTO = "__auto__"
MANUAL_TICKET_LABEL_OPTIONS: tuple[tuple[str, str], ...] = (
    (TICKET_LABEL_AUTO, "auto"),
    ("complaint", "complaint"),
    ("fund", "fund"),
    ("support", "support"),
)

SELLER_BUBBLE_COLOR = "#E8F1FF"
SUPPORT_BUBBLE_COLOR = "#EAF8EA"
AI_REPLY_BUBBLE_BORDER = "2px solid #7cb87c"

_SAMPLE_MESSAGES: tuple[tuple[str, str], ...] = (
    ("support_agent", "لطفاً کد رهگیری را ارسال کنید"),
    ("seller", "051800506400081160839102"),
)

BuildAssistedPackageFn = Callable[..., AgenticAssistedPackage]


@dataclass(frozen=True)
class ManualAutoRunResult:
    """Outcome of auto-run / regenerate for a seller turn."""

    success: bool
    seller_message_id: str | None = None
    ai_message: ManualChatMessage | None = None
    package: AgenticAssistedPackage | None = None
    error: str | None = None
    skipped_duplicate: bool = False
    replaced_existing: bool = False
    tracking_verification_attempted: bool = False
    used_tracking_reply: bool = False
    used_decision_reply: bool = False
    reply_origin: str | None = None


def _utc_now_iso() -> str:
    return utc_now_iso()


def default_manual_room_id() -> str:
    stamp = datetime.now(tz=UTC).strftime("%Y%m%d%H%M%S")
    return f"manual-sandbox-{stamp}"


def resolve_manual_ticket_label(selected: str) -> str | None:
    """Return explicit ticket_label or None for auto/unset."""
    if selected == TICKET_LABEL_AUTO:
        return None
    return selected.strip() or None


def manual_ticket_label_display(
    selected: str,
    snapshot: ConversationTicketSnapshot,
) -> str:
    if snapshot.metadata.get("ticket_label_source") == "manual_unset":
        return "auto"
    return snapshot.ticket_label or selected


def messages_from_session(raw: object) -> list[ManualChatMessage]:
    if not isinstance(raw, list):
        return []
    parsed: list[ManualChatMessage] = []
    for item in raw:
        if isinstance(item, dict):
            parsed.append(ManualChatMessage.from_dict(item))
    return parsed


def save_messages_to_session(
    session_state: MutableMapping[str, Any],
    messages: Sequence[ManualChatMessage],
) -> None:
    session_state[SESSION_MANUAL_CHAT_MESSAGES] = [message.to_dict() for message in messages]


def next_message_id(messages: Sequence[ManualChatMessage]) -> str:
    return f"m{len(messages) + 1}"


def append_manual_chat_message(
    messages: list[ManualChatMessage],
    *,
    sender_type: str,
    text: str,
) -> ManualChatMessage:
    sender = sender_type.strip().lower()
    if sender not in {"seller", "support_agent"}:
        raise ValueError("sender_type must be seller or support_agent")
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("message text must be non-empty")
    message = ManualChatMessage(
        message_id=next_message_id(messages),
        sender_type=sender,
        text=cleaned,
        created_at=_utc_now_iso(),
    )
    messages.append(message)
    return message


def append_ai_support_reply(
    messages: list[ManualChatMessage],
    draft_text: str,
    *,
    draft_provider: str | None,
) -> ManualChatMessage:
    cleaned = draft_text.strip()
    if not cleaned:
        raise ValueError("AI draft text must be non-empty")
    message = ManualChatMessage(
        message_id=next_message_id(messages),
        sender_type="support_agent",
        text=cleaned,
        created_at=_utc_now_iso(),
        source=AI_ASSISTED_DRAFT_SOURCE,
        is_ai_generated=True,
        draft_provider=draft_provider or "mock",
    )
    messages.append(message)
    return message


def replace_ai_support_reply(
    messages: list[ManualChatMessage],
    index: int,
    draft_text: str,
    *,
    draft_provider: str | None,
) -> ManualChatMessage:
    cleaned = draft_text.strip()
    if not cleaned:
        raise ValueError("AI draft text must be non-empty")
    previous = messages[index]
    message = ManualChatMessage(
        message_id=previous.message_id,
        sender_type="support_agent",
        text=cleaned,
        created_at=_utc_now_iso(),
        source=AI_ASSISTED_DRAFT_SOURCE,
        is_ai_generated=True,
        draft_provider=draft_provider or "mock",
    )
    messages[index] = message
    return message


def load_sample_messages() -> list[ManualChatMessage]:
    return [
        ManualChatMessage(
            message_id=f"m{index + 1}",
            sender_type=sender,
            text=text,
            created_at=_utc_now_iso(),
        )
        for index, (sender, text) in enumerate(_SAMPLE_MESSAGES)
    ]


def manual_chat_to_conversation_messages(
    messages: Sequence[ManualChatMessage],
) -> list[ConversationMessage]:
    from app.operator_console.assisted_ticket_input_builder import (
        manual_messages_to_conversation_messages,
    )

    return manual_messages_to_conversation_messages(messages)


def build_manual_chat_snapshot(
    messages: Sequence[ManualChatMessage],
    *,
    room_id: str,
    ticket_label: str | None = None,
    shop_id: str | None = None,
    status: str = "open",
) -> ConversationTicketSnapshot:
    """Build a validated conversation snapshot from manual chat messages."""
    if not messages:
        raise ValueError("manual chat requires at least one message")
    return build_conversation_snapshot_from_manual_messages(
        messages,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
        status=status,
    )


def manual_chat_to_conversation_snapshot(
    messages: Sequence[ManualChatMessage],
    *,
    room_id: str,
    ticket_label: str | None = None,
    shop_id: str | None = None,
    status: str = "open",
) -> ConversationTicketSnapshot:
    """Alias for build_manual_chat_snapshot."""
    return build_manual_chat_snapshot(
        messages,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
        status=status,
    )


def build_manual_operator_ticket(
    snapshot: ConversationTicketSnapshot,
    *,
    shop_id: str | None = None,
    ticket_label: str | None = None,
) -> OperatorTicket:
    """Build HITL-safe operator ticket from a manual chat snapshot."""
    label_source = str(snapshot.metadata.get("ticket_label_source") or "")
    explicit_label = ticket_label
    if explicit_label is None and label_source == "manual_unset":
        explicit_label = None
    elif explicit_label is None and snapshot.ticket_label != "unknown":
        explicit_label = snapshot.ticket_label
    return build_operator_ticket_from_open_snapshot(
        snapshot,
        shop_id=shop_id,
        ticket_label=explicit_label,
        ticket_label_source=label_source,
    )


def manual_chat_latest_sender(messages: Sequence[ManualChatMessage]) -> str | None:
    if not messages:
        return None
    return latest_meaningful_sender(manual_chat_to_conversation_messages(messages))


def manual_chat_should_generate_draft(
    messages: Sequence[ManualChatMessage],
) -> tuple[bool, str | None]:
    """Return whether assisted draft generation should be enabled."""
    if not messages:
        return False, "no_seller_message"
    latest = manual_chat_latest_sender(messages)
    if latest is None:
        return False, "malformed_ticket"
    if latest == "seller":
        return True, None
    if latest in {"support_agent", "finance_agent"}:
        return False, "latest_message_from_support"
    return False, "malformed_ticket"


def seller_message_already_answered(
    session_state: Mapping[str, Any],
    seller_message_id: str,
) -> bool:
    return (
        str(session_state.get(SESSION_MANUAL_LAST_AI_REPLY_FOR_MESSAGE_ID) or "")
        == seller_message_id
    )


def draft_text_from_assisted_package(package: AgenticAssistedPackage) -> str | None:
    graph = package.graph
    text = (graph.final_reflected_draft or graph.draft_reply or "").strip()
    return text or None


def draft_provider_from_assisted_package(package: AgenticAssistedPackage) -> str:
    graph = package.graph
    if graph.draft_provider:
        return str(graph.draft_provider)
    if graph.draft_is_mock:
        return "mock"
    return "openai"


def clear_manual_auto_run_guards(session_state: MutableMapping[str, Any]) -> None:
    session_state.pop(SESSION_MANUAL_LAST_AUTO_RUN_MESSAGE_ID, None)
    session_state.pop(SESSION_MANUAL_LAST_AI_REPLY_FOR_MESSAGE_ID, None)
    session_state.pop(SESSION_MANUAL_LAST_GENERATION_ERROR, None)
    clear_manual_tracking_session(session_state)


def mark_auto_run_success(
    session_state: MutableMapping[str, Any],
    *,
    seller_message_id: str,
) -> None:
    session_state[SESSION_MANUAL_LAST_AUTO_RUN_MESSAGE_ID] = seller_message_id
    session_state[SESSION_MANUAL_LAST_AI_REPLY_FOR_MESSAGE_ID] = seller_message_id
    session_state.pop(SESSION_MANUAL_LAST_GENERATION_ERROR, None)


def mark_auto_run_failure(
    session_state: MutableMapping[str, Any],
    *,
    seller_message_id: str,
    error: str,
) -> None:
    session_state[SESSION_MANUAL_LAST_AUTO_RUN_MESSAGE_ID] = seller_message_id
    session_state[SESSION_MANUAL_LAST_GENERATION_ERROR] = error


def find_regeneratable_ai_reply_index(messages: Sequence[ManualChatMessage]) -> int | None:
    if len(messages) < 2:
        return None
    last = messages[-1]
    previous = messages[-2]
    if (
        last.is_ai_generated
        and last.sender_type == "support_agent"
        and previous.sender_type == "seller"
    ):
        return len(messages) - 1
    return None


def remove_last_ai_generated_reply(messages: list[ManualChatMessage]) -> bool:
    if not messages or not messages[-1].is_ai_generated:
        return False
    messages.pop()
    return True


def _build_package_for_messages(
    messages: Sequence[ManualChatMessage],
    *,
    room_id: str,
    ticket_label: str | None,
    shop_id: str | None,
    settings: AppSettings,
    build_package_fn: BuildAssistedPackageFn,
) -> AgenticAssistedPackage:
    ticket, display_snapshot = build_operator_ticket_from_manual_chat(
        messages,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
    )
    bundle = build_assisted_graph_input_from_operator_ticket(
        ticket,
        conversation_snapshot=display_snapshot,
        source_mode="manual_sandbox_chat",
        settings=settings,
    )
    return build_package_fn(
        bundle.ticket,
        settings=settings,
        conversation_snapshot=bundle.conversation_snapshot,
        source_mode="manual_sandbox_chat",
    )


def _seller_text_for_message(
    messages: Sequence[ManualChatMessage],
    seller_message_id: str,
) -> str:
    for message in messages:
        if message.message_id == seller_message_id and message.sender_type == "seller":
            return message.text
    return ""


def _complete_seller_turn_with_reply(
    messages: list[ManualChatMessage],
    *,
    seller_message_id: str,
    room_id: str,
    ticket_label: str | None,
    shop_id: str | None,
    session_state: MutableMapping[str, Any],
    settings: AppSettings,
    build_package_fn: BuildAssistedPackageFn,
    replace_index: int | None = None,
    force_refresh_tracking: bool = False,
    verify_tracking_fn: VerifyTrackingFn | None = None,
) -> ManualAutoRunResult:
    """Build assisted package, optionally auto-verify tracking, append one AI bubble."""
    seller_text = _seller_text_for_message(messages, seller_message_id)

    try:
        package = _build_package_for_messages(
            messages if replace_index is None else messages[:replace_index],
            room_id=room_id,
            ticket_label=ticket_label,
            shop_id=shop_id,
            settings=settings,
            build_package_fn=build_package_fn,
        )
    except (ValueError, OSError, RuntimeError) as exc:
        mark_auto_run_failure(session_state, seller_message_id=seller_message_id, error=str(exc))
        return ManualAutoRunResult(
            success=False,
            seller_message_id=seller_message_id,
            error=str(exc),
        )

    store_manual_sandbox_assisted_package(session_state, package)

    if settings.agentic_graph_read_only_tools_enabled and bool(
        getattr(package.graph, "graph_tools_enabled", False)
    ):
        graph_draft = draft_text_from_assisted_package(package)
        if graph_draft:
            provider = draft_provider_from_assisted_package(package)
            if replace_index is not None:
                ai_message = replace_ai_support_reply(
                    messages,
                    replace_index,
                    graph_draft,
                    draft_provider=provider,
                )
            else:
                ai_message = append_ai_support_reply(
                    messages,
                    graph_draft,
                    draft_provider=provider,
                )
            store_orchestration_meta(
                session_state,
                order_lookup_auto_triggered=bool(
                    getattr(package.graph, "order_lookup_auto_triggered", False),
                ),
                order_lookup_result_source=str(
                    getattr(package.graph, "order_lookup_result_source", "none") or "none",
                ),
                decision_used_order_lookup_result=bool(
                    getattr(package.graph, "decision_used_order_lookup_result", False),
                ),
                reply_origin="graph_read_only_tools",
                decision_type=getattr(package.graph, "shipment_delivery_decision_type", None),
                tools_debug={
                    "eligible_tools": list(getattr(package.graph, "graph_tools_planned", ()) or ()),
                    "blocked_tools": list(getattr(package.graph, "graph_tools_blocked", ()) or ()),
                    "blocked_reason": dict(
                        getattr(package.graph, "graph_tools_blocked_reasons", {}) or {},
                    ),
                    "tool_execution_mode": {
                        "graph": "sandbox_auto"
                        if package.graph.graph_tools_enabled
                        else "disabled",
                    },
                    "tool_risk_level": {},
                },
            )
            mark_auto_run_success(session_state, seller_message_id=seller_message_id)
            return ManualAutoRunResult(
                success=True,
                seller_message_id=seller_message_id,
                ai_message=ai_message,
                package=package,
                replaced_existing=replace_index is not None,
                reply_origin="graph_read_only_tools",
                used_decision_reply=bool(getattr(package.graph, "tool_grounded_reply_used", False)),
            )

    decision_outcome = try_manual_sandbox_shipment_decision(
        package,
        seller_text=seller_text,
        seller_message_id=seller_message_id,
        room_id=room_id,
        session_state=session_state,
        source_mode=SOURCE_MANUAL_SANDBOX_CHAT,
        settings=settings,
        ticket_label=ticket_label,
        messages=messages,
    )
    if decision_outcome.chat_reply and (
        decision_outcome.decision is not None
        and decision_outcome.decision.skip_iran_post_verification
    ):
        if replace_index is not None:
            ai_message = replace_shipment_decision_ai_reply(
                messages,
                replace_index,
                decision_outcome.chat_reply,
            )
        else:
            ai_message = append_shipment_decision_ai_reply(
                messages,
                decision_outcome.chat_reply,
                message_id=next_message_id(messages),
            )
        mark_auto_run_success(session_state, seller_message_id=seller_message_id)
        return ManualAutoRunResult(
            success=True,
            seller_message_id=seller_message_id,
            ai_message=ai_message,
            package=package,
            replaced_existing=replace_index is not None,
            used_decision_reply=True,
            reply_origin=decision_outcome.reply_origin or "shipment_delivery_decision",
        )

    skip_tracking = bool(
        decision_outcome.decision is not None
        and decision_outcome.decision.skip_iran_post_verification,
    )
    tracking_outcome = None
    if not skip_tracking:
        order_lookup = get_order_lookup_from_session(session_state, room_id)
        order_delivered = bool(
            isinstance(order_lookup, dict) and order_lookup.get("is_delivered_in_inchand"),
        )
        tracking_outcome = try_manual_sandbox_auto_tracking_verify(
            seller_text,
            seller_message_id=seller_message_id,
            session_state=session_state,
            settings=settings,
            verify_fn=verify_tracking_fn,
            force_refresh=force_refresh_tracking,
            order_delivered_in_inchand=order_delivered,
        )

    if (
        tracking_outcome is not None
        and tracking_outcome.attempted
        and tracking_outcome.chat_reply
        and tracking_outcome.tracking_code
    ):
        if tracking_outcome.skipped_duplicate and seller_message_already_answered(
            session_state,
            seller_message_id,
        ):
            return ManualAutoRunResult(
                success=True,
                seller_message_id=seller_message_id,
                package=package,
                skipped_duplicate=True,
                tracking_verification_attempted=True,
                used_tracking_reply=True,
            )

        decision_after_tracking = try_manual_sandbox_shipment_decision(
            package,
            seller_text=seller_text,
            seller_message_id=seller_message_id,
            room_id=room_id,
            session_state=session_state,
            source_mode=SOURCE_MANUAL_SANDBOX_CHAT,
            settings=settings,
            ticket_label=ticket_label,
            messages=messages,
        )
        if decision_after_tracking.chat_reply:
            if replace_index is not None:
                ai_message = replace_shipment_decision_ai_reply(
                    messages,
                    replace_index,
                    decision_after_tracking.chat_reply,
                )
            else:
                ai_message = append_shipment_decision_ai_reply(
                    messages,
                    decision_after_tracking.chat_reply,
                    message_id=next_message_id(messages),
                )
            mark_auto_run_success(session_state, seller_message_id=seller_message_id)
            return ManualAutoRunResult(
                success=True,
                seller_message_id=seller_message_id,
                ai_message=ai_message,
                package=package,
                skipped_duplicate=tracking_outcome.skipped_duplicate,
                replaced_existing=replace_index is not None,
                tracking_verification_attempted=True,
                used_decision_reply=True,
                reply_origin=decision_after_tracking.reply_origin or "shipment_delivery_decision",
            )

        reply = tracking_outcome.chat_reply
        store_orchestration_meta(
            session_state,
            order_lookup_auto_triggered=decision_outcome.order_lookup_auto_triggered,
            order_lookup_result_source=decision_outcome.order_lookup_result_source,
            order_lookup_cache_hit=decision_outcome.order_lookup_cache_hit,
            decision_used_order_lookup_result=decision_outcome.decision_used_order_lookup_result,
            iran_post_auto_attempted=True,
            reply_origin="iran_post_tracking",
            decision_type=(
                decision_outcome.decision.decision_type.value
                if decision_outcome.decision is not None
                else None
            ),
        )
        verified = bool(
            tracking_outcome.result.verified
            if tracking_outcome.result is not None
            else tracking_outcome.safe_result and tracking_outcome.safe_result.get("verified"),
        )
        if replace_index is not None:
            ai_message = replace_tracking_verification_ai_reply(
                messages,
                replace_index,
                reply,
                tracking_code=tracking_outcome.tracking_code,
                tracking_verified=verified,
                created_at=_utc_now_iso(),
            )
        else:
            ai_message = append_tracking_verification_ai_reply(
                messages,
                reply,
                tracking_code=tracking_outcome.tracking_code,
                tracking_verified=verified,
                message_id=next_message_id(messages),
                created_at=_utc_now_iso(),
            )
        mark_auto_run_success(session_state, seller_message_id=seller_message_id)
        return ManualAutoRunResult(
            success=True,
            seller_message_id=seller_message_id,
            ai_message=ai_message,
            package=package,
            skipped_duplicate=tracking_outcome.skipped_duplicate,
            replaced_existing=replace_index is not None,
            tracking_verification_attempted=True,
            used_tracking_reply=True,
            reply_origin="iran_post_tracking",
        )

    if decision_outcome.chat_reply:
        if replace_index is not None:
            ai_message = replace_shipment_decision_ai_reply(
                messages,
                replace_index,
                decision_outcome.chat_reply,
            )
        else:
            ai_message = append_shipment_decision_ai_reply(
                messages,
                decision_outcome.chat_reply,
                message_id=next_message_id(messages),
            )
        mark_auto_run_success(session_state, seller_message_id=seller_message_id)
        return ManualAutoRunResult(
            success=True,
            seller_message_id=seller_message_id,
            ai_message=ai_message,
            package=package,
            replaced_existing=replace_index is not None,
            used_decision_reply=True,
            reply_origin=decision_outcome.reply_origin or "shipment_delivery_decision",
        )

    draft = draft_text_from_assisted_package(package)
    if not draft:
        error = "assisted package produced no draft text"
        mark_auto_run_failure(session_state, seller_message_id=seller_message_id, error=error)
        return ManualAutoRunResult(
            success=False,
            seller_message_id=seller_message_id,
            package=package,
            error=error,
        )

    provider = draft_provider_from_assisted_package(package)
    store_orchestration_meta(
        session_state,
        order_lookup_auto_triggered=decision_outcome.order_lookup_auto_triggered,
        order_lookup_result_source=decision_outcome.order_lookup_result_source,
        order_lookup_cache_hit=decision_outcome.order_lookup_cache_hit,
        decision_used_order_lookup_result=decision_outcome.decision_used_order_lookup_result,
        iran_post_auto_attempted=decision_outcome.iran_post_auto_attempted,
        reply_origin=provider or "generic_assisted_draft",
        decision_type=(
            decision_outcome.decision.decision_type.value
            if decision_outcome.decision is not None
            else None
        ),
    )
    if replace_index is not None:
        ai_message = replace_ai_support_reply(
            messages,
            replace_index,
            draft,
            draft_provider=provider,
        )
    else:
        ai_message = append_ai_support_reply(messages, draft, draft_provider=provider)

    mark_auto_run_success(session_state, seller_message_id=seller_message_id)
    return ManualAutoRunResult(
        success=True,
        seller_message_id=seller_message_id,
        ai_message=ai_message,
        package=package,
        replaced_existing=replace_index is not None,
    )


def run_manual_assisted_auto_reply(
    messages: list[ManualChatMessage],
    *,
    seller_message_id: str,
    room_id: str,
    ticket_label: str | None,
    shop_id: str | None,
    session_state: MutableMapping[str, Any],
    settings: AppSettings | None = None,
    build_package_fn: BuildAssistedPackageFn | None = None,
    verify_tracking_fn: VerifyTrackingFn | None = None,
) -> ManualAutoRunResult:
    """Generate assisted package for latest seller turn and append AI support reply."""
    if seller_message_already_answered(session_state, seller_message_id):
        return ManualAutoRunResult(
            success=True,
            seller_message_id=seller_message_id,
            skipped_duplicate=True,
        )

    last_auto = str(session_state.get(SESSION_MANUAL_LAST_AUTO_RUN_MESSAGE_ID) or "")
    if last_auto == seller_message_id:
        return ManualAutoRunResult(
            success=True,
            seller_message_id=seller_message_id,
            skipped_duplicate=True,
        )

    cfg = settings or get_settings()
    builder = build_package_fn or build_agentic_assisted_package
    return _complete_seller_turn_with_reply(
        messages,
        seller_message_id=seller_message_id,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
        session_state=session_state,
        settings=cfg,
        build_package_fn=builder,
        verify_tracking_fn=verify_tracking_fn,
    )


def regenerate_latest_ai_reply(
    messages: list[ManualChatMessage],
    *,
    room_id: str,
    ticket_label: str | None,
    shop_id: str | None,
    session_state: MutableMapping[str, Any],
    settings: AppSettings | None = None,
    build_package_fn: BuildAssistedPackageFn | None = None,
    verify_tracking_fn: VerifyTrackingFn | None = None,
) -> ManualAutoRunResult:
    """Regenerate AI reply for the latest seller turn (replace trailing AI bubble if present)."""
    if not messages:
        return ManualAutoRunResult(success=False, error="no messages")

    regen_index = find_regeneratable_ai_reply_index(messages)
    if regen_index is not None:
        seller_message_id = messages[regen_index - 1].message_id
        replace_mode = True
    elif messages[-1].sender_type == "seller":
        seller_message_id = messages[-1].message_id
        replace_mode = False
        if seller_message_already_answered(session_state, seller_message_id):
            return ManualAutoRunResult(
                success=True,
                seller_message_id=seller_message_id,
                skipped_duplicate=True,
            )
    else:
        return ManualAutoRunResult(success=False, error="no seller turn to regenerate for")

    cfg = settings or get_settings()
    builder = build_package_fn or build_agentic_assisted_package

    return _complete_seller_turn_with_reply(
        messages,
        seller_message_id=seller_message_id,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
        session_state=session_state,
        settings=cfg,
        build_package_fn=builder,
        replace_index=regen_index if replace_mode else None,
        # Reuse cached verification result (no re-verify) unless the operator
        # explicitly refreshes via the tracking panel.
        force_refresh_tracking=False,
        verify_tracking_fn=verify_tracking_fn,
    )


def handle_manual_add_message(
    session_state: MutableMapping[str, Any],
    *,
    role: str,
    text: str,
    room_id: str,
    ticket_label: str | None,
    shop_id: str | None,
    settings: AppSettings | None = None,
    build_package_fn: BuildAssistedPackageFn | None = None,
    verify_tracking_fn: VerifyTrackingFn | None = None,
) -> ManualAutoRunResult | None:
    """Append a manual message; auto-run assisted package when role is seller."""
    messages = messages_from_session(session_state.get(SESSION_MANUAL_CHAT_MESSAGES))
    session_state.pop(SESSION_MANUAL_LAST_GENERATION_ERROR, None)
    try:
        new_message = append_manual_chat_message(messages, sender_type=role, text=text)
    except ValueError as exc:
        return ManualAutoRunResult(success=False, error=str(exc))

    save_messages_to_session(session_state, messages)

    if role != "seller":
        return None

    result = run_manual_assisted_auto_reply(
        messages,
        seller_message_id=new_message.message_id,
        room_id=room_id,
        ticket_label=ticket_label,
        shop_id=shop_id,
        session_state=session_state,
        settings=settings,
        build_package_fn=build_package_fn,
        verify_tracking_fn=verify_tracking_fn,
    )
    if result.ai_message is not None:
        save_messages_to_session(session_state, messages)
    return result


def format_message_time_hhmm(created_at_iso: str) -> str:
    try:
        parsed = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
        return parsed.astimezone(UTC).strftime("%H:%M")
    except ValueError:
        return "--:--"


def render_manual_chat_bubble(
    message: ManualChatMessage,
    *,
    ai_reply_label: str = "AI suggested reply",
) -> str:
    """HTML bubble for chat display (escaped text; RTL for body)."""
    is_seller = message.sender_type == "seller"
    bg = SELLER_BUBBLE_COLOR if is_seller else SUPPORT_BUBBLE_COLOR
    border = "1px solid rgba(0,0,0,0.06)"
    if message.is_ai_generated:
        role_label = ai_reply_label
        border = AI_REPLY_BUBBLE_BORDER
    elif is_seller:
        role_label = "فروشنده"
    else:
        role_label = "پشتیبانی"
    time_label = format_message_time_hhmm(message.created_at)
    escaped = html.escape(message.text, quote=False)
    return (
        f'<div style="margin:0.4rem 0;display:flex;justify-content:'
        f'{"flex-end" if is_seller else "flex-start"};">'
        f'<div style="max-width:85%;background:{bg};border-radius:0.65rem;'
        f'padding:0.55rem 0.75rem;border:{border};">'
        f'<div dir="ltr" style="font-size:0.75rem;color:#555;margin-bottom:0.2rem;">'
        f"{html.escape(role_label)} · {time_label}</div>"
        f'<div dir="rtl" style="white-space:pre-wrap;line-height:1.5;">{escaped}</div>'
        f"</div></div>"
    )


def get_manual_sandbox_assisted_package(
    session_state: Mapping[str, Any],
    room_id: str,
) -> AgenticAssistedPackage | None:
    bucket = session_state.get(SESSION_MANUAL_ASSISTED_PACKAGES, {})
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(room_id)
    if isinstance(value, AgenticAssistedPackage):
        return value
    return None


def store_manual_sandbox_assisted_package(
    session_state: MutableMapping[str, Any],
    package: AgenticAssistedPackage,
) -> None:
    bucket = session_state.setdefault(SESSION_MANUAL_ASSISTED_PACKAGES, {})
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[SESSION_MANUAL_ASSISTED_PACKAGES] = bucket
    bucket[package.room_id] = package


def init_manual_chat_session_defaults(session_state: MutableMapping[str, Any]) -> None:
    if SESSION_MANUAL_CHAT_MESSAGES not in session_state:
        session_state[SESSION_MANUAL_CHAT_MESSAGES] = []
    if SESSION_MANUAL_TICKET_LABEL not in session_state:
        session_state[SESSION_MANUAL_TICKET_LABEL] = TICKET_LABEL_AUTO
    if SESSION_MANUAL_ROOM_ID not in session_state:
        session_state[SESSION_MANUAL_ROOM_ID] = default_manual_room_id()
    if SESSION_MANUAL_SHOP_ID not in session_state:
        session_state[SESSION_MANUAL_SHOP_ID] = ""
