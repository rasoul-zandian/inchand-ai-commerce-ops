"""Manual Iran Post tracking verification panel (operator console; session-only)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.console_models import OperatorTicket
from app.operator_console.i18n import DEFAULT_CONSOLE_LANG, t
from app.operator_console.manual_sandbox_shipment_decision import (
    inchand_order_lookup_session_key,
)
from app.tools.operational_actions_registry import (
    OperationalToolId,
    build_iran_post_eligibility_context,
    evaluate_tool_eligibility,
    tool_registry_metadata_captions_fa,
)
from app.tools.tracking.iran_post_tracking import (
    assert_safe_tracking_result_payload,
    looks_like_iran_post_tracking_code,
    verify_iran_post_tracking_code,
)


def _session_result_key(room_id: str) -> str:
    return f"iran_post_tracking_result_{room_id}"


def _resolve_tracking_code(graph: AgenticSandboxPreviewResult) -> str | None:
    code = (graph.extracted_tracking_code or "").strip()
    if code:
        return code
    return None


def should_show_tracking_verification_section(
    graph: AgenticSandboxPreviewResult,
) -> bool:
    """Show panel when a plausible Iran Post code exists or verification is recommended."""
    code = _resolve_tracking_code(graph)
    if not code:
        return False
    plausible, _ = looks_like_iran_post_tracking_code(code)
    if plausible:
        return True
    return bool(graph.tracking_verification_recommended)


def render_iran_post_tracking_verification_panel(
    streamlit: Any,
    ticket: OperatorTicket,
    graph: AgenticSandboxPreviewResult,
    session_state: Any,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
    source_mode: str = "historical_replay",
) -> None:
    """Manual verify button — never auto-calls API on page load."""
    if not should_show_tracking_verification_section(graph):
        return

    streamlit.markdown(f"##### {t('tracking_verification_section', lang)}")
    streamlit.caption(t("tracking_verification_advisory_caption", lang))

    code = _resolve_tracking_code(graph)
    if code:
        streamlit.caption(f"{t('assisted_tracking', lang)}: `{code}`")

    if graph.tracking_verification_recommended:
        streamlit.info(t("tracking_verification_recommended_note", lang))

    settings = get_settings()
    order_lookup = session_state.get(inchand_order_lookup_session_key(ticket.room_id))
    order_delivered = bool(
        isinstance(order_lookup, dict) and order_lookup.get("is_delivered_in_inchand"),
    )
    eligibility = evaluate_tool_eligibility(
        OperationalToolId.IRAN_POST_TRACKING_VERIFICATION,
        build_iran_post_eligibility_context(
            settings,
            source_mode=source_mode,
            tracking_code_present=bool(code),
            carrier_candidate=graph.tracking_verification_carrier_candidate or "iran_post",
            order_delivered_in_inchand=order_delivered,
            manual_trigger=True,
        ),
    )
    for line in tool_registry_metadata_captions_fa(eligibility):
        streamlit.caption(line)

    if not settings.iran_post_tracking_enabled:
        streamlit.warning(t("tracking_verification_disabled", lang))
        return
    if not (settings.iran_post_tracking_token or "").strip():
        streamlit.warning(t("tracking_verification_missing_token", lang))
        return
    if not eligibility.manual_allowed:
        return

    button_key = f"iran_post_verify_{ticket.room_id}"
    if streamlit.button(t("tracking_verification_verify_button", lang), key=button_key):
        result = verify_iran_post_tracking_code(code or "")
        payload = result.to_safe_dict()
        assert_safe_tracking_result_payload(payload)
        session_state[_session_result_key(ticket.room_id)] = payload
        streamlit.rerun()

    stored = session_state.get(_session_result_key(ticket.room_id))
    if not isinstance(stored, dict):
        return

    assert_safe_tracking_result_payload(stored)
    streamlit.markdown(f"**{t('tracking_verification_result_heading', lang)}**")
    streamlit.markdown(
        f"- {t('tracking_verification_verified', lang)}: {'✓' if stored.get('verified') else '✗'}",
    )
    if stored.get("status_description"):
        streamlit.markdown(
            f"- {t('tracking_verification_status', lang)}: {stored['status_description']}",
        )
    if stored.get("last_event_description"):
        streamlit.markdown(
            f"- {t('tracking_verification_last_event', lang)}: {stored['last_event_description']}",
        )
    if stored.get("last_event_province"):
        streamlit.markdown(
            f"- {t('tracking_verification_province', lang)}: {stored['last_event_province']}",
        )
    streamlit.markdown(
        f"- {t('tracking_verification_event_count', lang)}: {stored.get('event_count', 0)}",
    )
    if stored.get("destination"):
        streamlit.markdown(
            f"- {t('tracking_verification_destination', lang)}: {stored['destination']}",
        )
    if stored.get("source"):
        streamlit.markdown(f"- {t('tracking_verification_source', lang)}: {stored['source']}")
    if stored.get("safe_summary_fa"):
        streamlit.info(stored["safe_summary_fa"])
    if stored.get("error_message"):
        streamlit.warning(stored["error_message"])
