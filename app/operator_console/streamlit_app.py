"""Internal operator console (Streamlit) — local review of AI assist + retrieval summaries."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

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
from app.live_feed.ticket_polling import load_recent_operator_payloads, poll_live_ticket_feed
from app.live_shadow.live_first_turn_shadow_intake import is_live_shadow_intake_recently_active
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
    operator_tickets_from_hitl_payloads,
    parse_operator_console_display_limit,
)
from app.operator_console.console_models import (
    OperatorTicket,
    compute_console_metrics,
    ticket_row_display_label,
)
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
from app.operator_console.rtl_text import format_context_lines, render_rtl_text_block
from app.tickets.conversation_models import ConversationTicketSnapshot

_DISCLAIMER = (
    "**Internal operator console (local only).** Aggregate metadata plus optional "
    "**full conversation mode** (redacted, sandbox-only). No customer responses, no auto-send, "
    "no retrieval hit bodies, no vectors. HITL exports/reports keep truncated safe previews. "
    "Optional **Submit feedback** writes append-only rows to `reports/operator_feedback.jsonl` "
    "(aggregate labels + note only; not used for training or AI assist)."
)
_LIVE_DISCLAIMER = (
    "**Live feed mode:** read-only JSONL polling. No production DB writes, no auto-routing, "
    "no customer replies. Enable shadow flags locally for routing/retrieval/assist processing."
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


def _render_operator_agentic_assisted_mode(ticket: OperatorTicket) -> None:
    settings = get_settings()
    if not settings.operator_agentic_assisted_mode_enabled:
        return

    st.markdown(f"#### {_t('operator_assisted_mode')}")
    st.caption(_t("operator_assisted_caption"))

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

    run_label = _t("refresh_assisted_package")
    existing = get_session_agentic_assisted_package(st.session_state, ticket.room_id)
    if existing is None:
        run_label = _t("run_assisted_package")

    if st.button(run_label, key=f"agentic_assisted_run_{ticket.room_id}"):
        try:
            package = build_agentic_assisted_package(ticket, settings=settings)
        except ValueError as exc:
            st.error(f"Assisted package failed safety checks: {exc}")
        except (OSError, RuntimeError) as exc:
            st.error(f"Assisted package failed: {exc}")
        else:
            store_session_agentic_assisted_package(st.session_state, package)
            st.success(_t("assisted_package_ready"))

    package = get_session_agentic_assisted_package(st.session_state, ticket.room_id)
    if package is None:
        st.info(_t("no_assisted_package"))
        return

    render_operator_assisted_work_package(
        st,
        package,
        ticket,
        lang=_lang(),
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
) -> None:
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
    _render_operator_agentic_assisted_mode(ticket)
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


def _load_live_tickets(*, source_path: str, use_checkpoint: bool) -> list[OperatorTicket]:
    settings = get_settings()
    try:
        if use_checkpoint:
            batch = poll_live_ticket_feed(settings=settings, source_path=source_path)
        else:
            batch = load_recent_operator_payloads(settings=settings, source_path=source_path)
    except ValueError as exc:
        st.error(str(exc))
        return []
    tickets = operator_tickets_from_hitl_payloads(batch.operator_payloads)
    tickets.sort(key=lambda item: item.room_id, reverse=True)
    st.caption(
        f"Live batch: {batch.new_count} new / {batch.fetched_count} fetched "
        f"(source: {settings.live_feed_source_path})"
    )
    return tickets


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
    if data_mode == "Live":
        settings = get_settings()
        st.sidebar.caption(
            f"Live polling batch size: {settings.live_feed_max_batch} "
            "(LIVE_FEED_MAX_BATCH). Display limit applies after load."
        )
    else:
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
    mode_options = ["Replay"]
    if settings.live_feed_enabled:
        mode_options.append("Live")
    data_mode = st.sidebar.radio(_t("sidebar_data_source"), mode_options, horizontal=True)

    if data_mode == "Live":
        st.markdown(_LIVE_DISCLAIMER)
        live_path = st.sidebar.text_input(
            "Live feed JSONL",
            value=settings.live_feed_source_path,
        )
        use_checkpoint = st.sidebar.checkbox("Incremental checkpoint", value=True)
        poll_seconds = st.sidebar.number_input(
            "Auto-refresh (seconds)",
            min_value=settings.live_feed_poll_interval_seconds,
            value=settings.live_feed_poll_interval_seconds,
            step=5,
        )
        if st.sidebar.button("Refresh now"):
            st.session_state["live_refresh_nonce"] = (
                st.session_state.get("live_refresh_nonce", 0) + 1
            )

        @st.fragment(run_every=timedelta(seconds=int(poll_seconds)))
        def _live_panel() -> None:
            _ = st.session_state.get("live_refresh_nonce", 0)
            path = Path(live_path)
            if not path.is_file():
                st.error(f"Live feed file not found: {path}")
                return
            tickets = _load_live_tickets(
                source_path=live_path,
                use_checkpoint=use_checkpoint,
            )
            if not tickets:
                st.warning("No new tickets in live feed.")
                return
            _render_ticket_browser(
                tickets,
                data_mode="Live",
                conversation_source_path=live_path,
                first_vendor_snapshot_path=str(DEFAULT_REDACTED_TICKETS_PATH),
            )

        _live_panel()
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
        data_mode="Replay",
        conversation_source_path=conversation_path,
        first_vendor_snapshot_path=conversation_path,
    )


if __name__ == "__main__":
    main()
