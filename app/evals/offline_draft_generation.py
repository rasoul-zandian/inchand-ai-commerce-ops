"""Offline internal draft reply suggestions for historical benchmark cases (evaluation only)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.evals.actionability_validation import (
    actionability_metadata_row,
    apply_actionability_to_draft,
    build_actionability_prompt_instruction,
    validate_actionability,
)
from app.evals.conceptual_intent_fa import (
    draft_generation_json_instruction,
    generate_draft_with_conceptual_intent,
    operational_intent_prompt_block,
)
from app.evals.draft_completion_calibration import (
    apply_draft_completion_calibration,
    completion_calibration_metadata_row,
)
from app.evals.draft_evidence_wording_calibration import calibrate_photo_evidence_wording
from app.evals.draft_generation_mode import (
    DEFAULT_DRAFT_GENERATION_MODE,
    DraftGenerationMode,
    parse_draft_generation_mode,
)
from app.evals.draft_policy_grounding_calibration import apply_policy_grounding_calibration
from app.evals.draft_prompt_leakage import (
    assert_prompt_messages_safe,
    build_prompt_audit_record,
    extract_forbidden_values_from_benchmark_case,
    list_included_prompt_fields,
    safe_snapshot_before_reply,
    write_prompt_audit_jsonl,
)
from app.evals.draft_style import (
    apply_draft_style_checks,
    draft_style_metadata_row,
    merge_style_and_completion_instructions,
    resolve_effective_draft_style,
    resolve_effective_draft_style_limits,
)
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    FirstTurnDraftContext,
    build_first_turn_draft_context_from_case,
    first_turn_text_from_case,
)
from app.hitl.ticket_text_preview import _contains_unredacted_pii
from app.knowledge.knowledge_models import KnowledgeDocumentType
from app.knowledge.policy_fact_extraction import build_policy_facts_prompt_block
from app.llm.types import LLMMessage
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import (
    KnowledgeHint,
    KnowledgeRetrievalFn,
    fetch_knowledge_hints_for_ticket,
)
from app.workflows.seller_notification_detection import normalize_persian_arabic_digits
from app.workflows.suggested_action_taxonomy import map_intent_to_suggested_action
from app.workflows.vendor_ticket_intent_detection import (
    VendorTicketIntent,
    detect_vendor_ticket_intent,
)

DRAFT_MAX_CHARS = 700

_FORBIDDEN_DRAFT_MARKERS = (
    "sk-",
    "openai_api_key",
    "begin private key",
    "postgresql://",
    '"messages"',
    "conversation transcript",
    "gold_reference_reply",
)

_AUTO_SEND_MARKERS = (
    "auto-send",
    "automatically send",
    "به صورت خودکار ارسال",
    "ارسال خودکار",
    "بدون تایید اپراتور ارسال",
)

_INTERNAL_DOC_TYPE_NAMES = frozenset(document_type.value for document_type in KnowledgeDocumentType)

_LLMGenerateFn = Callable[..., Any]


@dataclass
class OfflineDraftGenerationStats:
    """Aggregate counts for ``offline_draft_suggestions_summary.json``."""

    total_cases: int = 0
    drafts_generated: int = 0
    drafts_failed: int = 0
    failure_reasons: dict[str, int] = field(default_factory=dict)
    cases_by_intent: dict[str, int] = field(default_factory=dict)
    cases_with_policy_hints: int = 0
    source_path: str = ""
    output_jsonl_path: str = ""
    output_summary_path: str = ""
    generated_at_utc: str = ""
    llm_provider: str = ""
    llm_model: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "drafts_generated": self.drafts_generated,
            "drafts_failed": self.drafts_failed,
            "failure_reasons": dict(sorted(self.failure_reasons.items())),
            "cases_by_intent": dict(sorted(self.cases_by_intent.items())),
            "cases_with_policy_hints": self.cases_with_policy_hints,
            "source_path": self.source_path,
            "output_jsonl_path": self.output_jsonl_path,
            "output_summary_path": self.output_summary_path,
            "generated_at_utc": self.generated_at_utc,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
        }


def gold_reference_reply_hash(gold_text: str) -> str:
    """SHA-256 hex digest for benchmark gold reply (output never includes full gold text)."""
    normalized = gold_text.strip().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def resolve_draft_generation_mode(settings: AppSettings | None = None) -> DraftGenerationMode:
    """Resolve draft mode from settings (defaults to first-turn isolation)."""
    cfg = settings or get_settings()
    return parse_draft_generation_mode(cfg.draft_generation_mode)


def _snapshot_text(
    case: Mapping[str, Any],
    *,
    mode: DraftGenerationMode = DEFAULT_DRAFT_GENERATION_MODE,
) -> str:
    """Text used for intent detection before draft prompt assembly."""
    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        return first_turn_text_from_case(case)
    snap = safe_snapshot_before_reply(case.get("snapshot_before_reply"), mode=mode)  # type: ignore[arg-type]
    parts: list[str] = []
    for value in snap.values():
        if value:
            parts.append(value)
    return " ".join(parts)


def _thread_texts_from_case(case: Mapping[str, Any]) -> list[str]:
    """Later-thread preview fields that must not drive first-turn drafts."""
    texts: list[str] = []
    snap = case.get("snapshot_before_reply")
    if isinstance(snap, Mapping):
        for key in ("latest_vendor_message", "recent_context_preview"):
            raw = snap.get(key)
            if isinstance(raw, str) and raw.strip():
                texts.append(raw.strip())
    for key in ("open_ticket_preview", "ticket_text_preview"):
        raw = case.get(key)
        if isinstance(raw, str) and raw.strip():
            texts.append(raw.strip())
    return texts


def _seller_context_lines(case: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    seller_intent = case.get("seller_intent_type")
    if seller_intent:
        lines.append(f"- نوع پیام فروشنده: {seller_intent}")
    request_type = case.get("seller_operational_request_type")
    if request_type:
        lines.append(f"- نوع درخواست عملیاتی: {request_type}")
    return lines


def _operator_ticket_from_case(
    case: Mapping[str, Any],
    *,
    intent_result: Any,
) -> OperatorTicket:
    snap = case.get("snapshot_before_reply")
    if not isinstance(snap, dict):
        snap = {}
    order_ids_csv = (
        ",".join(intent_result.extracted_order_ids) if intent_result.extracted_order_ids else None
    )
    return OperatorTicket(
        room_id=str(case.get("room_id") or ""),
        ticket_label=_optional_str(case.get("ticket_label")),
        route_label=_optional_str(case.get("route_label")),
        assigned_department=None,
        review_priority=None,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=None,
        open_ticket_preview=None,
        original_vendor_issue_preview=_optional_str(snap.get("original_vendor_issue_preview")),
        latest_vendor_message=_optional_str(snap.get("latest_vendor_message")),
        recent_context_preview=_optional_str(snap.get("recent_context_preview")),
        extracted_order_id=(
            intent_result.extracted_order_ids[0] if intent_result.extracted_order_ids else None
        ),
        extracted_order_ids=order_ids_csv,
        extracted_tracking_code=intent_result.extracted_tracking_code,
        extracted_product_ids=(
            ",".join(intent_result.extracted_product_ids)
            if getattr(intent_result, "extracted_product_ids", None)
            else None
        ),
        extracted_tracking_carrier=getattr(intent_result, "extracted_tracking_carrier", None),
        entity_warnings_summary=getattr(intent_result, "entity_warnings_summary", None),
        detected_intent=intent_result.detected_intent,
    )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_policy_hints_for_prompt(
    hints: Sequence[KnowledgeHint],
    *,
    detected_intent: str | None = None,
    suggested_action: str | None = None,
    seller_text: str = "",
) -> str:
    if not hints:
        return "(هیچ متن سیاست رسمی بازیابی نشد — در صورت نیاز از اپراتور تأیید بگیرید.)"
    facts_block = build_policy_facts_prompt_block(
        detected_intent=detected_intent,
        suggested_action=suggested_action,
        seller_text=seller_text,
        document_types=tuple(hint.document_type for hint in hints),
        hints=hints,
    )
    if facts_block:
        return (
            facts_block + "\n\nاز این حقایق مستقیم استفاده کن؛ زمان‌بندی دیگری اختراع نکن؛ "
            "اگر پاسخ در همین حقایق هست به قوانین/راهنما ارجاع نده."
        )
    return "(هیچ متن سیاست رسمی بازیابی نشد — در صورت نیاز از اپراتور تأیید بگیرید.)"


def build_offline_draft_messages(
    case: Mapping[str, Any],
    *,
    intent_result: Any,
    suggested_action: str,
    policy_hints: Sequence[KnowledgeHint],
    mode: DraftGenerationMode = DEFAULT_DRAFT_GENERATION_MODE,
    first_turn_context: FirstTurnDraftContext | None = None,
    settings: AppSettings | None = None,
) -> list[LLMMessage]:
    """Build LLM messages for an offline draft (mode-gated; no gold/future replies)."""
    cfg = settings or get_settings()
    if mode == DraftGenerationMode.FIRST_TURN_ONLY and first_turn_context is None:
        first_turn_context = build_first_turn_draft_context_from_case(case, settings=cfg)
    if mode == DraftGenerationMode.FIRST_TURN_ONLY and first_turn_context is not None:
        intent_result = first_turn_context.first_turn_intent
        suggested_action = first_turn_context.suggested_action
        if not policy_hints:
            policy_hints = first_turn_context.first_turn_policy_hints

    snap = safe_snapshot_before_reply(case.get("snapshot_before_reply"), mode=mode)  # type: ignore[arg-type]
    first_turn_text = (
        first_turn_context.first_turn_text
        if first_turn_context is not None
        else (snap.get("original_vendor_issue_preview") or "")
    )
    policy_block = _format_policy_hints_for_prompt(
        policy_hints,
        detected_intent=intent_result.detected_intent,
        suggested_action=suggested_action,
        seller_text=first_turn_text,
    )
    entities_lines: list[str] = []
    if intent_result.extracted_order_ids:
        entities_lines.append(
            "شناسه سفارش (تجمیعی، بدون تأیید سیستم): "
            + ", ".join(intent_result.extracted_order_ids),
        )
    product_ids = getattr(intent_result, "extracted_product_ids", None) or []
    if product_ids:
        entities_lines.append(
            "شناسه کالا (تجمیعی، بدون تأیید سیستم): " + ", ".join(product_ids),
        )
    if intent_result.extracted_tracking_code:
        carrier = getattr(intent_result, "extracted_tracking_carrier", None) or "نامشخص"
        entities_lines.append(
            f"کد رهگیری (تجمیعی، بدون تأیید): {intent_result.extracted_tracking_code} "
            f"(حامل: {carrier})",
        )
    warnings = getattr(intent_result, "entity_warnings_summary", None)
    if warnings:
        entities_lines.append(f"هشدار استخراج موجودیت: {warnings}")
    entities_block = "\n".join(entities_lines) if entities_lines else "(ندارد)"
    seller_lines = _seller_context_lines(case)
    seller_block = "\n".join(seller_lines) + ("\n" if seller_lines else "")
    operational_block = operational_intent_prompt_block(first_turn_text)
    seller_text_for_validation = (
        first_turn_text
        if mode == DraftGenerationMode.FIRST_TURN_ONLY
        else " ".join(
            part
            for part in (
                snap.get("original_vendor_issue_preview"),
                snap.get("latest_vendor_message"),
            )
            if part
        )
    )
    actionability = validate_actionability(
        suggested_action=suggested_action,
        entities=intent_result,
        seller_text=seller_text_for_validation or "",
        detected_intent=intent_result.detected_intent,
    )
    actionability_block = build_actionability_prompt_instruction(actionability)

    style_name, _max_sent, _target, _hard = resolve_effective_draft_style_limits(
        cfg,
        seller_text=seller_text_for_validation or first_turn_text or "",
        detected_intent=intent_result.detected_intent,
        suggested_action=suggested_action,
    )
    style_instruction = merge_style_and_completion_instructions(
        style_name,
        max_sentences=_max_sent,
        target_max_chars=_target,
    )
    draft_user_verb = (
        "یک پیش‌نویس پاسخ فارسی شفاف برای اولین پاسخ پشتیبانی بنویس."
        if style_name == "policy_explanation"
        else "یک پیش‌نویس پاسخ فارسی کوتاه برای اولین پاسخ پشتیبانی بنویس."
    )

    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        user_body = (
            "متن درخواست اولیه فروشنده (فقط موضوع اولیه — بدون ادامه گفتگو یا پاسخ پشتیبانی):\n"
            f"- {first_turn_text or '—'}\n\n"
            f"{operational_block}"
            f"برچسب مسیر: ticket_label={case.get('ticket_label')!s}, "
            f"route_label={case.get('route_label')!s}\n"
            f"{seller_block}"
            f"قصد عملیاتی تشخیص‌داده‌شده: {intent_result.detected_intent}\n"
            f"پیشنهاد اقدام داخلی (برای اپراتور): {suggested_action}\n"
            f"موجودیت‌های استخراج‌شده:\n{entities_block}\n\n"
            "متن‌های راهنمای سیاست (فقط برای راهنمایی — "
            "نام فایل/داخلی را در پاسخ به فروشنده ننویس):\n"
            f"{policy_block}\n\n"
            f"{draft_user_verb}"
        )
        entity_source_note = (
            f"منبع موجودیت‌ها: {ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE} "
            "(استخراج فقط از پیام اول — بدون تأیید سیستم).\n"
        )
        user_body = entity_source_note + user_body
    else:
        vendor_issue = " ".join(
            part
            for part in (
                snap.get("original_vendor_issue_preview"),
                snap.get("latest_vendor_message"),
            )
            if part
        )
        operational_block = operational_intent_prompt_block(vendor_issue)
        user_body = (
            "متن تیکت فروشنده (بخش‌های امن و خلاصه‌شده):\n"
            f"- موضوع اولیه: {snap.get('original_vendor_issue_preview') or '—'}\n"
            f"- آخرین پیام فروشنده: {snap.get('latest_vendor_message') or '—'}\n"
            f"- زمینه اخیر: {snap.get('recent_context_preview') or '—'}\n\n"
            f"{operational_block}"
            f"برچسب مسیر: ticket_label={case.get('ticket_label')!s}, "
            f"route_label={case.get('route_label')!s}\n"
            f"{seller_block}"
            f"قصد عملیاتی تشخیص‌داده‌شده: {intent_result.detected_intent}\n"
            f"پیشنهاد اقدام داخلی (برای اپراتور): {suggested_action}\n"
            f"موجودیت‌های استخراج‌شده:\n{entities_block}\n\n"
            "متن‌های راهنمای سیاست (فقط برای راهنمایی — "
            "نام فایل/داخلی را در پاسخ به فروشنده ننویس):\n"
            f"{policy_block}\n\n"
            "یک پیش‌نویس پاسخ فارسی کوتاه برای بررسی اپراتور بنویس."
        )

    system = (
        "شما برای تیم پشتیبانی داخلی اینچند پیش‌نویس پاسخ می‌نویسید. "
        "این متن هرگز به‌صورت خودکار برای فروشنده ارسال نمی‌شود.\n"
        "قوانین:\n"
        "- لحن رسمی و محترمانه به فارسی؛ مختصر (حداکثر حدود ۶۰۰ کاراکتر).\n"
        "- تاریخ، مبلغ، وضعیت سفارش یا وعده قطعی اختراع نکن.\n"
        "- اگر سیاست کافی نیست، از فروشنده بخواه صبر کند و بگو اپراتور بررسی می‌کند.\n"
        "- نام chunk، settlement_rules، یا اصطلاحات فنی داخلی بازیابی را به فروشنده نگو.\n"
        "- از عبارات «ارسال شد»، «به‌صورت خودکار»، یا وعده ارسال بدون بازبینی انسانی پرهیز کن.\n"
        f"{actionability_block}"
        f"{style_instruction}\n"
        f"{draft_generation_json_instruction()}"
    )

    messages = [
        LLMMessage(role="system", content=system),
        LLMMessage(role="user", content=user_body),
    ]
    forbidden = extract_forbidden_values_from_benchmark_case(case, mode=mode)
    first_turn_for_entity_check = (
        first_turn_context.first_turn_text
        if first_turn_context is not None
        else first_turn_text_from_case(case)
    )
    assert_prompt_messages_safe(
        messages,
        forbidden_values=forbidden,
        mode=mode,
        first_turn_text=first_turn_for_entity_check
        if mode == DraftGenerationMode.FIRST_TURN_ONLY
        else None,
        thread_texts=_thread_texts_from_case(case)
        if mode == DraftGenerationMode.FIRST_TURN_ONLY
        else None,
    )
    return messages


def assert_prompt_excludes_gold_reference(
    messages: Sequence[LLMMessage],
    gold_reference_reply: str,
) -> None:
    """Fail closed if prompt may leak the benchmark gold human reply."""
    gold = gold_reference_reply.strip()
    if not gold:
        assert_prompt_messages_safe(messages, forbidden_values=[])
        return
    assert_prompt_messages_safe(messages, forbidden_values=[gold])


def assert_draft_reply_safe(draft: str, *, max_chars: int = DRAFT_MAX_CHARS) -> None:
    """Reject drafts that may expose PII, internals, or auto-send language."""
    text = draft.strip()
    if not text:
        raise ValueError("draft_reply must be non-empty")
    if len(text) > max_chars:
        raise ValueError(f"draft_reply exceeds max length {max_chars}")
    lowered = text.lower()
    for marker in _FORBIDDEN_DRAFT_MARKERS:
        if marker in lowered:
            raise ValueError(f"draft_reply contains forbidden marker: {marker}")
    for marker in _AUTO_SEND_MARKERS:
        if marker in lowered:
            raise ValueError(f"draft_reply contains auto-send language: {marker}")
    for doc_type in _INTERNAL_DOC_TYPE_NAMES:
        if doc_type in lowered:
            raise ValueError(f"draft_reply must not mention internal document type: {doc_type}")
    if _contains_unredacted_pii(text):
        raise ValueError("draft_reply contains unredacted PII-like patterns")


def _truncate_draft(text: str, *, max_chars: int = DRAFT_MAX_CHARS) -> str:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 1].rstrip() + "…"


def generate_draft_reply(
    messages: list[LLMMessage],
    *,
    provider: str,
    model: str,
    generate_fn: _LLMGenerateFn | None = None,
    max_chars: int = DRAFT_MAX_CHARS,
    detected_intent: str = "general_vendor_support",
) -> str:
    """Call LLM and return a sanitized draft string (legacy; prefer structured helper)."""
    result = generate_draft_with_conceptual_intent(
        messages,
        detected_intent=detected_intent,
        provider=provider,
        model=model,
        generate_fn=generate_fn,
        max_chars=max_chars,
    )
    return result.draft_reply


def resolve_suggested_action(
    intent: VendorTicketIntent,
    *,
    normalized_text: str,
    entities: Any | None = None,
    conceptual_intent_fa: str | None = None,
    ticket_label: str | None = None,
    route_label: str | None = None,
) -> str:
    return map_intent_to_suggested_action(
        intent,
        conceptual_intent_fa=conceptual_intent_fa,
        entities=entities,
        normalized_text=normalized_text,
        ticket_label=ticket_label,
        route_label=route_label,
    ).action.value


def process_benchmark_case(
    case: Mapping[str, Any],
    *,
    settings: AppSettings,
    provider: str,
    model: str,
    generate_fn: _LLMGenerateFn | None = None,
    retrieve_fn: KnowledgeRetrievalFn | None = None,
    query_embedding_fn: Callable[[str], list[float]] | None = None,
    store: Any | None = None,
    collect_prompt_audit: bool = False,
) -> dict[str, Any]:
    """Produce one output row for ``offline_draft_suggestions_v1.jsonl``."""
    case_id = str(case.get("case_id") or "")
    room_id = str(case.get("room_id") or "")
    ticket_label = case.get("ticket_label")
    route_label = case.get("route_label")
    gold = case.get("gold_reference_reply")
    gold_hash = (
        gold_reference_reply_hash(str(gold)) if isinstance(gold, str) and gold.strip() else None
    )

    base_row: dict[str, Any] = {
        "case_id": case_id,
        "room_id": room_id,
        "ticket_label": ticket_label,
        "route_label": route_label,
        "detected_intent": None,
        "conceptual_intent_fa": None,
        "suggested_action": None,
        "suggested_action_reason": None,
        "draft_reply": None,
        "knowledge_hint_document_types": [],
        "draft_generated": False,
        "error_reason": None,
        "gold_reference_reply_hash": gold_hash,
    }

    try:
        draft_mode = resolve_draft_generation_mode(settings)
        first_turn_ctx: FirstTurnDraftContext | None = None
        if draft_mode == DraftGenerationMode.FIRST_TURN_ONLY:
            first_turn_ctx = build_first_turn_draft_context_from_case(
                case,
                settings=settings,
                store=store,
                query_embedding_fn=query_embedding_fn,
                retrieve_fn=retrieve_fn,
            )
            intent_result = first_turn_ctx.first_turn_intent
            suggested_action = first_turn_ctx.suggested_action
            base_row["suggested_action_reason"] = first_turn_ctx.suggested_action_reason
            hints = first_turn_ctx.first_turn_policy_hints
            source_text = first_turn_ctx.first_turn_text
            hint_error = None
            base_row["entity_source"] = first_turn_ctx.entity_source
        else:
            source_text = _snapshot_text(case, mode=draft_mode)
            intent_result = detect_vendor_ticket_intent(
                source_text,
                ticket_label=str(ticket_label) if ticket_label is not None else None,
                route_label=str(route_label) if route_label is not None else None,
            )
            normalized = normalize_persian_arabic_digits(source_text) if source_text else ""
            intent = intent_result.intent
            action_mapping = map_intent_to_suggested_action(
                intent,
                entities=intent_result,
                normalized_text=normalized,
                ticket_label=str(ticket_label) if ticket_label is not None else None,
                route_label=str(route_label) if route_label is not None else None,
            )
            suggested_action = action_mapping.action.value
            base_row["suggested_action_reason"] = action_mapping.reason
            hints = ()
            hint_error = None
            if settings.knowledge_hints_enabled:
                try:
                    ticket = _operator_ticket_from_case(case, intent_result=intent_result)
                    hints = fetch_knowledge_hints_for_ticket(
                        ticket,
                        settings=settings,
                        store=store,
                        query_embedding_fn=query_embedding_fn,
                        retrieve_fn=retrieve_fn,
                    )
                except Exception as exc:  # noqa: BLE001
                    hint_error = f"knowledge_hints_failed: {exc}"

        intent = intent_result.intent
        base_row["detected_intent"] = intent.value
        base_row["suggested_action"] = suggested_action

        messages = build_offline_draft_messages(
            case,
            intent_result=intent_result,
            suggested_action=suggested_action,
            policy_hints=hints,
            mode=draft_mode,
            first_turn_context=first_turn_ctx,
            settings=settings,
        )
        if collect_prompt_audit:
            base_row["_prompt_audit"] = build_prompt_audit_record(
                case_id=case_id,
                messages=messages,
                included_fields=list_included_prompt_fields(
                    case,
                    intent_result=intent_result,
                    suggested_action=suggested_action,
                    policy_hints=hints,
                    mode=draft_mode,
                ),
                case=case,
                mode=draft_mode,
            )

        seller_for_calibration = source_text or first_turn_text_from_case(case)
        _style, _max_sent, _target, hard_max = resolve_effective_draft_style_limits(
            settings,
            seller_text=seller_for_calibration or "",
            detected_intent=intent.value,
            suggested_action=suggested_action,
        )
        draft_max = min(DRAFT_MAX_CHARS, hard_max)
        draft_result = generate_draft_with_conceptual_intent(
            messages,
            detected_intent=intent.value,
            provider=provider,
            model=model,
            generate_fn=generate_fn,
            source_text=source_text,
            max_chars=draft_max,
        )
        assert_draft_reply_safe(draft_result.draft_reply, max_chars=draft_max)
        completion = apply_draft_completion_calibration(
            draft_result.draft_reply,
            seller_text=seller_for_calibration,
            suggested_action=suggested_action,
            detected_intent=intent.value,
            entity_warnings_summary=getattr(intent_result, "entity_warnings_summary", None),
        )
        calibrated_draft = completion.draft_reply
        actionability = validate_actionability(
            suggested_action=suggested_action,
            entities=intent_result,
            seller_text=seller_for_calibration or "",
            detected_intent=intent.value,
        )
        calibrated_draft, actionability = apply_actionability_to_draft(
            calibrated_draft,
            actionability,
            seller_text=seller_for_calibration or "",
        )
        calibrated_draft, _photo_calibrated, _unnecessary_photo = calibrate_photo_evidence_wording(
            calibrated_draft,
            seller_text=seller_for_calibration or "",
            detected_intent=intent.value,
            suggested_action=suggested_action,
            missing_entities=actionability.missing_required_entities,
            product_ids=tuple(getattr(intent_result, "extracted_product_ids", None) or ()),
        )
        effective_style = resolve_effective_draft_style(
            seller_text=seller_for_calibration or "",
            detected_intent=intent.value,
            suggested_action=suggested_action,
        )
        grounding = apply_policy_grounding_calibration(
            calibrated_draft,
            seller_text=seller_for_calibration or "",
            detected_intent=intent.value,
            suggested_action=suggested_action,
            draft_style=effective_style,
            hints=hints,
        )
        calibrated_draft = grounding.draft_reply
        assert_draft_reply_safe(calibrated_draft, max_chars=draft_max)
        style_validation = apply_draft_style_checks(
            calibrated_draft,
            settings,
            seller_text=seller_for_calibration or "",
            detected_intent=intent.value,
            suggested_action=suggested_action,
        )
        base_row["draft_reply"] = calibrated_draft
        base_row.update(actionability_metadata_row(actionability))
        base_row["conceptual_intent_fa"] = draft_result.conceptual_intent_fa
        base_row["knowledge_hint_document_types"] = [hint.document_type for hint in hints]
        base_row.update(draft_style_metadata_row(style_validation))
        base_row.update(completion_calibration_metadata_row(completion))
        base_row["draft_generated"] = True
        if hint_error:
            base_row["error_reason"] = hint_error
    except Exception as exc:  # noqa: BLE001
        base_row["error_reason"] = str(exc)

    return base_row


def load_benchmark_cases(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"benchmark input not found: {path}")
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"line {line_no} must be a JSON object")
        cases.append(row)
    return cases


def generate_offline_draft_suggestions(
    input_path: Path,
    *,
    output_jsonl_path: Path,
    output_summary_path: Path,
    provider: str = "mock",
    model: str = "mock-vendor-ticket-drafter",
    settings: AppSettings | None = None,
    limit: int | None = None,
    generate_fn: _LLMGenerateFn | None = None,
    retrieve_fn: KnowledgeRetrievalFn | None = None,
    query_embedding_fn: Callable[[str], list[float]] | None = None,
    store: Any | None = None,
    prompt_audit_path: Path | None = None,
) -> OfflineDraftGenerationStats:
    """Read benchmark JSONL and write offline draft suggestion outputs under ``reports/``."""
    cfg = settings or get_settings()
    cases = load_benchmark_cases(input_path)
    if limit is not None:
        cases = cases[:limit]

    stats = OfflineDraftGenerationStats(
        total_cases=len(cases),
        source_path=str(input_path.resolve()),
        output_jsonl_path=str(output_jsonl_path.resolve()),
        output_summary_path=str(output_summary_path.resolve()),
        generated_at_utc=datetime.now(UTC).replace(microsecond=0).isoformat(),
        llm_provider=provider,
        llm_model=model,
    )
    failures: Counter[str] = Counter()
    by_intent: Counter[str] = Counter()

    from app.evals.draft_prompt_leakage import assert_audit_record_safe

    collect_audit = prompt_audit_path is not None
    audit_rows: list[dict[str, Any]] = []

    output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with output_jsonl_path.open("w", encoding="utf-8") as outp:
        for case in cases:
            row = process_benchmark_case(
                case,
                settings=cfg,
                provider=provider,
                model=model,
                generate_fn=generate_fn,
                retrieve_fn=retrieve_fn,
                query_embedding_fn=query_embedding_fn,
                store=store,
                collect_prompt_audit=collect_audit,
            )
            audit = row.pop("_prompt_audit", None)
            if isinstance(audit, dict):
                assert_audit_record_safe(audit)
                audit_rows.append(audit)
            outp.write(json.dumps(row, ensure_ascii=False) + "\n")
            if row.get("draft_generated"):
                stats.drafts_generated += 1
                intent = row.get("detected_intent")
                if isinstance(intent, str):
                    by_intent[intent] += 1
                if row.get("knowledge_hint_document_types"):
                    stats.cases_with_policy_hints += 1
            else:
                stats.drafts_failed += 1
                reason = str(row.get("error_reason") or "unknown")
                bucket = reason.split(":", 1)[0] if ":" in reason else reason[:80]
                failures[bucket] += 1

    stats.failure_reasons = dict(failures)
    stats.cases_by_intent = dict(by_intent)
    output_summary_path.parent.mkdir(parents=True, exist_ok=True)
    output_summary_path.write_text(
        json.dumps(stats.to_json_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if prompt_audit_path is not None:
        write_prompt_audit_jsonl(audit_rows, prompt_audit_path)
    return stats


def assert_output_row_safe(row: Mapping[str, Any]) -> None:
    """Fail closed if output row leaks gold text or forbidden keys."""
    forbidden_keys = frozenset(
        {
            "gold_reference_reply",
            "messages",
            "user_input",
            "snapshot_before_reply",
            "query",
            "retrieved_context",
        },
    )
    keys = {str(k).lower() for k in row.keys()}
    bad = keys.intersection(forbidden_keys)
    if bad:
        joined = ", ".join(sorted(bad))
        raise ValueError(f"output row contains forbidden keys: {joined}")
    draft = row.get("draft_reply")
    if isinstance(draft, str) and draft.strip():
        assert_draft_reply_safe(draft)
    serialized = json.dumps(row, ensure_ascii=False)
    if re.search(r"sk-[a-zA-Z0-9]{10,}", serialized):
        raise ValueError("output row must not contain API key patterns")
