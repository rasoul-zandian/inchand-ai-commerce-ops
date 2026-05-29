"""Internal operator console (Streamlit) — local review of AI assist + retrieval summaries."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from app.agentic_sandbox.preview_review_feedback import (
    DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH,
    append_agentic_preview_review_feedback,
    build_agentic_preview_review_record,
    latest_agentic_preview_review_for_room,
    load_agentic_preview_review_summary,
)
from app.config import get_settings
from app.evals.draft_completion_calibration import detect_unnecessary_followup_in_draft
from app.evals.draft_quality_slice_analysis import (
    DEFAULT_SLICE_SUMMARY_PATH,
    compute_draft_quality_slice_analysis,
    load_draft_enrichment_index,
)
from app.evals.draft_review_metrics import compute_draft_review_metrics
from app.evals.offline_draft_generation import resolve_draft_generation_mode
from app.evals.suggested_action_calibration import compute_suggested_action_calibration
from app.live_shadow.live_first_turn_shadow_intake import (
    is_live_shadow_intake_recently_active,
    operator_ticket_from_live_ticket,
)
from app.operator_console.agentic_assisted_mode import (
    build_agentic_assisted_package,
    get_session_agentic_assisted_package,
    is_agentic_assisted_mode_allowed,
    load_graduation_status,
    store_session_agentic_assisted_package,
)
from app.operator_console.agentic_assisted_work_package import (
    render_operator_assisted_work_package,
)
from app.operator_console.agentic_draft_display import render_agentic_internal_draft_html
from app.operator_console.agentic_sandbox_preview import (
    get_session_agentic_preview,
    render_agentic_preview_markdown_or_lines,
    run_agentic_preview_for_ticket,
    store_session_agentic_preview,
)
from app.operator_console.assisted_ticket_input_builder import (
    build_assisted_graph_input_from_operator_ticket,
    build_operator_ticket_from_manual_chat,
    parity_debug_row_with_settings,
)
from app.operator_console.console_loader import (
    DEFAULT_OPERATOR_CONSOLE_DISPLAY_LIMIT_LABEL,
    DEFAULT_REDACTED_TICKETS_PATH,
    DEFAULT_REPLAY_PATH,
    OPERATOR_CONSOLE_DISPLAY_LIMIT_LABELS,
    apply_operator_console_display_limit,
    distinct_suggested_actions,
    distinct_ticket_labels,
    filter_operator_tickets,
    load_conversation_snapshot_index,
    load_operator_tickets,
    parse_operator_console_display_limit,
)
from app.operator_console.console_models import (
    OperatorTicket,
    compute_console_metrics,
    ticket_row_display_label,
)
from app.operator_console.datetime_display import format_iso_for_console
from app.operator_console.draft_preview import (
    DraftPreviewRecord,
    draft_mode_display_label,
    generate_draft_for_operator_ticket,
    get_session_draft_overrides,
    load_draft_preview_for_ticket,
    store_session_draft,
)
from app.operator_console.draft_review_feedback import (
    DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH,
    ENTITY_REVIEW_UI_CAPTION_FA,
    ENTITY_REVIEW_UI_OPTIONS,
    append_draft_review_feedback,
    build_draft_review_feedback_record,
    draft_review_badge_lines,
    entity_review_ui_label,
    latest_draft_review_for_room,
    load_draft_review_feedback_rows,
    map_entity_review_ui_choice,
    parse_draft_review_feedback_row,
)
from app.operator_console.feedback import (
    ALLOWED_FEEDBACK_TYPES,
    INTERNAL_NOTE_MAX_CHARS,
    append_operator_feedback,
    build_operator_feedback_record,
    load_operator_feedback_summary,
)
from app.operator_console.first_vendor_filter import (
    FirstVendorFilterStats,
    apply_operator_first_vendor_filter,
)
from app.operator_console.full_ticket_view import (
    build_full_ticket_conversation,
    render_full_ticket_conversation_html,
)
from app.operator_console.i18n import (
    LANG_EN,
    LANG_FA,
    apply_console_direction_css,
    get_console_language,
    set_console_language,
)
from app.operator_console.i18n import (
    t as translate_console,
)
from app.operator_console.intent_display import (
    draft_entity_fallback_message,
    first_turn_entity_fallback_message,
    first_turn_entity_section_caption,
    first_turn_entity_section_title,
    format_draft_entity_lines,
    format_first_turn_entity_lines,
    format_open_snapshot_entity_lines,
    format_operational_intent_lines,
    open_snapshot_entity_section_caption,
    open_snapshot_entity_section_title,
    operational_entity_fallback_message,
    operational_intent_fallback_message,
    ticket_has_operational_intent_data,
    use_first_turn_entity_display,
)
from app.operator_console.knowledge_hints import fetch_knowledge_hints_for_ticket
from app.operator_console.live_feed_fetch_handler import handle_live_api_feed_fetch
from app.operator_console.live_feed_loader import (
    CONSOLE_DATA_SOURCE_SESSION_KEY,
    DEFAULT_LIVE_API_FEED_PATH,
    DEFAULT_LIVE_ROOMS_FETCH_LIMIT,
    ELIGIBILITY_FILTER_OPTIONS,
    FIRST_SENDER_FILTER_OPTIONS,
    LATEST_SENDER_FILTER_OPTIONS,
    LIVE_API_FEED_ELIGIBILITY_FILTER_KEY,
    LIVE_API_FEED_ENTRIES_SESSION_KEY,
    LIVE_API_FEED_FIRST_SENDER_FILTER_KEY,
    LIVE_API_FEED_LAST_FETCH_TIME_SESSION_KEY,
    LIVE_API_FEED_LAST_REFRESH_SESSION_KEY,
    LIVE_API_FEED_LATEST_SENDER_FILTER_KEY,
    LIVE_API_FEED_PATH_SESSION_KEY,
    LIVE_API_FEED_TICKET_LABEL_FILTER_KEY,
    SOURCE_HISTORICAL_REPLAY,
    SOURCE_LIVE_API_FEED,
    LiveFeedTicketEntry,
    distinct_live_feed_first_senders,
    distinct_live_feed_latest_senders,
    distinct_live_feed_ticket_labels,
    filter_live_feed_dashboard_entries,
    live_feed_detail_row_number,
    load_live_feed_dashboard_entries,
    resolve_live_feed_filter_selection,
    resolve_live_feed_list_selection,
)
from app.operator_console.manual_chat_sandbox import (
    MANUAL_TICKET_LABEL_OPTIONS,
    SESSION_MANUAL_ASSISTED_PACKAGES,
    SESSION_MANUAL_CHAT_MESSAGES,
    SESSION_MANUAL_LAST_GENERATION_ERROR,
    SESSION_MANUAL_ROOM_ID,
    SESSION_MANUAL_SHOP_ID,
    SESSION_MANUAL_TICKET_LABEL,
    SOURCE_MANUAL_SANDBOX_CHAT,
    TICKET_LABEL_AUTO,
    clear_manual_auto_run_guards,
    get_manual_sandbox_assisted_package,
    handle_manual_add_message,
    init_manual_chat_session_defaults,
    load_sample_messages,
    manual_chat_should_generate_draft,
    manual_ticket_label_display,
    messages_from_session,
    regenerate_latest_ai_reply,
    remove_last_ai_generated_reply,
    render_manual_chat_bubble,
    resolve_manual_ticket_label,
    save_messages_to_session,
    store_manual_sandbox_assisted_package,
)
from app.operator_console.manual_sandbox_auto_tracking import (
    get_tracking_result_for_message,
    render_manual_sandbox_tracking_result_panel,
)
from app.operator_console.manual_sandbox_shipment_decision import (
    render_manual_sandbox_shipment_decision_panel,
)
from app.operator_console.rtl_text import format_context_lines, render_rtl_text_block
from app.tickets.conversation_models import ConversationTicketSnapshot

_DISCLAIMER = (
    "**Internal operator console (local only).** Aggregate metadata plus optional "
    "**full conversation mode** (redacted, sandbox-only). No customer responses, no auto-send, "
    "no retrieval hit bodies, no vectors. HITL exports/reports keep truncated safe previews. "
    "Optional **Submit feedback** writes append-only rows to `reports/operator_feedback.jsonl` "
    "(aggregate labels + note only; not used for training or AI assist)."
)
_DATA_SOURCE_OPTIONS: tuple[tuple[str, str], ...] = (
    (SOURCE_HISTORICAL_REPLAY, "data_source_historical_replay"),
    (SOURCE_LIVE_API_FEED, "data_source_live_api_feed"),
    (SOURCE_MANUAL_SANDBOX_CHAT, "data_source_manual_sandbox_chat"),
)


def _lang() -> str:
    return get_console_language(st.session_state)


def _t(key: str) -> str:
    return translate_console(key, _lang())


def _render_console_language_selector() -> None:
    current = _lang()
    selected = st.radio(
        "زبان / Language",
        options=[LANG_FA, LANG_EN],
        format_func=lambda value: "فارسی (FA)" if value == LANG_FA else "English (EN)",
        index=0 if current == LANG_FA else 1,
        horizontal=True,
        key="operator_console_lang_radio",
    )
    if selected != current:
        set_console_language(st.session_state, selected)


def _render_agentic_graph_draft_block(preview: object) -> None:
    from app.operator_console.agentic_sandbox_preview import AgenticSandboxPreviewResult

    if not isinstance(preview, AgenticSandboxPreviewResult):
        return
    block = render_agentic_internal_draft_html(preview, _lang())
    if block:
        st.markdown(block, unsafe_allow_html=True)


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _render_metrics_header(tickets: list[OperatorTicket]) -> None:
    metrics = compute_console_metrics(tickets)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total tickets", metrics.total_tickets)
    col2.metric("Escalation", metrics.escalation_count)
    col3.metric("Duplicate flag", metrics.duplicate_count)
    if metrics.action_distribution:
        dist = ", ".join(f"{key}: {count}" for key, count in metrics.action_distribution.items())
    else:
        dist = "—"
    col4.metric("Actions", dist)


def _render_knowledge_hints(ticket: OperatorTicket) -> None:
    settings = get_settings()
    if not settings.knowledge_hints_enabled:
        return
    try:
        hints = (
            ticket.knowledge_hints
            if ticket.knowledge_hints
            else fetch_knowledge_hints_for_ticket(ticket, settings=settings)
        )
    except (ValueError, OSError, RuntimeError) as exc:
        st.warning(f"Knowledge hints unavailable: {exc}")
        return
    st.markdown("#### Relevant official policy hints")
    st.caption(
        "Sandbox official policy snippets only (≤300 chars). Not used for draft/final "
        "responses or customer send."
    )
    if not hints:
        st.info("No policy hint found.")
        return
    for index, hint in enumerate(hints, start=1):
        st.markdown(
            f"**Hint {index}** · `{hint.document_type}` · "
            f"{hint.section_title} · _{hint.source_lane}_"
        )
        st.text(hint.snippet)


def _render_internal_draft_suggestion(ticket: OperatorTicket) -> None:
    settings = get_settings()
    preview_on = settings.operator_draft_preview_enabled
    generation_on = settings.operator_draft_generation_enabled
    if not preview_on and not generation_on:
        return

    st.markdown(f"#### {_t('internal_draft_suggestion')}")
    st.caption(_t("internal_draft_caption"))
    draft_mode = resolve_draft_generation_mode(settings)
    st.markdown(f"- **Draft mode:** {draft_mode_display_label(draft_mode)}")
    if draft_mode.value == "first_turn_only":
        st.caption(
            "Draft generated only from the seller's initial message and policy knowledge.",
        )
    overrides = get_session_draft_overrides(st.session_state)
    suggestions_path = st.session_state.get(
        "operator_draft_suggestions_path",
        settings.operator_draft_suggestions_path,
    )
    preview = load_draft_preview_for_ticket(
        ticket,
        suggestions_path=suggestions_path,
        session_overrides=overrides,
        load_offline=settings.operator_draft_preview_enabled,
        settings=settings,
    )

    if preview is None:
        st.info("No draft suggestion loaded for this ticket.")
    else:
        draft_label = _t("internal_draft_suggestion")
        block = render_rtl_text_block(draft_label, preview.draft_reply)
        if block:
            st.markdown(block, unsafe_allow_html=True)
        draft_entity_lines = format_draft_entity_lines(
            draft_entity_source=preview.draft_entity_source
            or preview.entity_source
            or "original_vendor_issue_preview",
            draft_extracted_order_ids=preview.draft_extracted_order_ids,
            draft_extracted_product_ids=preview.draft_extracted_product_ids,
            draft_extracted_tracking_code=preview.draft_extracted_tracking_code,
            draft_extracted_tracking_carrier=preview.draft_extracted_tracking_carrier,
            draft_extracted_iban=preview.draft_extracted_iban,
            draft_extracted_iban_masked=preview.draft_extracted_iban_masked,
            draft_entity_warnings_summary=preview.draft_entity_warnings_summary,
        )
        st.markdown(
            f"- **Conceptual intent:** {_display(preview.conceptual_intent_fa)}\n"
            f"- **detected_intent:** {_display(preview.detected_intent)}\n"
            f"- **suggested_action:** {_display(preview.suggested_action)}\n"
            f"- **Actionable:** {_display(preview.actionability_actionable)}\n"
            f"- **Missing entities:** {_display(preview.actionability_missing_entities)}\n"
            f"- **Validation reason:** {_display(preview.actionability_validation_reason)}\n"
            f"- **Draft style:** {_display(preview.draft_style)}\n"
            f"- **Draft length:** {_display(preview.draft_char_count)}\n"
            f"- **Style validation:** "
            f"{_display('ok' if preview.draft_style_ok else 'warnings')}\n"
            f"- **Style warnings:** "
            f"{_display(', '.join(preview.draft_style_warnings) or None)}\n"
            f"- **policy hint document types:** "
            f"{_display(', '.join(preview.knowledge_hint_document_types) or None)}\n"
            f"- **source:** {_display(preview.source)}\n"
            f"- **generated_at:** {_display(preview.generated_at)}\n"
            f"- **model:** {_display(preview.llm_model)} ({_display(preview.llm_provider)})"
        )
        st.markdown("**Draft entities (first-turn only)**")
        if draft_entity_lines:
            st.markdown("\n".join(draft_entity_lines))
        else:
            st.info(draft_entity_fallback_message())
        if preview.error_reason:
            st.warning(f"Draft note: {preview.error_reason}")

    if settings.operator_draft_generation_enabled:
        if st.button("Generate new draft", key=f"regen_draft_{ticket.room_id}"):
            try:
                hints = None
                if settings.knowledge_hints_enabled:
                    hints = fetch_knowledge_hints_for_ticket(ticket, settings=settings)
                record = generate_draft_for_operator_ticket(
                    ticket,
                    settings=settings,
                    hints=hints,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                store_session_draft(st.session_state, record)
                st.success(
                    "Draft regenerated in this session only (not saved to JSONL or tickets).",
                )
                st.rerun()
    else:
        st.button(
            "Generate new draft",
            key=f"regen_draft_disabled_{ticket.room_id}",
            disabled=True,
            help="Set OPERATOR_DRAFT_GENERATION_ENABLED=true to enable session-only regeneration.",
        )
        st.warning(
            "Draft regeneration is disabled. Set OPERATOR_DRAFT_GENERATION_ENABLED=true "
            "(and OPENAI_API_KEY for real OpenAI)."
        )

    _render_draft_review_form(
        ticket,
        preview=preview,
        draft_mode=draft_mode,
        settings=settings,
    )


def _render_agentic_sandbox_preview(ticket: OperatorTicket) -> None:
    settings = get_settings()
    if not settings.operator_agentic_sandbox_preview_enabled:
        return

    st.markdown(f"#### {_t('agentic_sandbox_preview')}")
    st.caption(_t("agentic_sandbox_preview_caption"))
    if st.button(_t("run_sandbox_graph"), key=f"agentic_sandbox_run_{ticket.room_id}"):
        try:
            preview = run_agentic_preview_for_ticket(ticket, settings=settings)
        except ValueError as exc:
            st.error(f"Sandbox preview failed safety checks: {exc}")
        except (OSError, RuntimeError) as exc:
            st.error(f"Sandbox preview failed: {exc}")
        else:
            store_session_agentic_preview(st.session_state, preview)
            st.success(_t("sandbox_graph_done"))

    preview = get_session_agentic_preview(st.session_state, ticket.room_id)
    if preview is None:
        st.info(_t("no_sandbox_preview"))
        return
    st.markdown("\n".join(render_agentic_preview_markdown_or_lines(preview, lang=_lang())))
    _render_agentic_graph_draft_block(preview)
    _render_agentic_preview_review_form(ticket)


def _agentic_preview_review_session_key(room_id: str) -> str:
    return f"agentic_preview_review_submitted_{room_id}"


def _render_agentic_preview_review_badges(room_id: str) -> None:
    session_review = st.session_state.get(_agentic_preview_review_session_key(room_id))
    review = None
    if isinstance(session_review, dict) and session_review.get("room_id") == room_id:
        review = session_review
    if review is None:
        latest = latest_agentic_preview_review_for_room(room_id)
        if latest is not None:
            review = latest.to_record()
    if review is None:
        return
    if review.get("overall_preview_useful"):
        st.markdown("**Sandbox review:** ✅ preview useful")
    else:
        st.markdown("**Sandbox review:** ⚠️ needs improvement")


def _render_agentic_preview_review_form(ticket: OperatorTicket) -> None:
    st.markdown(f"##### {_t('sandbox_preview_review')}")
    st.caption(_t("sandbox_preview_review_caption"))
    _render_agentic_preview_review_badges(ticket.room_id)

    with st.form(f"agentic_preview_review_form_{ticket.room_id}"):
        graph_status_correct = st.checkbox("Graph interpretation correct?", value=True)
        intent_correct = st.checkbox("Intent correct?", value=True)
        action_correct = st.checkbox("Suggested action correct?", value=True)
        actionability_correct = st.checkbox("Actionability correct?", value=True)
        entity_extraction_correct = st.checkbox("Entity extraction correct?", value=True)
        knowledge_hints_helpful = st.checkbox("Knowledge hints helpful?", value=True)
        safety_correct = st.checkbox("Safety flags correct?", value=True)
        ready_for_human_review_correct = st.checkbox(
            "Ready for human review correct?",
            value=True,
        )
        draft_length_reasonable = st.checkbox("Draft length reasonable?", value=True)
        overall_preview_useful = st.checkbox("Overall preview useful?", value=False)
        unnecessary_additional_details = st.checkbox(
            _t("review_unnecessary_additional_details"),
            value=False,
        )
        reviewer_note = st.text_area(
            "Reviewer note (optional)",
            max_chars=300,
            height=80,
            placeholder="Max 300 characters. No transcript, prompts, or snippets.",
        )
        submitted = st.form_submit_button(_t("submit_sandbox_review"))

    if not submitted:
        return

    try:
        record = build_agentic_preview_review_record(
            room_id=ticket.room_id,
            graph_status_correct=graph_status_correct,
            intent_correct=intent_correct,
            action_correct=action_correct,
            actionability_correct=actionability_correct,
            entity_extraction_correct=entity_extraction_correct,
            knowledge_hints_helpful=knowledge_hints_helpful,
            safety_correct=safety_correct,
            ready_for_human_review_correct=ready_for_human_review_correct,
            draft_length_reasonable=draft_length_reasonable,
            overall_preview_useful=overall_preview_useful,
            unnecessary_additional_details_requested=unnecessary_additional_details,
            reviewer_notes=reviewer_note.strip() if reviewer_note else None,
        )
        append_agentic_preview_review_feedback(record)
    except ValueError as exc:
        st.error(str(exc))
        return

    st.session_state[_agentic_preview_review_session_key(ticket.room_id)] = record
    short_id = str(record["review_id"])[:8]
    st.success(
        f"Sandbox preview review saved (`{short_id}…`). Evaluation only — not auto-learning.",
    )
    _render_agentic_preview_review_badges(ticket.room_id)


def _render_operator_agentic_assisted_mode(
    ticket: OperatorTicket,
    *,
    conversation_snapshot: Any | None = None,
    multi_turn_should_generate_draft: bool | None = None,
    multi_turn_skip_reason: str | None = None,
    assisted_package_getter: Any | None = None,
    assisted_package_store: Any | None = None,
    latest_support_skip_message: str | None = None,
    assisted_run_button_label: str | None = None,
    manual_assisted_regenerate: Any | None = None,
    assisted_source_mode: str = "historical_replay",
) -> None:
    settings = get_settings()
    if not settings.operator_agentic_assisted_mode_enabled:
        return

    st.markdown(f"#### {_t('operator_assisted_mode')}")
    st.caption(_t("operator_assisted_caption"))

    if settings.multi_turn_context_enabled and multi_turn_should_generate_draft is False:
        st.warning(
            latest_support_skip_message
            or multi_turn_skip_reason
            or "Draft generation skipped: latest message is not from seller.",
        )
    elif multi_turn_should_generate_draft is False:
        st.warning(
            latest_support_skip_message
            or multi_turn_skip_reason
            or "Draft generation skipped: latest message is not from seller.",
        )

    allowed, block_reason = is_agentic_assisted_mode_allowed(settings)
    graduation = load_graduation_status()
    if graduation is not None:
        st.caption(
            f"Graduation: **{graduation.get('overall_status', '—')}** "
            f"(`reports/agentic_sandbox_graduation_summary.json`)."
        )
    if not allowed:
        st.warning(
            block_reason or "Operator-assisted agentic mode is blocked by the graduation gate.",
        )
        return

    get_package = assisted_package_getter or get_session_agentic_assisted_package
    store_package = assisted_package_store or store_session_agentic_assisted_package

    if assisted_run_button_label:
        run_label = assisted_run_button_label
    else:
        run_label = _t("refresh_assisted_package")
        existing = get_package(st.session_state, ticket.room_id)
        if existing is None:
            run_label = _t("run_assisted_package")

    draft_allowed = multi_turn_should_generate_draft is not False
    if manual_assisted_regenerate is not None:
        draft_allowed = True
    if st.button(
        run_label,
        key=f"agentic_assisted_run_{ticket.room_id}",
        disabled=not draft_allowed,
    ):
        if manual_assisted_regenerate is not None:
            result = manual_assisted_regenerate()
            if result is not None and result.error:
                st.error(f"{_t('manual_sandbox_generation_error')}: {result.error}")
            elif result is not None and result.success:
                st.success(_t("assisted_package_ready"))
                st.rerun()
        else:
            try:
                package = build_agentic_assisted_package(
                    ticket,
                    settings=settings,
                    conversation_snapshot=conversation_snapshot,
                    source_mode=assisted_source_mode,
                )
            except ValueError as exc:
                st.error(f"Assisted package failed safety checks: {exc}")
            except (OSError, RuntimeError) as exc:
                st.error(f"Assisted package failed: {exc}")
            else:
                store_package(st.session_state, package)
                st.success(_t("assisted_package_ready"))

    package = get_package(st.session_state, ticket.room_id)
    if package is None:
        st.info(_t("no_assisted_package"))
        return

    render_operator_assisted_work_package(
        st,
        package,
        ticket,
        lang=_lang(),
        source_mode=assisted_source_mode,
    )
    st.info(_t("assisted_feedback_note"))


def _render_agentic_preview_review_sidebar_summary() -> None:
    summary = load_agentic_preview_review_summary(DEFAULT_AGENTIC_PREVIEW_REVIEW_FEEDBACK_PATH)
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Sandbox preview reviews**")
    st.sidebar.metric("Total sandbox reviews", summary.total_reviews)
    st.sidebar.metric("Preview usefulness %", summary.preview_usefulness_percent)
    st.sidebar.metric("Intent correctness %", summary.intent_correctness_percent)
    st.sidebar.metric("Action correctness %", summary.action_correctness_percent)
    st.sidebar.metric("Knowledge helpfulness %", summary.knowledge_helpfulness_percent)


def _draft_review_session_key(room_id: str) -> str:
    return f"draft_review_submitted_{room_id}"


def _render_draft_review_badges(room_id: str) -> None:
    session_review = st.session_state.get(_draft_review_session_key(room_id))
    review = None
    if isinstance(session_review, dict) and session_review.get("room_id") == room_id:
        review = parse_draft_review_feedback_row(session_review)
    if review is None:
        review = latest_draft_review_for_room(room_id)
    if review is None:
        return
    badges = draft_review_badge_lines(review)
    if badges:
        st.markdown(" ".join(f"**{badge}**" for badge in badges))


def _render_draft_review_form(
    ticket: OperatorTicket,
    *,
    preview: DraftPreviewRecord | None,
    draft_mode: object,
    settings: object,
) -> None:
    """Structured human review for internal drafts (local JSONL; no auto-learning)."""
    st.markdown("#### Draft review")
    st.caption(
        "Behavior calibration only — saved to `reports/draft_review_feedback.jsonl`. "
        "Not used for auto-training, prompt changes, or customer send."
    )
    _render_draft_review_badges(ticket.room_id)

    with st.form(f"draft_review_form_{ticket.room_id}"):
        intent_correct = st.checkbox("Intent correct", value=True)
        action_correct = st.checkbox("Suggested action correct", value=True)
        entity_review_choice = st.radio(
            "بررسی استخراج موجودیت",
            options=[key for key, _label in ENTITY_REVIEW_UI_OPTIONS],
            format_func=entity_review_ui_label,
            index=0,
        )
        st.caption(ENTITY_REVIEW_UI_CAPTION_FA)
        entities_applicable, entities_correct = map_entity_review_ui_choice(
            entity_review_choice,
        )
        draft_usable = st.checkbox("Draft usable with minimal edits", value=False)
        too_verbose = st.checkbox("Too verbose", value=False)
        hallucination_detected = st.checkbox(
            "Hallucination / unsupported claim",
            value=False,
        )
        reviewer_note = st.text_area(
            "Reviewer note (optional)",
            max_chars=300,
            height=80,
            placeholder="Max 300 characters. No transcript or prompts.",
        )
        better_reply = st.text_area(
            "Better reply suggestion (optional)",
            max_chars=300,
            height=80,
            placeholder="Short alternative wording for calibration.",
        )
        submitted = st.form_submit_button("Submit review")

    if not submitted:
        return

    try:
        seller_text = ticket.original_vendor_issue_preview or ""
        unnecessary_followup = False
        if preview is not None and preview.draft_reply:
            unnecessary_followup = detect_unnecessary_followup_in_draft(
                preview.draft_reply,
                seller_text=seller_text,
                suggested_action=preview.suggested_action,
                detected_intent=preview.detected_intent,
            )
        record = build_draft_review_feedback_record(
            room_id=ticket.room_id,
            draft_generation_mode=str(getattr(draft_mode, "value", draft_mode)),
            intent_correct=intent_correct,
            action_correct=action_correct,
            entities_applicable=entities_applicable,
            entities_correct=entities_correct,
            draft_usable=draft_usable,
            too_verbose=too_verbose,
            hallucination_detected=hallucination_detected,
            unnecessary_followup_detected=unnecessary_followup,
            preview=preview,
            ticket_label=ticket.ticket_label,
            draft_style=getattr(settings, "draft_style", None)
            or (preview.draft_style if preview else None),
            reviewer_note=reviewer_note.strip() if reviewer_note else None,
            suggested_better_reply=better_reply.strip() if better_reply else None,
        )
        append_draft_review_feedback(record)
    except ValueError as exc:
        st.error(str(exc))
        return

    st.session_state[_draft_review_session_key(ticket.room_id)] = record
    short_id = str(record["review_id"])[:8]
    st.success(
        f"Draft review saved (`{short_id}…`). For offline calibration only — not auto-learning.",
    )
    _render_draft_review_badges(ticket.room_id)


def _render_first_vendor_filter_sidebar(stats: FirstVendorFilterStats) -> None:
    st.sidebar.markdown("---")
    st.sidebar.markdown("**First-vendor filter**")
    st.sidebar.metric("Total tickets loaded", stats.total_loaded)
    if stats.filter_active:
        st.sidebar.metric("First-vendor tickets shown", stats.tickets_shown)
        st.sidebar.caption("Filter active: first-turn seller initiated")
    else:
        st.sidebar.caption("Filter disabled (OPERATOR_FIRST_VENDOR_ONLY=false)")


def _render_draft_review_sidebar_summary() -> None:
    rows = load_draft_review_feedback_rows(DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH)
    metrics = compute_draft_review_metrics(
        rows,
        source_feedback_path=str(DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH),
    )
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Draft review log**")
    st.sidebar.metric("Reviewed count", metrics.total_reviews)
    st.sidebar.metric("Usable %", round(metrics.usable_rate * 100, 1))
    st.sidebar.metric("Hallucination %", round(metrics.hallucination_rate * 100, 1))
    st.sidebar.metric("Verbosity %", round(metrics.verbosity_rate * 100, 1))
    st.sidebar.metric("Entity accuracy %", round(metrics.entity_accuracy_rate * 100, 1))
    st.sidebar.caption(
        f"Entity reviews: {metrics.entity_applicable_count} applicable, "
        f"{metrics.entity_not_applicable_count} not applicable.",
    )
    action_cal = compute_suggested_action_calibration(rows)
    st.sidebar.markdown("**Suggested action calibration**")
    st.sidebar.metric("Action accuracy %", round(action_cal.action_accuracy_rate * 100, 1))
    st.sidebar.metric("Monitor usage %", round(action_cal.monitor_usage_rate * 100, 1))
    st.sidebar.metric("Fallback overuse", action_cal.fallback_overuse_count)
    st.sidebar.caption(
        "Local JSONL only. Reports: "
        "`build_draft_review_metrics_report.py`, "
        "`build_suggested_action_calibration_report.py`."
    )
    _render_draft_quality_slice_sidebar(rows)


def _render_draft_quality_slice_sidebar(rows: list) -> None:
    """Read-only slice highlights (analytics only)."""
    if not rows:
        return
    settings = get_settings()
    enrichment = load_draft_enrichment_index(settings.operator_draft_suggestions_path)
    slice_summary = compute_draft_quality_slice_analysis(
        rows,
        enrichment_index=enrichment,
        source_feedback_path=str(DEFAULT_DRAFT_REVIEW_FEEDBACK_PATH),
        enrichment_source_path=str(settings.operator_draft_suggestions_path),
    )
    if slice_summary.total_reviews == 0:
        return
    st.sidebar.markdown("**Draft quality slices**")
    if slice_summary.weakest_slices:
        weak = slice_summary.weakest_slices[0]
        st.sidebar.caption(
            f"Weakest: {weak.slice_type}/{weak.slice_key[:28]} "
            f"({weak.usable_rate:.0%} usable, n={weak.total_reviews})",
        )
    if slice_summary.strongest_slices:
        strong = slice_summary.strongest_slices[0]
        st.sidebar.caption(
            f"Strongest: {strong.slice_type}/{strong.slice_key[:28]} "
            f"({strong.usable_rate:.0%} usable)",
        )
    best_usable = max(
        (
            report
            for report in slice_summary.slice_reports
            if report.total_reviews >= slice_summary.min_slice_reviews
        ),
        key=lambda report: report.usable_rate,
        default=None,
    )
    if best_usable is not None:
        st.sidebar.caption(
            f"Best usable slice: {best_usable.slice_type}/{best_usable.slice_key[:24]} "
            f"({best_usable.usable_rate:.0%})",
        )
    st.sidebar.caption(
        f"Offline report: `{DEFAULT_SLICE_SUMMARY_PATH}` (build_draft_quality_slice_analysis.py).",
    )


def _snapshot_index_cache_key(path: str) -> str:
    return f"conversation_snapshot_index::{path}"


def _get_conversation_snapshot_index(path: str) -> dict[str, ConversationTicketSnapshot]:
    key = _snapshot_index_cache_key(path)
    if key not in st.session_state:
        st.session_state[key] = load_conversation_snapshot_index(path)
    cached = st.session_state[key]
    if isinstance(cached, dict):
        return cached
    return {}


def _render_full_conversation(
    ticket: OperatorTicket,
    *,
    snapshot_index: dict[str, ConversationTicketSnapshot],
) -> None:
    st.markdown("#### Full conversation (internal)")
    st.caption(
        "Redacted full thread for local operator review — no truncation, no system/internal "
        "messages, no draft/final bodies. Not exported to HITL JSONL."
    )
    snapshot = snapshot_index.get(ticket.room_id)
    if snapshot is None:
        st.warning(
            "Full conversation unavailable: load redacted ticket JSONL with this room_id "
            f"({ticket.room_id}).",
        )
        return
    try:
        conversation = build_full_ticket_conversation(snapshot)
    except (ValueError, TypeError) as exc:
        st.error(f"Could not build full conversation: {exc}")
        return
    block = render_full_ticket_conversation_html(conversation)
    if block:
        st.markdown(block, unsafe_allow_html=True)
    st.caption(f"Visible messages: {len(conversation.messages)}")


def _render_compact_ticket_preview(ticket: OperatorTicket, *, preview_mode: str) -> None:
    if preview_mode == "Open ticket snapshot":
        st.markdown("#### Open ticket snapshot")
        st.caption(
            "Operational slice at the latest vendor turn — no post-vendor support "
            "replies or full transcript."
        )
        if ticket.original_vendor_issue_preview:
            block = render_rtl_text_block(
                "Original issue",
                ticket.original_vendor_issue_preview,
            )
            if block:
                st.markdown(block, unsafe_allow_html=True)
        else:
            st.caption("No original vendor issue preview available.")
        if ticket.latest_vendor_message:
            block = render_rtl_text_block(
                "Latest vendor message",
                ticket.latest_vendor_message,
            )
            if block:
                st.markdown(block, unsafe_allow_html=True)
        else:
            st.caption("No latest vendor message available.")
        if ticket.recent_context_preview:
            formatted = format_context_lines(ticket.recent_context_preview)
            block = render_rtl_text_block("Recent context", formatted)
            if block:
                st.markdown(block, unsafe_allow_html=True)
        if ticket.open_ticket_preview:
            block = render_rtl_text_block("", ticket.open_ticket_preview, compact=True)
            if block:
                st.markdown(block, unsafe_allow_html=True)
        if not any(
            (
                ticket.original_vendor_issue_preview,
                ticket.latest_vendor_message,
                ticket.recent_context_preview,
                ticket.open_ticket_preview,
            ),
        ):
            st.caption("No open ticket snapshot available for this ticket.")
    else:
        st.markdown("#### Ticket text preview (historical)")
        if ticket.ticket_text_preview:
            st.caption("Redacted, truncated preview — not the full transcript.")
            block = render_rtl_text_block("Historical preview", ticket.ticket_text_preview)
            if block:
                st.markdown(block, unsafe_allow_html=True)
        else:
            st.caption("No safe preview available for this ticket.")


def _render_ticket_entity_sections(ticket: OperatorTicket) -> None:
    """Entity blocks: first-turn primary in calibration mode; open snapshot in expander."""
    settings = get_settings()
    draft_mode = resolve_draft_generation_mode(settings)
    if use_first_turn_entity_display(draft_generation_mode=draft_mode):
        st.markdown(f"#### {first_turn_entity_section_title()}")
        st.caption(first_turn_entity_section_caption())
        first_turn_lines = format_first_turn_entity_lines(ticket)
        if first_turn_lines:
            st.markdown("\n".join(first_turn_lines))
        else:
            st.info(first_turn_entity_fallback_message())
        with st.expander("Open snapshot entities (debug)", expanded=False):
            st.caption(open_snapshot_entity_section_caption())
            open_lines = format_open_snapshot_entity_lines(ticket)
            if open_lines:
                st.markdown("\n".join(open_lines))
            else:
                st.caption("No AI assist / open snapshot entity fields on this ticket.")
        return

    st.markdown(f"#### {open_snapshot_entity_section_title()}")
    st.caption(open_snapshot_entity_section_caption())
    open_lines = format_open_snapshot_entity_lines(ticket)
    if open_lines:
        st.markdown("\n".join(open_lines))
    else:
        st.info(operational_entity_fallback_message())


def _render_ticket_detail(
    ticket: OperatorTicket,
    *,
    row_number: int,
    preview_mode: str,
    full_conversation_mode: bool,
    snapshot_index: dict[str, ConversationTicketSnapshot],
    conversation_snapshot: ConversationTicketSnapshot | None = None,
    multi_turn_should_generate_draft: bool | None = None,
    multi_turn_skip_reason: str | None = None,
    assisted_package_getter: Any | None = None,
    assisted_package_store: Any | None = None,
    latest_support_skip_message: str | None = None,
    assisted_run_button_label: str | None = None,
    manual_assisted_regenerate: Any | None = None,
    assisted_source_mode: str = "historical_replay",
) -> None:
    row_number = max(1, row_number or 1)
    st.subheader(ticket_row_display_label(row_number, ticket))
    st.markdown("#### Ticket")
    st.markdown(
        f"- **ticket_label:** {_display(ticket.ticket_label)}\n"
        f"- **route_label:** {_display(ticket.route_label)}\n"
        f"- **assigned_department:** {_display(ticket.assigned_department)}\n"
        f"- **review_priority:** {_display(ticket.review_priority)}"
    )
    if full_conversation_mode:
        _render_full_conversation(ticket, snapshot_index=snapshot_index)
    else:
        _render_compact_ticket_preview(ticket, preview_mode=preview_mode)
    st.markdown("#### AI assist")
    st.markdown(
        f"- **suggested_action:** {_display(ticket.suggested_action)}\n"
        f"- **Action reason:** {_display(ticket.suggested_action_reason)}\n"
        f"- **suggested_priority:** {_display(ticket.suggested_priority)}\n"
        f"- **escalation_recommended:** {_display(ticket.escalation_recommended)}\n"
        f"- **duplicate_possible:** {_display(ticket.duplicate_possible)}\n"
        f"- **confidence_band:** {_display(ticket.confidence_band)}"
    )
    st.markdown("#### Operational intent (taxonomy v1)")
    st.caption(
        "Rule-based intent for operator review — distinct from coarse ticket_label "
        "(support / complaint / fund). No LLM classifier; no auto-send."
    )
    if ticket_has_operational_intent_data(ticket):
        st.markdown("\n".join(format_operational_intent_lines(ticket)))
    else:
        st.info(operational_intent_fallback_message())
    _render_ticket_entity_sections(ticket)
    if ticket.seller_intent_type:
        st.markdown("#### Seller message class (Step 169)")
        st.caption("Notification vs operational request — compat layer under taxonomy v1.")
        request_type = (
            ticket.seller_operational_request_type
            if ticket.seller_intent_type == "seller_operational_request"
            else ticket.seller_notification_type
        )
        st.markdown(
            f"- **seller_intent_type:** {_display(ticket.seller_intent_type)}\n"
            f"- **request_type:** {_display(request_type)}\n"
            f"- **status:** {_display(ticket.seller_notification_shipment_status)}"
        )
    st.markdown("#### Retrieval summary")
    st.markdown(
        f"- **retrieval_gate_decision:** {_display(ticket.retrieval_gate_decision)}\n"
        f"- **retrieval_result_count:** {_display(ticket.retrieval_result_count)}"
    )
    _render_knowledge_hints(ticket)
    _render_internal_draft_suggestion(ticket)
    _render_agentic_sandbox_preview(ticket)
    _render_operator_agentic_assisted_mode(
        ticket,
        conversation_snapshot=conversation_snapshot,
        multi_turn_should_generate_draft=multi_turn_should_generate_draft,
        multi_turn_skip_reason=multi_turn_skip_reason,
        assisted_package_getter=assisted_package_getter,
        assisted_package_store=assisted_package_store,
        latest_support_skip_message=latest_support_skip_message,
        assisted_run_button_label=assisted_run_button_label,
        manual_assisted_regenerate=manual_assisted_regenerate,
        assisted_source_mode=assisted_source_mode,
    )
    st.markdown("#### Operator feedback (local JSONL)")
    st.caption(
        "Persists to `reports/operator_feedback.jsonl` — no ticket text, transcript, "
        "retrieval hits, or draft/final content."
    )
    with st.form(f"feedback_form_{ticket.room_id}"):
        feedback_type = st.selectbox(
            "Feedback type",
            options=sorted(ALLOWED_FEEDBACK_TYPES),
            key=f"fb_type_{ticket.room_id}",
        )
        internal_note = st.text_area(
            "Internal note (optional)",
            max_chars=INTERNAL_NOTE_MAX_CHARS,
            height=100,
            key=f"fb_note_{ticket.room_id}",
            placeholder="Max 500 characters. No transcript or raw payload.",
        )
        submitted = st.form_submit_button("Submit feedback")
    if submitted:
        try:
            note_value = internal_note.strip() if internal_note else None
            record = build_operator_feedback_record(
                room_id=ticket.room_id,
                suggested_action=ticket.suggested_action,
                ticket_label=ticket.ticket_label,
                route_label=ticket.route_label,
                feedback_type=feedback_type,
                internal_note=note_value,
            )
            append_operator_feedback(record)
        except ValueError as exc:
            st.error(str(exc))
        else:
            short_id = str(record["feedback_id"])[:8]
            st.success(f"Feedback saved (`{short_id}…`). Not used for auto-learning or send.")


def _data_source_label(source_key: str) -> str:
    for value, i18n_key in _DATA_SOURCE_OPTIONS:
        if value == source_key:
            return _t(i18n_key)
    return source_key


def _init_console_data_source() -> str:
    if CONSOLE_DATA_SOURCE_SESSION_KEY not in st.session_state:
        st.session_state[CONSOLE_DATA_SOURCE_SESSION_KEY] = SOURCE_HISTORICAL_REPLAY
    return str(st.session_state[CONSOLE_DATA_SOURCE_SESSION_KEY])


def _skip_reason_display(skip_reason: str | None) -> str:
    if not skip_reason:
        return "—"
    key = f"live_feed_skip_{skip_reason}"
    translated = translate_console(key, _lang())
    if translated != key:
        return translated
    return skip_reason


def _reload_live_api_feed_entries(source_path: Path) -> list[LiveFeedTicketEntry]:
    entries = load_live_feed_dashboard_entries(source_path)
    st.session_state[LIVE_API_FEED_ENTRIES_SESSION_KEY] = entries
    st.session_state[LIVE_API_FEED_LAST_REFRESH_SESSION_KEY] = (
        datetime.now(tz=UTC).replace(microsecond=0).isoformat()
    )
    st.session_state[LIVE_API_FEED_PATH_SESSION_KEY] = str(source_path)
    return entries


def _format_live_feed_timestamp(iso_value: str | None) -> str:
    return format_iso_for_console(iso_value, _lang())


def _live_feed_eligibility_badge(entry: LiveFeedTicketEntry) -> str:
    if entry.eligible:
        return _t("live_feed_badge_eligible")
    reason = _skip_reason_display(entry.skip_reason)
    return f"{_t('live_feed_badge_skipped')}: {reason}"


def _live_feed_row_label(index: int, entry: LiveFeedTicketEntry) -> str:
    label = entry.ticket_label or "—"
    updated = _format_live_feed_timestamp(entry.updated_at_iso)
    sender = entry.first_sender or "—"
    badge = _live_feed_eligibility_badge(entry)
    return f"#{index} — {entry.room_id} · {updated} · {label} · {sender} · {badge}"


def _render_live_feed_ticket_card(entry: LiveFeedTicketEntry) -> None:
    updated = _format_live_feed_timestamp(entry.updated_at_iso)
    sender = _display(entry.first_sender)
    badge = _live_feed_eligibility_badge(entry)
    st.markdown(
        f"**{entry.room_id}** · `{updated}` · **{entry.ticket_label or '—'}** · "
        f"{_t('live_feed_first_sender')}: {sender} · {badge}",
    )
    preview = entry.seller_preview
    if preview:
        st.caption(preview[:220] + ("…" if len(preview) > 220 else ""))


def _init_live_feed_filter_session(
    key: str,
    options: list[str],
) -> list[str]:
    if key not in st.session_state:
        st.session_state[key] = list(options)
    stored = st.session_state.get(key, [])
    if isinstance(stored, list) and stored:
        return [value for value in stored if value in options]
    return list(options)


def _render_live_feed_sidebar_filters(
    entries: list[LiveFeedTicketEntry],
) -> list[LiveFeedTicketEntry]:
    st.sidebar.markdown("---")
    label_options = distinct_live_feed_ticket_labels(entries)
    if not label_options:
        label_options = ["unknown"]
    label_default = _init_live_feed_filter_session(
        LIVE_API_FEED_TICKET_LABEL_FILTER_KEY,
        label_options,
    )
    selected_labels = st.sidebar.multiselect(
        _t("live_feed_filter_ticket_label"),
        options=label_options,
        default=label_default,
        key="live_api_feed_ticket_label_multiselect",
    )
    st.session_state[LIVE_API_FEED_TICKET_LABEL_FILTER_KEY] = selected_labels

    eligibility_options = list(ELIGIBILITY_FILTER_OPTIONS)
    eligibility_default = _init_live_feed_filter_session(
        LIVE_API_FEED_ELIGIBILITY_FILTER_KEY,
        eligibility_options,
    )
    selected_eligibility = st.sidebar.multiselect(
        _t("live_feed_filter_eligibility"),
        options=eligibility_options,
        default=eligibility_default,
        format_func=lambda value: (
            _t("live_feed_eligibility_eligible")
            if value == "eligible"
            else _skip_reason_display(value)
        ),
        key="live_api_feed_eligibility_multiselect",
    )
    st.session_state[LIVE_API_FEED_ELIGIBILITY_FILTER_KEY] = selected_eligibility

    present_senders = distinct_live_feed_first_senders(entries)
    sender_options = [sender for sender in FIRST_SENDER_FILTER_OPTIONS if sender in present_senders]
    if not sender_options:
        sender_options = list(FIRST_SENDER_FILTER_OPTIONS)
    sender_default = _init_live_feed_filter_session(
        LIVE_API_FEED_FIRST_SENDER_FILTER_KEY,
        sender_options,
    )
    selected_senders = st.sidebar.multiselect(
        _t("live_feed_filter_first_sender"),
        options=sender_options,
        default=sender_default,
        key="live_api_feed_first_sender_multiselect",
    )
    st.session_state[LIVE_API_FEED_FIRST_SENDER_FILTER_KEY] = selected_senders

    present_latest = distinct_live_feed_latest_senders(entries)
    latest_options = [sender for sender in LATEST_SENDER_FILTER_OPTIONS if sender in present_latest]
    if not latest_options:
        latest_options = list(LATEST_SENDER_FILTER_OPTIONS)
    latest_default = _init_live_feed_filter_session(
        LIVE_API_FEED_LATEST_SENDER_FILTER_KEY,
        latest_options,
    )
    selected_latest = st.sidebar.multiselect(
        "Latest sender",
        options=latest_options,
        default=latest_default,
        key="live_api_feed_latest_sender_multiselect",
    )
    st.session_state[LIVE_API_FEED_LATEST_SENDER_FILTER_KEY] = selected_latest

    label_filter = resolve_live_feed_filter_selection(
        selected_labels,
        all_options=label_options,
    )
    eligibility_filter = resolve_live_feed_filter_selection(
        selected_eligibility,
        all_options=eligibility_options,
    )
    sender_filter = resolve_live_feed_filter_selection(
        selected_senders,
        all_options=sender_options,
    )
    latest_filter = resolve_live_feed_filter_selection(
        selected_latest,
        all_options=latest_options,
    )
    return filter_live_feed_dashboard_entries(
        entries,
        ticket_labels=label_filter,
        eligibility_reasons=eligibility_filter,
        first_senders=sender_filter,
        latest_senders=latest_filter,
    )


def _render_live_feed_metadata(entry: LiveFeedTicketEntry, *, settings: Any | None = None) -> None:
    cfg = settings or get_settings()
    st.markdown(f"#### {_t('live_feed_metadata_title')}")
    if entry.eligible:
        st.caption(_t("live_feed_hitl_required"))
    cols = st.columns(3)
    cols[0].metric(_t("live_feed_source_system"), _display(entry.source_system))
    cols[1].metric(_t("live_feed_updated_at"), _format_live_feed_timestamp(entry.updated_at_iso))
    cols[2].metric(_t("live_feed_created_at"), _format_live_feed_timestamp(entry.created_at_iso))
    cols2 = st.columns(3)
    cols2[0].metric(_t("live_feed_message_count"), entry.message_count)
    cols2[1].metric(_t("live_feed_first_sender"), _display(entry.first_sender))
    cols2[2].metric(_t("live_feed_latest_sender"), _display(entry.latest_sender))
    cols3 = st.columns(3)
    if entry.eligible:
        cols3[0].metric(_t("live_feed_eligibility_reason"), _t("live_feed_badge_eligible"))
    else:
        cols3[0].metric(
            _t("live_feed_eligibility_reason"),
            _skip_reason_display(entry.skip_reason),
        )
    if (
        cfg.multi_turn_context_enabled
        and entry.ticket is not None
        and entry.ticket.snapshot is not None
    ):
        from app.workflows.multi_turn_ticket_context import build_multi_turn_context

        ctx = build_multi_turn_context(entry.ticket.snapshot, settings=cfg)
        cols3[1].metric("pending_request_type", _display(ctx.pending_request_type))
        cols3[2].metric(
            "pending_request_fulfilled",
            "yes" if ctx.pending_request_fulfilled else "no",
        )
        st.caption(
            f"should_generate_draft: {'yes' if ctx.should_generate_draft else 'no'}"
            + (f" · skip: {ctx.should_skip_reason}" if ctx.should_skip_reason else ""),
        )
    if entry.parse_error:
        st.warning(entry.parse_error)


def _manual_ticket_label_select_label(value: str) -> str:
    if value == TICKET_LABEL_AUTO:
        return _t("manual_sandbox_ticket_label_auto")
    return _t(f"manual_sandbox_ticket_label_{value}")


def _render_manual_sandbox_chat_panel() -> None:
    settings = get_settings()
    init_manual_chat_session_defaults(st.session_state)
    st.markdown(_t("manual_sandbox_disclaimer"))

    label_values = [value for value, _ in MANUAL_TICKET_LABEL_OPTIONS]
    current_label = str(st.session_state.get(SESSION_MANUAL_TICKET_LABEL, TICKET_LABEL_AUTO))
    if current_label not in label_values:
        current_label = TICKET_LABEL_AUTO
    with st.sidebar.expander(_t("manual_sandbox_ticket_label"), expanded=True):
        selected_label = st.selectbox(
            _t("manual_sandbox_ticket_label"),
            options=label_values,
            index=label_values.index(current_label),
            format_func=_manual_ticket_label_select_label,
            key="manual_sandbox_ticket_label_select",
        )
        st.session_state[SESSION_MANUAL_TICKET_LABEL] = selected_label
        st.session_state[SESSION_MANUAL_ROOM_ID] = st.text_input(
            _t("manual_sandbox_room_id"),
            value=str(st.session_state.get(SESSION_MANUAL_ROOM_ID, "")),
            key="manual_sandbox_room_id_input",
        )
        st.session_state[SESSION_MANUAL_SHOP_ID] = st.text_input(
            _t("manual_sandbox_shop_id"),
            value=str(st.session_state.get(SESSION_MANUAL_SHOP_ID, "")),
            key="manual_sandbox_shop_id_input",
        )
        if st.button("Use test shop_id", key="manual_sandbox_use_test_shop_id_btn"):
            st.session_state[SESSION_MANUAL_SHOP_ID] = "manual-sandbox-shop"
            st.rerun()

    room_id = str(st.session_state.get(SESSION_MANUAL_ROOM_ID, "")).strip()
    shop_id = str(st.session_state.get(SESSION_MANUAL_SHOP_ID, "")).strip() or None
    st.caption(
        "شناسه فروشگاه در context موجود است: " + ("بله" if bool(shop_id) else "خیر"),
    )
    if not shop_id:
        st.warning("shop_id در context موجود نیست؛ ممکن است مدل شناسه فروشگاه بخواهد.")
    explicit_label = resolve_manual_ticket_label(
        str(st.session_state.get(SESSION_MANUAL_TICKET_LABEL)),
    )

    messages = messages_from_session(st.session_state.get(SESSION_MANUAL_CHAT_MESSAGES))
    st.markdown("#### Manual sandbox chat")
    ai_label = _t("manual_sandbox_ai_reply_label")
    if messages:
        bubbles = "".join(
            render_manual_chat_bubble(message, ai_reply_label=ai_label) for message in messages
        )
        st.markdown(bubbles, unsafe_allow_html=True)
        render_manual_sandbox_tracking_result_panel(st, st.session_state, messages)
        render_manual_sandbox_shipment_decision_panel(st, st.session_state, messages)
    else:
        st.info(_t("manual_sandbox_no_messages"))

    gen_error = st.session_state.get(SESSION_MANUAL_LAST_GENERATION_ERROR)
    if gen_error:
        st.error(f"{_t('manual_sandbox_generation_error')}: {gen_error}")

    role = st.radio(
        "Role",
        options=["seller", "support_agent"],
        format_func=lambda value: (
            _t("manual_sandbox_role_seller")
            if value == "seller"
            else _t("manual_sandbox_role_support")
        ),
        horizontal=True,
        key="manual_sandbox_role_radio",
    )
    draft_text = st.text_area(
        "Message",
        height=120,
        placeholder=_t("manual_sandbox_message_placeholder"),
        key="manual_sandbox_message_input",
    )
    col_add, col_clear, col_sample = st.columns(3)
    with col_add:
        if st.button(_t("manual_sandbox_add_message"), key="manual_sandbox_add_message_btn"):
            result = handle_manual_add_message(
                st.session_state,
                role=role,
                text=draft_text,
                room_id=room_id,
                ticket_label=explicit_label,
                shop_id=shop_id,
                settings=settings,
            )
            if result is not None and result.error:
                st.error(f"{_t('manual_sandbox_generation_error')}: {result.error}")
            elif result is not None and result.success and result.error is None:
                pass
            elif result is not None and not result.success:
                st.error(result.error or _t("manual_sandbox_generation_error"))
            st.rerun()
    with col_clear:
        if st.button(_t("manual_sandbox_clear_chat"), key="manual_sandbox_clear_chat_btn"):
            st.session_state[SESSION_MANUAL_CHAT_MESSAGES] = []
            bucket = st.session_state.get(SESSION_MANUAL_ASSISTED_PACKAGES)
            if isinstance(bucket, dict):
                bucket.clear()
            clear_manual_auto_run_guards(st.session_state)
            st.rerun()
    with col_sample:
        if st.button(_t("manual_sandbox_load_sample"), key="manual_sandbox_load_sample_btn"):
            st.session_state[SESSION_MANUAL_CHAT_MESSAGES] = [
                message.to_dict() for message in load_sample_messages()
            ]
            clear_manual_auto_run_guards(st.session_state)
            st.rerun()

    col_regen, col_remove = st.columns(2)
    with col_regen:
        if st.button(
            _t("manual_sandbox_regenerate_ai_reply"),
            key="manual_sandbox_regenerate_ai_reply_btn",
            disabled=not messages,
        ):
            regen_messages = messages_from_session(
                st.session_state.get(SESSION_MANUAL_CHAT_MESSAGES),
            )
            regen_result = regenerate_latest_ai_reply(
                regen_messages,
                room_id=room_id,
                ticket_label=explicit_label,
                shop_id=shop_id,
                session_state=st.session_state,
                settings=settings,
            )
            if regen_result.ai_message is not None:
                save_messages_to_session(st.session_state, regen_messages)
            if regen_result.error:
                st.error(f"{_t('manual_sandbox_generation_error')}: {regen_result.error}")
            st.rerun()
    with col_remove:
        if st.button(
            _t("manual_sandbox_remove_last_ai_reply"),
            key="manual_sandbox_remove_last_ai_reply_btn",
            disabled=not messages,
        ):
            remove_messages = messages_from_session(
                st.session_state.get(SESSION_MANUAL_CHAT_MESSAGES),
            )
            if remove_last_ai_generated_reply(remove_messages):
                save_messages_to_session(st.session_state, remove_messages)
            st.rerun()

    if not messages:
        return
    try:
        ticket, snapshot = build_operator_ticket_from_manual_chat(
            messages,
            room_id=room_id,
            ticket_label=explicit_label,
            shop_id=shop_id,
        )
        assisted_input_bundle = build_assisted_graph_input_from_operator_ticket(
            ticket,
            conversation_snapshot=snapshot,
            source_mode="manual_sandbox_chat",
            settings=settings,
        )
    except ValueError as exc:
        st.error(str(exc))
        return
    label_display = manual_ticket_label_display(
        str(st.session_state.get(SESSION_MANUAL_TICKET_LABEL, TICKET_LABEL_AUTO)),
        snapshot,
    )
    st.markdown("---")
    st.markdown(
        f"- **room_id:** {_display(ticket.room_id)}\n"
        f"- **ticket_label:** {_display(label_display)}\n"
        f"- **source_system:** manual_sandbox_chat"
    )
    with st.expander("Input parity / debug"):
        for key, value in parity_debug_row_with_settings(
            assisted_input_bundle,
            settings=settings,
        ).items():
            st.markdown(f"- **{key}:** {_display(value)}")
        package = get_manual_sandbox_assisted_package(st.session_state, room_id)
        if package is not None:
            graph = package.graph
            st.markdown(
                f"- **reflection_runtime_shop_identity_available:** "
                f"{_display(getattr(graph, 'reflection_runtime_shop_identity_available', None))}"
            )
            st.markdown(
                f"- **reflection_unnecessary_identifier_detected:** "
                f"{_display(getattr(graph, 'reflection_unnecessary_identifier_detected', None))}"
            )
            st.markdown(
                f"- **reflection_rewrite_applied:** "
                f"{_display(getattr(graph, 'reflection_rewrite_applied', None))}"
            )
        if shop_id:
            masked = f"****{shop_id[-4:]}" if len(shop_id) >= 4 else "****"
            st.markdown(f"- **shop_id_masked:** {masked}")
        seller_id = None
        for message in reversed(messages):
            if message.sender_type == "seller":
                seller_id = message.message_id
                break
        if seller_id:
            tracking_result = get_tracking_result_for_message(st.session_state, seller_id)
            if isinstance(tracking_result, dict):
                meta = tracking_result.get("auto_verification_metadata")
                if isinstance(meta, dict):
                    st.markdown("**Tracking auto-verification (manual sandbox)**")
                    st.markdown(
                        f"- **auto_verification_attempted:** "
                        f"{_display(meta.get('auto_verification_attempted'))}"
                    )
                    st.markdown(
                        f"- **carrier_candidate:** {_display(meta.get('carrier_candidate'))}"
                    )
                    st.markdown(f"- **verified:** {_display(meta.get('verified'))}")
                    st.markdown(f"- **event_count:** {_display(meta.get('event_count'))}")
                    st.markdown(f"- **error_type:** {_display(meta.get('error_type'))}")
                    extraction_dbg = meta.get("extraction_diagnostics")
                    if isinstance(extraction_dbg, dict):
                        st.markdown("**دیباگ استخراج کد رهگیری / Tracking extraction debug**")
                        for key in (
                            "original_seller_text_length",
                            "numeric_candidates_found",
                            "selected_tracking_code",
                            "selected_candidate_reason",
                            "api_code_field",
                            "payload_trace_number",
                            "payload_package_number",
                            "extraction_source_message_id",
                            "extraction_source_sender_type",
                        ):
                            if key in extraction_dbg:
                                st.markdown(
                                    f"- **{key}:** {_display(extraction_dbg.get(key))}",
                                )
                        if extraction_dbg.get("normalized_candidates"):
                            st.markdown(
                                "- **normalized_candidates:** "
                                f"{_display(extraction_dbg.get('normalized_candidates'))}",
                            )
                        rejected = extraction_dbg.get("rejected_candidates")
                        if isinstance(rejected, list) and rejected:
                            st.markdown("- **rejected_candidates:**")
                            for item in rejected:
                                if isinstance(item, dict):
                                    st.markdown(
                                        f"  - `{item.get('code', '—')}`: "
                                        f"{_display(item.get('reason'))}",
                                    )

    should_generate, skip_reason = manual_chat_should_generate_draft(messages)
    multi_should_generate: bool | None = should_generate
    multi_skip: str | None = None
    if not should_generate and skip_reason == "latest_message_from_support":
        multi_skip = _t("manual_sandbox_latest_support_skip")
    elif not should_generate:
        multi_skip = _t("manual_sandbox_no_messages")

    if settings.multi_turn_context_enabled:
        from app.workflows.multi_turn_ticket_context import build_multi_turn_context

        multi_ctx = build_multi_turn_context(snapshot, settings=settings)
        multi_should_generate = multi_ctx.should_generate_draft
        if not multi_ctx.should_generate_draft:
            multi_skip = multi_ctx.should_skip_reason or multi_skip

    def _manual_regenerate_from_details() -> object:
        regen_messages = messages_from_session(
            st.session_state.get(SESSION_MANUAL_CHAT_MESSAGES),
        )
        regen_result = regenerate_latest_ai_reply(
            regen_messages,
            room_id=room_id,
            ticket_label=explicit_label,
            shop_id=shop_id,
            session_state=st.session_state,
            settings=settings,
        )
        if regen_result.ai_message is not None:
            save_messages_to_session(st.session_state, regen_messages)
        return regen_result

    snapshot_index = {snapshot.room_id: snapshot}
    _render_ticket_detail(
        ticket,
        row_number=1,
        preview_mode="Open ticket snapshot",
        full_conversation_mode=True,
        snapshot_index=snapshot_index,
        conversation_snapshot=assisted_input_bundle.display_snapshot,
        multi_turn_should_generate_draft=multi_should_generate,
        multi_turn_skip_reason=multi_skip,
        assisted_package_getter=get_manual_sandbox_assisted_package,
        assisted_package_store=store_manual_sandbox_assisted_package,
        latest_support_skip_message=_t("manual_sandbox_latest_support_skip"),
        assisted_run_button_label=_t("manual_sandbox_regenerate_ai_reply"),
        manual_assisted_regenerate=_manual_regenerate_from_details,
        assisted_source_mode="manual_sandbox_chat",
    )


def _render_live_api_feed_panel() -> None:
    settings = get_settings()
    st.markdown(_t("live_api_feed_disclaimer"))
    default_path = Path(settings.live_feed_source_path or str(DEFAULT_LIVE_API_FEED_PATH))
    live_path = Path(
        st.sidebar.text_input(
            _t("live_feed_jsonl_path"),
            value=str(st.session_state.get(LIVE_API_FEED_PATH_SESSION_KEY, default_path)),
        ),
    )

    if st.sidebar.button(_t("live_feed_fetch_button"), key="live_api_feed_fetch"):
        with st.spinner(_t("live_feed_fetch_spinner")):
            fetch_result = handle_live_api_feed_fetch(
                st.session_state,
                feed_path=live_path,
                settings=settings,
                limit=settings.live_rooms_api_fetch_limit or DEFAULT_LIVE_ROOMS_FETCH_LIMIT,
                reload_fn=_reload_live_api_feed_entries,
            )
        if fetch_result.success:
            st.sidebar.success(
                _t("live_feed_fetch_success").format(count=fetch_result.tickets_written),
            )
            st.sidebar.metric(_t("live_feed_fetch_rooms_metric"), fetch_result.rooms_fetched)
            st.sidebar.metric(_t("live_feed_ticket_count"), fetch_result.tickets_written)
            if fetch_result.validation_passed is not None:
                validation_label = _t("live_feed_fetch_validation_metric") + (
                    " ✓" if fetch_result.validation_passed else " ✗"
                )
                st.sidebar.metric(validation_label, fetch_result.valid_rows or 0)
                if fetch_result.invalid_rows:
                    st.sidebar.metric(
                        _t("live_feed_fetch_invalid_rows_metric"),
                        fetch_result.invalid_rows,
                    )
            if fetch_result.fetch_warnings:
                st.sidebar.metric(
                    _t("live_feed_fetch_warnings_metric"),
                    len(fetch_result.fetch_warnings),
                )
        else:
            st.sidebar.error(fetch_result.error_message or _t("live_feed_fetch_failed"))

    if st.sidebar.button(_t("live_feed_reload_button"), key="live_api_feed_reload"):
        if not live_path.is_file():
            st.sidebar.error(f"{_t('live_feed_file_missing')}: {live_path}")
        else:
            try:
                _reload_live_api_feed_entries(live_path)
            except (OSError, ValueError) as exc:
                st.sidebar.error(str(exc))

    last_fetch_time = st.session_state.get(LIVE_API_FEED_LAST_FETCH_TIME_SESSION_KEY)
    if last_fetch_time:
        st.sidebar.caption(
            f"{_t('live_feed_fetch_last_time')}: "
            f"{format_iso_for_console(str(last_fetch_time), _lang())}",
        )

    entries: list[LiveFeedTicketEntry] = st.session_state.get(LIVE_API_FEED_ENTRIES_SESSION_KEY, [])
    if not entries and live_path.is_file():
        try:
            entries = _reload_live_api_feed_entries(live_path)
        except (OSError, ValueError) as exc:
            st.error(str(exc))
            return
    elif not entries and not live_path.is_file():
        st.error(f"{_t('live_feed_file_missing')}: {live_path}")
        st.caption(_t("live_feed_fetch_button"))
        return

    total = len(entries)
    eligible_count = sum(1 for entry in entries if entry.eligible)
    st.sidebar.metric(_t("live_feed_ticket_count"), total)
    st.sidebar.metric(_t("live_feed_eligible_count"), eligible_count)
    last_refresh = st.session_state.get(LIVE_API_FEED_LAST_REFRESH_SESSION_KEY)
    if last_refresh:
        st.sidebar.caption(
            f"{_t('live_feed_last_refresh')}: {format_iso_for_console(str(last_refresh), _lang())}",
        )

    filtered_entries = _render_live_feed_sidebar_filters(entries)
    st.sidebar.metric(_t("live_feed_filtered_count"), len(filtered_entries))

    if not entries:
        st.warning(_t("live_feed_no_entries"))
        return

    if not filtered_entries:
        st.info("No tickets match the current live feed filters.")
        return

    row_labels = [
        _live_feed_row_label(index, entry) for index, entry in enumerate(filtered_entries, start=1)
    ]
    select_key = "live_api_feed_select_ticket"
    selection = resolve_live_feed_list_selection(
        row_labels,
        st.session_state.get(select_key),
    )
    if selection is None:
        return
    selected_index, resolved_label = selection
    if st.session_state.get(select_key) != resolved_label:
        st.session_state[select_key] = resolved_label
    selected_label = st.selectbox(
        _t("live_feed_select_ticket"),
        row_labels,
        index=selected_index,
        key=select_key,
    )
    selected_index = row_labels.index(selected_label)
    entry = filtered_entries[selected_index]
    row_number = live_feed_detail_row_number(selected_index)

    st.markdown(f"#### {_t('live_feed_ticket_card_title')}")
    _render_live_feed_ticket_card(entry)

    preview = entry.seller_preview
    if preview:
        st.markdown(f"**{_t('live_feed_seller_preview')}**")
        st.text(preview[:400])

    _render_live_feed_metadata(entry, settings=settings)

    if entry.ticket is None:
        st.info(_skip_reason_display(entry.skip_reason))
        return

    try:
        ticket = operator_ticket_from_live_ticket(entry.ticket)
    except ValueError as exc:
        st.error(str(exc))
        return

    full_conversation_mode = st.sidebar.checkbox(
        "Full conversation mode",
        value=True,
        help="Show full thread from live feed JSONL (local/private dev).",
    )
    snapshot_index = _get_conversation_snapshot_index(live_path) if full_conversation_mode else {}
    snapshot = entry.ticket.snapshot if entry.ticket is not None else None
    multi_should_generate: bool | None = None
    multi_skip: str | None = None
    if settings.multi_turn_context_enabled and snapshot is not None:
        from app.workflows.multi_turn_ticket_context import build_multi_turn_context

        multi_ctx = build_multi_turn_context(snapshot, settings=settings)
        multi_should_generate = multi_ctx.should_generate_draft
        multi_skip = multi_ctx.should_skip_reason
    _render_ticket_detail(
        ticket,
        row_number=row_number,
        preview_mode="Open ticket snapshot",
        full_conversation_mode=full_conversation_mode,
        snapshot_index=snapshot_index,
        conversation_snapshot=snapshot,
        multi_turn_should_generate_draft=multi_should_generate,
        multi_turn_skip_reason=multi_skip,
        assisted_source_mode="live_api_feed",
    )


def _render_feedback_sidebar_summary() -> None:
    summary = load_operator_feedback_summary()
    st.sidebar.markdown("---")
    st.sidebar.markdown("**Feedback log**")
    st.sidebar.metric("Total rows", summary.total_count)
    st.sidebar.metric("Helpful", summary.helpful_count)
    st.sidebar.metric("Noisy / wrong / follow-up", summary.noisy_wrong_count)


def _render_ticket_browser(
    tickets: list[OperatorTicket],
    *,
    data_mode: str,
    conversation_source_path: str,
    first_vendor_snapshot_path: str | None = None,
) -> None:
    settings = get_settings()
    filter_snapshot_path = first_vendor_snapshot_path or conversation_source_path
    snapshot_index = _get_conversation_snapshot_index(filter_snapshot_path)
    tickets, first_vendor_stats = apply_operator_first_vendor_filter(
        tickets,
        snapshot_index=snapshot_index,
        enabled=settings.operator_first_vendor_only,
    )
    if first_vendor_stats.filter_active and not snapshot_index:
        st.sidebar.warning(
            "First-vendor filter is on but redacted tickets JSONL was not found or is empty. "
            "No tickets will match until snapshots are loaded.",
        )
    elif (
        first_vendor_stats.filter_active
        and first_vendor_stats.tickets_shown == 0
        and first_vendor_stats.total_loaded > 0
    ):
        st.sidebar.warning(
            "No seller-initiated rooms in the loaded set (or missing room_id in redacted JSONL).",
        )

    _render_first_vendor_filter_sidebar(first_vendor_stats)
    _render_feedback_sidebar_summary()
    _render_draft_review_sidebar_summary()
    _render_agentic_preview_review_sidebar_summary()
    full_conversation_mode = st.sidebar.checkbox(
        "Full conversation mode",
        value=True,
        help="Show redacted full thread (operator console only).",
    )
    compact_preview_mode = st.sidebar.checkbox(
        "Compact preview mode",
        value=False,
        help="Use truncated HITL-safe snapshot fields instead of full thread.",
    )
    if compact_preview_mode:
        full_conversation_mode = False
    preview_mode = "Open ticket snapshot"
    if not full_conversation_mode:
        preview_mode = st.sidebar.radio(
            "Compact preview type",
            ["Open ticket snapshot", "Historical preview"],
            index=0,
        )
    snapshot_index = (
        _get_conversation_snapshot_index(conversation_source_path) if full_conversation_mode else {}
    )
    display_limit_label = st.sidebar.selectbox(
        "Max tickets to display",
        OPERATOR_CONSOLE_DISPLAY_LIMIT_LABELS,
        index=OPERATOR_CONSOLE_DISPLAY_LIMIT_LABELS.index(
            DEFAULT_OPERATOR_CONSOLE_DISPLAY_LIMIT_LABEL,
        ),
    )
    st.sidebar.caption(
        f"Showing {len(tickets)} tickets after first-vendor filter "
        f"({first_vendor_stats.total_loaded} loaded from replay).",
    )

    labels = distinct_ticket_labels(tickets)
    actions = distinct_suggested_actions(tickets)
    label_filter = st.sidebar.selectbox("ticket_label", ["(all)"] + labels)
    action_filter = st.sidebar.selectbox("suggested_action", ["(all)"] + actions)
    escalation_only = st.sidebar.checkbox("Escalation only")
    duplicate_only = st.sidebar.checkbox("Duplicate only")

    filtered = filter_operator_tickets(
        tickets,
        ticket_label=None if label_filter == "(all)" else label_filter,
        suggested_action=None if action_filter == "(all)" else action_filter,
        escalation_only=escalation_only,
        duplicate_only=duplicate_only,
    )
    display_limit = parse_operator_console_display_limit(display_limit_label)
    displayed = apply_operator_console_display_limit(filtered, limit=display_limit)

    if len(displayed) < len(filtered):
        st.caption(f"Showing {len(displayed)} of {len(filtered)} tickets matching filters.")

    _render_metrics_header(displayed)

    if not displayed:
        st.info("No tickets match the current filters.")
        st.stop()

    row_labels = [
        ticket_row_display_label(index, ticket) for index, ticket in enumerate(displayed, start=1)
    ]
    selected_label = st.selectbox(_t("select_ticket"), row_labels)
    selected_index = row_labels.index(selected_label) + 1
    selected = displayed[selected_index - 1]
    _render_ticket_detail(
        selected,
        row_number=selected_index,
        preview_mode=preview_mode,
        full_conversation_mode=full_conversation_mode,
        snapshot_index=snapshot_index,
    )


def main() -> None:
    st.set_page_config(page_title="Inchand Operator Console", layout="wide")
    _render_console_language_selector()
    css = apply_console_direction_css(_lang())
    if css:
        st.markdown(css, unsafe_allow_html=True)

    st.title(_t("page_title"))
    st.markdown(_t("page_disclaimer"))
    if is_live_shadow_intake_recently_active():
        st.caption("Live shadow intake active (read-only first-turn evaluation).")

    settings = get_settings()
    current_source = _init_console_data_source()
    source_values = [value for value, _ in _DATA_SOURCE_OPTIONS]
    source_index = source_values.index(current_source) if current_source in source_values else 0
    selected_source = st.sidebar.radio(
        _t("sidebar_data_source"),
        options=source_values,
        format_func=_data_source_label,
        index=source_index,
        horizontal=True,
        key="operator_console_data_source_radio",
    )
    st.session_state[CONSOLE_DATA_SOURCE_SESSION_KEY] = selected_source

    if selected_source == SOURCE_LIVE_API_FEED:
        _render_live_api_feed_panel()
        return

    if selected_source == SOURCE_MANUAL_SANDBOX_CHAT:
        _render_manual_sandbox_chat_panel()
        return

    default_path = DEFAULT_REPLAY_PATH
    replay_path = st.sidebar.text_input(
        "Replay JSONL path",
        value=str(default_path),
    )
    conversation_path = st.sidebar.text_input(
        "Redacted tickets JSONL (full conversation)",
        value=str(DEFAULT_REDACTED_TICKETS_PATH),
    )
    if settings.operator_draft_preview_enabled:
        st.sidebar.text_input(
            "Offline draft suggestions JSONL",
            value=settings.operator_draft_suggestions_path,
            key="operator_draft_suggestions_path",
            help="Internal preview only (e.g. first-turn offline drafts).",
        )
    path = Path(replay_path)
    if not path.is_file():
        st.error(f"Replay file not found: {path}")
        st.stop()

    try:
        tickets = load_operator_tickets(path)
    except ValueError as exc:
        st.error(f"Failed to load tickets: {exc}")
        st.stop()

    if not tickets:
        st.warning("No tickets in replay file.")
        st.stop()

    _render_ticket_browser(
        tickets,
        data_mode="Historical replay",
        conversation_source_path=conversation_path,
        first_vendor_snapshot_path=conversation_path,
    )


if __name__ == "__main__":
    main()
