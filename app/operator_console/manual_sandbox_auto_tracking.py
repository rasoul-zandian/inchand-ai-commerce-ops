"""Manual sandbox auto Iran Post tracking verification (session-only; no live/replay)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.config import AppSettings, get_settings
from app.operator_console.manual_chat_models import (
    IRAN_POST_TRACKING_SOURCE,
    ManualChatMessage,
    utc_now_iso,
)
from app.tools.operational_actions_registry import (
    OperationalToolId,
    build_iran_post_eligibility_context,
    evaluate_tool_eligibility,
)
from app.tools.tracking.iran_post_tracking import (
    IranPostTrackingResult,
    TrackingExtractionDiagnostics,
    assert_safe_tracking_result_payload,
    build_tracking_verification_chat_reply,
    resolve_tracking_code_from_text,
    verify_iran_post_tracking_code,
)

SOURCE_MANUAL_SANDBOX_CHAT = "manual_sandbox_chat"

SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_MESSAGE_ID = (
    "manual_sandbox_last_tracking_auto_verify_message_id"
)
SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_CODE = "manual_sandbox_last_tracking_auto_verify_code"
SESSION_MANUAL_TRACKING_RESULTS_BY_MESSAGE_ID = "manual_sandbox_tracking_results_by_message_id"

VerifyTrackingFn = Callable[[str], IranPostTrackingResult]


@dataclass(frozen=True)
class ManualTrackingAutoVerifyOutcome:
    """Result of optional auto tracking verification for one seller turn."""

    attempted: bool = False
    tracking_code: str | None = None
    tracking_candidates: tuple[str, ...] = ()
    extraction_diagnostics: TrackingExtractionDiagnostics | None = None
    result: IranPostTrackingResult | None = None
    safe_result: dict[str, Any] | None = None
    chat_reply: str | None = None
    skipped_duplicate: bool = False
    carrier_candidate: str = "iran_post"


def manual_sandbox_auto_tracking_verify_enabled(settings: AppSettings | None = None) -> bool:
    cfg = settings or get_settings()
    context = build_iran_post_eligibility_context(
        cfg,
        source_mode=SOURCE_MANUAL_SANDBOX_CHAT,
        tracking_code_present=True,
        sandbox_auto_enabled=cfg.manual_sandbox_auto_tracking_verify_enabled,
        order_delivered_in_inchand=False,
    )
    result = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        context,
    )
    return result.sandbox_auto_allowed


def should_run_manual_sandbox_auto_tracking(
    *,
    source_mode: str,
    role: str,
    settings: AppSettings | None = None,
    tracking_code_present: bool = True,
    carrier_candidate: str | None = "iran_post",
    order_delivered_in_inchand: bool = False,
) -> bool:
    if source_mode != SOURCE_MANUAL_SANDBOX_CHAT:
        return False
    if role.strip().lower() != "seller":
        return False
    cfg = settings or get_settings()
    context = build_iran_post_eligibility_context(
        cfg,
        source_mode=source_mode,
        tracking_code_present=tracking_code_present,
        carrier_candidate=carrier_candidate,
        order_delivered_in_inchand=order_delivered_in_inchand,
        sandbox_auto_enabled=cfg.manual_sandbox_auto_tracking_verify_enabled,
    )
    result = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        context,
    )
    return result.sandbox_auto_allowed


def tracking_results_bucket(session_state: MutableMapping[str, Any]) -> dict[str, Any]:
    bucket = session_state.get(SESSION_MANUAL_TRACKING_RESULTS_BY_MESSAGE_ID)
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[SESSION_MANUAL_TRACKING_RESULTS_BY_MESSAGE_ID] = bucket
    return bucket


def get_tracking_result_for_message(
    session_state: Mapping[str, Any],
    seller_message_id: str,
) -> dict[str, Any] | None:
    bucket = session_state.get(SESSION_MANUAL_TRACKING_RESULTS_BY_MESSAGE_ID)
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(seller_message_id)
    return value if isinstance(value, dict) else None


def tracking_verify_already_done(
    session_state: Mapping[str, Any],
    *,
    seller_message_id: str,
    tracking_code: str,
) -> bool:
    if (
        str(session_state.get(SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_MESSAGE_ID) or "")
        == seller_message_id
        and str(session_state.get(SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_CODE) or "")
        == tracking_code
    ):
        return True
    cached = get_tracking_result_for_message(session_state, seller_message_id)
    return isinstance(cached, dict) and cached.get("tracking_code") == tracking_code


def clear_tracking_verify_cache_for_message(
    session_state: MutableMapping[str, Any],
    seller_message_id: str,
) -> None:
    bucket = tracking_results_bucket(session_state)
    bucket.pop(seller_message_id, None)
    if (
        str(session_state.get(SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_MESSAGE_ID) or "")
        == seller_message_id
    ):
        session_state.pop(SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_MESSAGE_ID, None)
        session_state.pop(SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_CODE, None)


def clear_manual_tracking_session(session_state: MutableMapping[str, Any]) -> None:
    session_state.pop(SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_MESSAGE_ID, None)
    session_state.pop(SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_CODE, None)
    session_state.pop(SESSION_MANUAL_TRACKING_RESULTS_BY_MESSAGE_ID, None)


def store_tracking_result_for_message(
    session_state: MutableMapping[str, Any],
    *,
    seller_message_id: str,
    tracking_code: str,
    safe_result: Mapping[str, Any],
    auto_metadata: Mapping[str, Any],
) -> None:
    bucket = tracking_results_bucket(session_state)
    bucket[seller_message_id] = {
        **dict(safe_result),
        "auto_verification_metadata": dict(auto_metadata),
    }
    session_state[SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_MESSAGE_ID] = seller_message_id
    session_state[SESSION_MANUAL_LAST_TRACKING_AUTO_VERIFY_CODE] = tracking_code


def append_tracking_verification_ai_reply(
    messages: list[ManualChatMessage],
    reply_text: str,
    *,
    tracking_code: str,
    tracking_verified: bool,
    message_id: str,
    created_at: str,
) -> ManualChatMessage:
    cleaned = reply_text.strip()
    if not cleaned:
        raise ValueError("tracking verification reply must be non-empty")
    message = ManualChatMessage(
        message_id=message_id,
        sender_type="support_agent",
        text=cleaned,
        created_at=created_at,
        source=IRAN_POST_TRACKING_SOURCE,
        is_ai_generated=True,
        draft_provider="iran_post_tracking",
        tracking_verification_used=True,
        tracking_code=tracking_code,
        tracking_verified=tracking_verified,
    )
    messages.append(message)
    return message


def replace_tracking_verification_ai_reply(
    messages: list[ManualChatMessage],
    index: int,
    reply_text: str,
    *,
    tracking_code: str,
    tracking_verified: bool,
    created_at: str,
) -> ManualChatMessage:
    cleaned = reply_text.strip()
    if not cleaned:
        raise ValueError("tracking verification reply must be non-empty")
    previous = messages[index]
    message = ManualChatMessage(
        message_id=previous.message_id,
        sender_type="support_agent",
        text=cleaned,
        created_at=created_at,
        source=IRAN_POST_TRACKING_SOURCE,
        is_ai_generated=True,
        draft_provider="iran_post_tracking",
        tracking_verification_used=True,
        tracking_code=tracking_code,
        tracking_verified=tracking_verified,
    )
    messages[index] = message
    return message


def try_manual_sandbox_auto_tracking_verify(
    seller_text: str,
    *,
    seller_message_id: str,
    session_state: MutableMapping[str, Any],
    settings: AppSettings | None = None,
    verify_fn: VerifyTrackingFn | None = None,
    force_refresh: bool = False,
    order_delivered_in_inchand: bool = False,
    carrier_candidate: str | None = "iran_post",
) -> ManualTrackingAutoVerifyOutcome:
    """Verify first plausible tracking candidate; session cache prevents duplicate API calls."""
    cfg = settings or get_settings()
    selected_code, diagnostics = resolve_tracking_code_from_text(
        seller_text,
        message_id=seller_message_id,
        sender_type="seller",
        code_field=cfg.iran_post_tracking_code_field,
    )
    if not selected_code:
        return ManualTrackingAutoVerifyOutcome(
            extraction_diagnostics=diagnostics,
        )

    if not should_run_manual_sandbox_auto_tracking(
        source_mode=SOURCE_MANUAL_SANDBOX_CHAT,
        role="seller",
        settings=cfg,
        tracking_code_present=True,
        carrier_candidate=carrier_candidate,
        order_delivered_in_inchand=order_delivered_in_inchand,
    ):
        return ManualTrackingAutoVerifyOutcome(
            extraction_diagnostics=diagnostics,
            tracking_code=selected_code,
        )

    tracking_code = selected_code
    candidates = tuple(diagnostics.normalized_candidates)
    if not force_refresh and tracking_verify_already_done(
        session_state,
        seller_message_id=seller_message_id,
        tracking_code=tracking_code,
    ):
        cached = get_tracking_result_for_message(session_state, seller_message_id)
        if isinstance(cached, dict):
            reply = build_tracking_verification_chat_reply(_result_from_safe_dict(cached))
            return ManualTrackingAutoVerifyOutcome(
                attempted=True,
                tracking_code=tracking_code,
                tracking_candidates=candidates,
                extraction_diagnostics=diagnostics,
                safe_result=cached,
                chat_reply=reply,
                skipped_duplicate=True,
            )
        return ManualTrackingAutoVerifyOutcome(
            attempted=True,
            tracking_code=tracking_code,
            tracking_candidates=candidates,
            extraction_diagnostics=diagnostics,
            skipped_duplicate=True,
        )

    _verify = verify_fn or (
        lambda code: verify_iran_post_tracking_code(
            code,
            settings=cfg,
            extraction_source_message_id=seller_message_id,
            extraction_source_sender_type="seller",
        )
    )
    result = _verify(tracking_code)
    diagnostics = result.extraction_diagnostics or diagnostics
    safe_result = result.to_safe_dict()
    assert_safe_tracking_result_payload(safe_result)
    auto_metadata = {
        "auto_verification_attempted": True,
        "carrier_candidate": "iran_post",
        "verified": result.verified,
        "event_count": result.event_count,
        "error_type": result.error_type,
        "tracking_candidates": list(candidates),
        "selected_candidate_reason": diagnostics.selected_candidate_reason,
        "api_code_field": diagnostics.api_code_field,
        "payload_trace_number": diagnostics.payload_trace_number,
        "payload_package_number": diagnostics.payload_package_number,
        "extraction_diagnostics": diagnostics.to_safe_dict(),
    }
    store_tracking_result_for_message(
        session_state,
        seller_message_id=seller_message_id,
        tracking_code=tracking_code,
        safe_result=safe_result,
        auto_metadata=auto_metadata,
    )
    reply = build_tracking_verification_chat_reply(result)
    return ManualTrackingAutoVerifyOutcome(
        attempted=True,
        tracking_code=tracking_code,
        tracking_candidates=candidates,
        extraction_diagnostics=diagnostics,
        result=result,
        safe_result=safe_result,
        chat_reply=reply,
    )


def _result_from_safe_dict(payload: Mapping[str, Any]) -> IranPostTrackingResult:
    events_raw = payload.get("events")
    events = ()
    if isinstance(events_raw, list):
        from app.tools.tracking.iran_post_tracking import IranPostTrackingEvent

        events = tuple(
            IranPostTrackingEvent(
                datetime=item.get("datetime") if isinstance(item, dict) else None,
                event_number=item.get("event_number") if isinstance(item, dict) else None,
                description=item.get("description") if isinstance(item, dict) else None,
                province=item.get("province") if isinstance(item, dict) else None,
            )
            for item in events_raw
            if isinstance(item, dict)
        )
    return IranPostTrackingResult(
        tracking_code=str(payload.get("tracking_code") or ""),
        is_plausible_code=bool(payload.get("is_plausible_code")),
        verified=bool(payload.get("verified")),
        status_code=payload.get("status_code"),
        status_description=payload.get("status_description"),
        last_event_description=payload.get("last_event_description"),
        last_event_province=payload.get("last_event_province"),
        last_event_datetime=payload.get("last_event_datetime"),
        event_count=int(payload.get("event_count") or 0),
        events=events,
        error_type=payload.get("error_type"),
        error_message=payload.get("error_message"),
    )


def latest_seller_message_id(messages: Sequence[ManualChatMessage]) -> str | None:
    for message in reversed(messages):
        if message.sender_type == "seller":
            return message.message_id
    return None


def render_manual_sandbox_tracking_result_panel(
    streamlit: Any,
    session_state: MutableMapping[str, Any],
    messages: Sequence[ManualChatMessage],
    *,
    title: str = "نتیجه استعلام کد رهگیری",
) -> None:
    """Render safe tracking verification summary below manual chat (FA labels)."""
    seller_id = latest_seller_message_id(messages)
    if not seller_id:
        return
    stored = get_tracking_result_for_message(session_state, seller_id)
    if not isinstance(stored, dict):
        return

    streamlit.markdown(f"##### {title}")
    streamlit.markdown(f"- **کد استخراج‌شده:** `{stored.get('tracking_code', '—')}`")

    meta = stored.get("auto_verification_metadata")
    if isinstance(meta, dict):
        api_field = meta.get("api_code_field") or "—"
        streamlit.markdown(f"- **روش ارسال به API:** `{api_field}`")
        if meta.get("selected_candidate_reason"):
            streamlit.markdown(f"- **دلیل انتخاب candidate:** {meta['selected_candidate_reason']}")
        candidates_list = meta.get("tracking_candidates")
        if isinstance(candidates_list, list):
            streamlit.markdown(f"- **تعداد candidateها:** {len(candidates_list)}")
        if meta.get("payload_trace_number") or meta.get("payload_package_number"):
            streamlit.markdown(
                f"- **TraceNumber ارسالی:** `{meta.get('payload_trace_number') or '—'}` · "
                f"**PackageNumber ارسالی:** `{meta.get('payload_package_number') or '—'}`",
            )

    streamlit.markdown(f"- **کد رهگیری (نتیجه API):** `{stored.get('tracking_code', '—')}`")

    if stored.get("error_type"):
        streamlit.markdown("- **وضعیت اعتبار:** خطا")
        streamlit.markdown(f"- **نوع خطا:** {stored.get('error_type')}")
        if stored.get("error_message"):
            streamlit.markdown(f"- **توضیح خطا:** {stored.get('error_message')}")
    elif stored.get("verified"):
        streamlit.markdown("- **وضعیت اعتبار:** معتبر")
    else:
        streamlit.markdown("- **وضعیت اعتبار:** نامعتبر")

    if stored.get("status_description"):
        streamlit.markdown(f"- **توضیح وضعیت:** {stored['status_description']}")
    if stored.get("last_event_description"):
        streamlit.markdown(f"- **آخرین رویداد:** {stored['last_event_description']}")
    if stored.get("last_event_province"):
        streamlit.markdown(f"- **استان آخرین رویداد:** {stored['last_event_province']}")
    if stored.get("last_event_datetime"):
        streamlit.markdown(f"- **زمان آخرین رویداد:** {stored['last_event_datetime']}")
    streamlit.markdown(f"- **تعداد رویدادها:** {stored.get('event_count', 0)}")
    if stored.get("source"):
        streamlit.markdown(f"- **مبدا:** {stored['source']}")
    if stored.get("destination"):
        streamlit.markdown(f"- **مقصد:** {stored['destination']}")
    if stored.get("safe_summary_fa"):
        streamlit.info(stored["safe_summary_fa"])

    if not stored.get("verified") and stored.get("status_description"):
        streamlit.warning("کد ارسال‌شده به API را با کد واردشده مقایسه کنید.")

    if isinstance(meta, dict) and meta.get("tracking_candidates"):
        streamlit.caption(f"کدهای بررسی‌شده: {', '.join(meta['tracking_candidates'])}")

    # Explicit refresh: re-verify tracking on operator click.
    refresh_key = f"iran_post_auto_refresh_{seller_id}"
    if streamlit.button("تازه‌سازی استعلام", key=refresh_key):
        seller_text = ""
        for msg in messages:
            if msg.sender_type == "seller" and msg.message_id == seller_id:
                seller_text = msg.text
                break

        settings = get_settings()
        outcome = try_manual_sandbox_auto_tracking_verify(
            seller_text,
            seller_message_id=seller_id,
            session_state=session_state,
            settings=settings,
            force_refresh=True,
        )

        if not isinstance(outcome.safe_result, dict) or not outcome.chat_reply:
            streamlit.warning("استعلام با خطا انجام نشد.")
            streamlit.rerun()

        created_at = utc_now_iso()
        new_tracking_code = str(outcome.safe_result.get("tracking_code") or "")
        new_tracking_verified = bool(outcome.safe_result.get("verified"))

        # Replace the existing tracking-aware AI bubble when present.
        ai_index: int | None = None
        for idx in range(len(messages) - 1, -1, -1):
            msg = messages[idx]
            if (
                msg.sender_type == "support_agent"
                and msg.is_ai_generated
                and msg.source == IRAN_POST_TRACKING_SOURCE
                and msg.tracking_verification_used
            ):
                ai_index = idx
                break

        new_reply = ManualChatMessage(
            message_id=(
                messages[ai_index].message_id if ai_index is not None else f"m{len(messages) + 1}"
            ),
            sender_type="support_agent",
            text=outcome.chat_reply,
            created_at=created_at,
            source=IRAN_POST_TRACKING_SOURCE,
            is_ai_generated=True,
            draft_provider="iran_post_tracking",
            tracking_verification_used=True,
            tracking_code=new_tracking_code,
            tracking_verified=new_tracking_verified,
        )

        updated = list(messages)
        if ai_index is not None:
            updated[ai_index] = new_reply
        else:
            updated.append(new_reply)

        session_state["manual_sandbox_chat_messages"] = [m.to_dict() for m in updated]
        streamlit.rerun()
