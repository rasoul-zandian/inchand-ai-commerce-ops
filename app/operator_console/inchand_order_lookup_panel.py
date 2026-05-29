"""Manual Inchand order lookup panel (operator console; session-only)."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult
from app.operator_console.console_models import OperatorTicket
from app.operator_console.i18n import DEFAULT_CONSOLE_LANG, t
from app.operator_console.manual_sandbox_shipment_decision import (
    store_order_lookup_in_session,
)
from app.tools.inchand.order_lookup import (
    assert_safe_order_lookup_payload,
    looks_like_inchand_order_id,
    lookup_inchand_order,
    normalize_inchand_order_id,
)
from app.tools.operational_actions_registry import (
    OperationalToolId,
    build_inchand_eligibility_context,
    evaluate_tool_eligibility,
    tool_registry_metadata_captions_fa,
)


def _session_result_key(room_id: str) -> str:
    return f"inchand_order_lookup_result_{room_id}"


def _resolve_order_id(graph: AgenticSandboxPreviewResult) -> str | None:
    candidate = (graph.inchand_order_id_candidate or "").strip()
    if candidate and looks_like_inchand_order_id(candidate):
        return normalize_inchand_order_id(candidate)
    extracted = (graph.extracted_order_ids or "").strip()
    if extracted:
        first = extracted.split(",")[0].strip()
        normalized = normalize_inchand_order_id(first)
        if normalized:
            return normalized
    return None


def should_show_inchand_order_lookup_section(
    graph: AgenticSandboxPreviewResult,
) -> bool:
    """Show panel when an Inchand order id is present or lookup is recommended."""
    if _resolve_order_id(graph):
        return True
    return bool(graph.inchand_order_lookup_recommended)


def render_inchand_order_lookup_panel(
    streamlit: Any,
    ticket: OperatorTicket,
    graph: AgenticSandboxPreviewResult,
    session_state: Any,
    *,
    lang: str = DEFAULT_CONSOLE_LANG,
    source_mode: str = "historical_replay",
) -> None:
    """Manual lookup button — never auto-calls API on page load."""
    if not should_show_inchand_order_lookup_section(graph):
        return

    streamlit.markdown(f"##### {t('inchand_order_lookup_section', lang)}")
    streamlit.caption(t("inchand_order_lookup_advisory_caption", lang))

    order_id = _resolve_order_id(graph)
    if order_id:
        streamlit.caption(f"{t('assisted_orders', lang)}: `{order_id}`")

    if graph.inchand_order_lookup_recommended:
        streamlit.info(t("inchand_order_lookup_recommended_note", lang))

    settings = get_settings()
    eligibility = evaluate_tool_eligibility(
        OperationalToolId.INCHAND_ORDER_LOOKUP,
        build_inchand_eligibility_context(
            settings,
            source_mode=source_mode,
            order_id_present=bool(order_id),
            manual_trigger=True,
        ),
    )
    for line in tool_registry_metadata_captions_fa(eligibility):
        streamlit.caption(line)

    if not settings.inchand_order_lookup_enabled:
        streamlit.warning(t("inchand_order_lookup_disabled", lang))
        return
    from app.tools.inchand.order_lookup import resolve_inchand_api_token

    if not resolve_inchand_api_token(settings):
        streamlit.warning(t("inchand_order_lookup_missing_token", lang))
        return
    if not eligibility.manual_allowed:
        return

    button_key = f"inchand_order_lookup_{ticket.room_id}"
    if streamlit.button(t("inchand_order_lookup_button", lang), key=button_key):
        result = lookup_inchand_order(order_id or "")
        payload = result.to_safe_dict()
        assert_safe_order_lookup_payload(payload)
        store_order_lookup_in_session(
            session_state,
            ticket.room_id,
            payload,
            order_id=order_id,
        )
        streamlit.rerun()

    stored = session_state.get(_session_result_key(ticket.room_id))
    if not isinstance(stored, dict):
        return

    assert_safe_order_lookup_payload(stored)
    streamlit.markdown(f"**{t('inchand_order_lookup_result_heading', lang)}**")
    if stored.get("order_status"):
        streamlit.markdown(
            f"- {t('inchand_order_lookup_order_status', lang)}: {stored['order_status']}",
        )
    if stored.get("primary_provider_status"):
        streamlit.markdown(
            f"- {t('inchand_order_lookup_provider_status', lang)}: "
            f"{stored['primary_provider_status']}",
        )
    if stored.get("primary_parcel_status_name"):
        streamlit.markdown(
            f"- {t('inchand_order_lookup_parcel_status', lang)}: "
            f"{stored['primary_parcel_status_name']}",
        )
    if stored.get("primary_parcel_tracking_code"):
        streamlit.markdown(
            f"- {t('inchand_order_lookup_parcel_tracking', lang)}: "
            f"`{stored['primary_parcel_tracking_code']}`",
        )
    providers = stored.get("providers") or []
    if providers and isinstance(providers[0], dict):
        delivered_at = providers[0].get("delivered_at")
        if delivered_at:
            streamlit.markdown(
                f"- {t('inchand_order_lookup_delivered_at', lang)}: {delivered_at}",
            )
    streamlit.markdown(
        f"- {t('inchand_order_lookup_has_tracking', lang)}: "
        f"{'✓' if stored.get('has_parcel_tracking_code') else '✗'}",
    )
    streamlit.markdown(
        f"- {t('inchand_order_lookup_is_delivered', lang)}: "
        f"{'✓' if stored.get('is_delivered_in_inchand') else '✗'}",
    )
    if stored.get("safe_summary_fa"):
        streamlit.info(stored["safe_summary_fa"])
    if stored.get("error_message"):
        streamlit.warning(stored["error_message"])
