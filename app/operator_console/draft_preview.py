"""Internal draft suggestion preview and session-only regeneration (operator console)."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import AppSettings, get_settings
from app.evals.actionability_validation import (
    actionability_metadata_row,
    apply_actionability_to_draft,
    validate_actionability,
)
from app.evals.conceptual_intent_fa import generate_draft_with_conceptual_intent
from app.evals.draft_completion_calibration import (
    apply_draft_completion_calibration,
    completion_calibration_metadata_row,
)
from app.evals.draft_generation_mode import DraftGenerationMode
from app.evals.draft_prompt_leakage import (
    assert_prompt_messages_safe,
    extract_forbidden_values_from_operator_ticket,
    list_included_prompt_fields,
)
from app.evals.draft_style import apply_operational_short_style_checks, resolve_draft_style_limits
from app.evals.first_turn_draft_context import (
    ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE,
    FirstTurnDraftContext,
    build_first_turn_draft_context_from_ticket,
    draft_entity_preview_fields,
    first_turn_text_from_ticket,
)
from app.evals.offline_draft_generation import (
    assert_draft_reply_safe,
    build_offline_draft_messages,
    resolve_draft_generation_mode,
)
from app.llm.factory import generate_text
from app.llm.types import LLMResponse
from app.operator_console.console_models import OperatorTicket
from app.operator_console.knowledge_hints import (
    KnowledgeHint,
    KnowledgeRetrievalFn,
)
from app.workflows.vendor_ticket_ai_assist_shadow import _suggested_action_for_intent

DEFAULT_OFFLINE_DRAFT_SUGGESTIONS_PATH = Path(
    "reports/offline_draft_suggestions_first_turn_v1.jsonl",
)

_FORBIDDEN_PREVIEW_KEYS = frozenset(
    {
        "gold_reference_reply",
        "gold_reference_reply_hash",
        "messages",
        "user_input",
        "transcript",
        "conversation_transcript",
        "retrieved_context",
        "draft_response",
        "final_response",
    },
)

_LLMGenerateFn = Callable[..., LLMResponse]


@dataclass(frozen=True)
class DraftPreviewRecord:
    """Safe draft preview fields for operator UI (no gold or transcript)."""

    room_id: str
    draft_reply: str
    detected_intent: str | None = None
    conceptual_intent_fa: str | None = None
    suggested_action: str | None = None
    knowledge_hint_document_types: tuple[str, ...] = ()
    draft_generated: bool = True
    generated_at: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    source: str = "offline_file"
    case_id: str | None = None
    error_reason: str | None = None
    entity_source: str | None = None
    entity_extraction_source: str | None = None
    entity_extraction_source_char_count: int | None = None
    display_preview_char_count: int | None = None
    draft_entity_source: str | None = None
    draft_extracted_order_ids: str | None = None
    draft_extracted_product_ids: str | None = None
    draft_extracted_tracking_code: str | None = None
    draft_extracted_tracking_carrier: str | None = None
    draft_extracted_iban: str | None = None
    draft_extracted_iban_masked: str | None = None
    draft_entity_warnings_summary: str | None = None
    draft_style: str | None = None
    draft_char_count: int | None = None
    draft_style_ok: bool | None = None
    draft_style_warnings: tuple[str, ...] = ()
    actionability_actionable: bool | None = None
    actionability_missing_entities: str | None = None
    actionability_validation_reason: str | None = None
    requires_identifier_request: bool | None = None

    def to_public_dict(self) -> dict[str, Any]:
        """Serialize allowlisted preview fields only."""
        return {
            "room_id": self.room_id,
            "case_id": self.case_id,
            "draft_reply": self.draft_reply,
            "detected_intent": self.detected_intent,
            "conceptual_intent_fa": self.conceptual_intent_fa,
            "suggested_action": self.suggested_action,
            "knowledge_hint_document_types": list(self.knowledge_hint_document_types),
            "draft_generated": self.draft_generated,
            "generated_at": self.generated_at,
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "source": self.source,
            "error_reason": self.error_reason,
            "entity_source": self.entity_source,
            "entity_extraction_source": self.entity_extraction_source,
            "entity_extraction_source_char_count": self.entity_extraction_source_char_count,
            "display_preview_char_count": self.display_preview_char_count,
            "draft_entity_source": self.draft_entity_source,
            "draft_extracted_order_ids": self.draft_extracted_order_ids,
            "draft_extracted_product_ids": self.draft_extracted_product_ids,
            "draft_extracted_tracking_code": self.draft_extracted_tracking_code,
            "draft_extracted_tracking_carrier": self.draft_extracted_tracking_carrier,
            "draft_extracted_iban": self.draft_extracted_iban,
            "draft_extracted_iban_masked": self.draft_extracted_iban_masked,
            "draft_entity_warnings_summary": self.draft_entity_warnings_summary,
            "draft_style": self.draft_style,
            "draft_char_count": self.draft_char_count,
            "draft_style_ok": self.draft_style_ok,
            "draft_style_warnings": list(self.draft_style_warnings),
            "actionability_actionable": self.actionability_actionable,
            "actionability_missing_entities": self.actionability_missing_entities,
            "actionability_validation_reason": self.actionability_validation_reason,
            "requires_identifier_request": self.requires_identifier_request,
        }


def _load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path}:{line_no}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"line {line_no} must be a JSON object")
        rows.append(row)
    return rows


def load_offline_draft_suggestions(
    path: Path | str,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Load draft rows indexed by ``room_id`` and ``case_id``."""
    by_room: dict[str, dict[str, Any]] = {}
    by_case: dict[str, dict[str, Any]] = {}
    for row in _load_jsonl_rows(Path(path)):
        room_id = row.get("room_id")
        case_id = row.get("case_id")
        if isinstance(room_id, str) and room_id.strip():
            room_key = room_id.strip()
            existing = by_room.get(room_key)
            if existing is None or _prefer_draft_row(row, over=existing):
                by_room[room_key] = row
        if isinstance(case_id, str) and case_id.strip():
            by_case[case_id.strip()] = row
    return by_room, by_case


def _prefer_draft_row(candidate: Mapping[str, Any], *, over: Mapping[str, Any]) -> bool:
    """Prefer first_vendor_turn rows and generated drafts when multiple exist per room."""
    cand_case = str(candidate.get("case_id") or "")
    over_case = str(over.get("case_id") or "")
    if cand_case.endswith("__first_vendor_turn") and not over_case.endswith("__first_vendor_turn"):
        return True
    if over_case.endswith("__first_vendor_turn") and not cand_case.endswith("__first_vendor_turn"):
        return False
    return bool(candidate.get("draft_generated")) and not bool(over.get("draft_generated"))


def find_draft_for_room_or_case(
    room_id: str,
    *,
    by_room: Mapping[str, Mapping[str, Any]],
    by_case: Mapping[str, Mapping[str, Any]],
    case_id: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a draft suggestion row for a ticket room (optional explicit case_id)."""
    if case_id and case_id in by_case:
        return dict(by_case[case_id])
    first_turn_id = f"{room_id}__first_vendor_turn"
    if first_turn_id in by_case:
        return dict(by_case[first_turn_id])
    if case_id:
        return None
    row = by_room.get(room_id)
    return dict(row) if row else None


def assert_draft_preview_record_safe(record: Mapping[str, Any]) -> None:
    """Fail closed if preview payload may leak forbidden fields."""
    keys = {str(key).lower() for key in record.keys()}
    forbidden = keys.intersection(_FORBIDDEN_PREVIEW_KEYS)
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise ValueError(f"draft preview contains forbidden keys: {joined}")
    draft = record.get("draft_reply")
    if isinstance(draft, str) and draft.strip():
        assert_draft_reply_safe(draft)


def build_draft_preview_record(
    row: Mapping[str, Any],
    *,
    source: str = "offline_file",
) -> DraftPreviewRecord | None:
    """Map an offline draft JSONL row to a safe preview record."""
    room_id = row.get("room_id")
    if not isinstance(room_id, str) or not room_id.strip():
        return None
    draft = row.get("draft_reply")
    if not isinstance(draft, str) or not draft.strip():
        return None
    doc_types_raw = row.get("knowledge_hint_document_types")
    doc_types: tuple[str, ...] = ()
    if isinstance(doc_types_raw, list):
        doc_types = tuple(str(item) for item in doc_types_raw if str(item).strip())
    elif isinstance(doc_types_raw, str) and doc_types_raw.strip():
        doc_types = tuple(part.strip() for part in doc_types_raw.split(",") if part.strip())

    style_warnings_raw = row.get("draft_style_warnings")
    style_warnings: tuple[str, ...] = ()
    if isinstance(style_warnings_raw, list):
        style_warnings = tuple(str(w) for w in style_warnings_raw if str(w).strip())

    record = DraftPreviewRecord(
        room_id=room_id.strip(),
        case_id=_optional_str(row.get("case_id")),
        draft_reply=draft.strip(),
        detected_intent=_optional_str(row.get("detected_intent")),
        conceptual_intent_fa=_optional_str(row.get("conceptual_intent_fa")),
        suggested_action=_optional_str(row.get("suggested_action")),
        knowledge_hint_document_types=doc_types,
        draft_generated=bool(row.get("draft_generated")),
        generated_at=_optional_str(row.get("generated_at_utc"))
        or _optional_str(row.get("generated_at")),
        llm_model=_optional_str(row.get("llm_model")),
        llm_provider=_optional_str(row.get("llm_provider")),
        source=source,
        error_reason=_optional_str(row.get("error_reason")),
        entity_source=_optional_str(row.get("entity_source"))
        or _optional_str(row.get("draft_entity_source")),
        draft_entity_source=_optional_str(row.get("draft_entity_source"))
        or _optional_str(row.get("entity_source")),
        draft_extracted_order_ids=_optional_str(row.get("draft_extracted_order_ids")),
        draft_extracted_product_ids=_optional_str(row.get("draft_extracted_product_ids")),
        draft_extracted_tracking_code=_optional_str(row.get("draft_extracted_tracking_code")),
        draft_extracted_tracking_carrier=_optional_str(row.get("draft_extracted_tracking_carrier")),
        draft_extracted_iban=_optional_str(row.get("draft_extracted_iban")),
        draft_extracted_iban_masked=_optional_str(row.get("draft_extracted_iban_masked")),
        draft_entity_warnings_summary=_optional_str(row.get("draft_entity_warnings_summary")),
        draft_style=_optional_str(row.get("draft_style")),
        draft_char_count=_optional_int(row.get("draft_char_count")),
        draft_style_ok=_optional_bool(row.get("draft_style_ok")),
        draft_style_warnings=style_warnings,
        actionability_actionable=_optional_bool(row.get("actionability_actionable"))
        if row.get("actionability_actionable") is not None
        else _optional_bool(row.get("actionability")),
        actionability_missing_entities=_optional_str(row.get("actionability_missing_entities")),
        actionability_validation_reason=_optional_str(row.get("actionability_validation_reason")),
        requires_identifier_request=_optional_bool(row.get("requires_identifier_request")),
    )
    assert_draft_preview_record_safe(record.to_public_dict())
    return record


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def enrich_draft_preview_with_first_turn_entities(
    record: DraftPreviewRecord | None,
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
) -> DraftPreviewRecord | None:
    """Re-derive draft entity fields from ``original_vendor_issue_preview`` only."""
    if record is None:
        return None
    cfg = settings or get_settings()
    if resolve_draft_generation_mode(cfg) != DraftGenerationMode.FIRST_TURN_ONLY:
        return record
    hint_cfg = cfg
    if cfg.knowledge_hints_enabled:
        hint_cfg = cfg.model_copy(update={"knowledge_hints_enabled": False})
    ctx = build_first_turn_draft_context_from_ticket(
        ticket,
        settings=hint_cfg,
        hints=(),
    )
    fields = draft_entity_preview_fields(ctx.first_turn_entities, context=ctx)
    return enrich_draft_preview_with_actionability(
        replace(
            record,
            entity_source=fields.get("entity_source"),
            entity_extraction_source=fields.get("entity_extraction_source"),
            entity_extraction_source_char_count=fields.get("entity_extraction_source_char_count"),
            display_preview_char_count=fields.get("display_preview_char_count"),
            draft_entity_source=fields.get("draft_entity_source"),
            draft_extracted_order_ids=fields.get("draft_extracted_order_ids"),
            draft_extracted_product_ids=fields.get("draft_extracted_product_ids"),
            draft_extracted_tracking_code=fields.get("draft_extracted_tracking_code"),
            draft_extracted_tracking_carrier=fields.get("draft_extracted_tracking_carrier"),
            draft_extracted_iban=fields.get("draft_extracted_iban"),
            draft_extracted_iban_masked=fields.get("draft_extracted_iban_masked"),
            draft_entity_warnings_summary=fields.get("draft_entity_warnings_summary"),
        ),
        ticket,
        entities=ctx.first_turn_entities,
    )


def enrich_draft_preview_with_actionability(
    record: DraftPreviewRecord | None,
    ticket: OperatorTicket,
    *,
    entities: Any | None = None,
) -> DraftPreviewRecord | None:
    """Attach actionability validation for operator preview (no draft mutation)."""
    if record is None:
        return None
    if record.actionability_validation_reason and record.actionability_actionable is not None:
        return record
    seller_text = first_turn_text_from_ticket(ticket)
    order_ids: list[str] = []
    product_ids: list[str] = []
    tracking: str | None = None
    if record.draft_extracted_order_ids:
        order_ids = [
            part.strip() for part in record.draft_extracted_order_ids.split(",") if part.strip()
        ]
    if record.draft_extracted_product_ids:
        product_ids = [
            part.strip() for part in record.draft_extracted_product_ids.split(",") if part.strip()
        ]
    tracking = record.draft_extracted_tracking_code
    validation = validate_actionability(
        suggested_action=record.suggested_action or "",
        order_ids=order_ids,
        product_ids=product_ids,
        tracking_code=tracking,
        seller_text=seller_text,
        detected_intent=record.detected_intent,
        entities=entities,
    )
    meta = actionability_metadata_row(validation)
    return replace(
        record,
        actionability_actionable=meta.get("actionability_actionable"),
        actionability_missing_entities=meta.get("actionability_missing_entities"),
        actionability_validation_reason=meta.get("actionability_validation_reason"),
        requires_identifier_request=meta.get("requires_identifier_request"),
    )


def draft_mode_display_label(mode: DraftGenerationMode) -> str:
    if mode == DraftGenerationMode.FIRST_TURN_ONLY:
        return "First-turn only"
    return "Live thread context"


def _operator_ticket_as_case(ticket: OperatorTicket) -> dict[str, Any]:
    return {
        "ticket_label": ticket.ticket_label,
        "route_label": ticket.route_label,
        "seller_intent_type": ticket.seller_intent_type,
        "seller_operational_request_type": ticket.seller_operational_request_type,
        "snapshot_before_reply": {
            "original_vendor_issue_preview": ticket.original_vendor_issue_preview,
            "latest_vendor_message": ticket.latest_vendor_message,
            "recent_context_preview": ticket.recent_context_preview,
        },
        "open_ticket_preview": ticket.open_ticket_preview,
        "ticket_text_preview": ticket.ticket_text_preview,
    }


def _thread_texts_from_ticket(ticket: OperatorTicket) -> list[str]:
    texts: list[str] = []
    for value in (
        ticket.latest_vendor_message,
        ticket.recent_context_preview,
        ticket.open_ticket_preview,
        ticket.ticket_text_preview,
    ):
        if isinstance(value, str) and value.strip():
            texts.append(value.strip())
    return texts


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def generate_draft_for_operator_ticket(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
    hints: Sequence[KnowledgeHint] | None = None,
    generate_fn: _LLMGenerateFn | None = None,
    retrieve_fn: KnowledgeRetrievalFn | None = None,
    query_embedding_fn: Callable[[str], list[float]] | None = None,
    store: Any | None = None,
) -> DraftPreviewRecord:
    """Regenerate an internal draft from safe operator fields (session-only; not persisted)."""
    cfg = settings or get_settings()
    if not cfg.operator_draft_generation_enabled:
        raise ValueError(
            "operator draft generation is disabled (set OPERATOR_DRAFT_GENERATION_ENABLED=true)",
        )

    draft_mode = resolve_draft_generation_mode(cfg)
    first_turn_ctx: FirstTurnDraftContext | None = None
    if draft_mode == DraftGenerationMode.FIRST_TURN_ONLY:
        first_turn_ctx = build_first_turn_draft_context_from_ticket(
            ticket,
            settings=cfg,
            hints=hints,
            store=store,
            query_embedding_fn=query_embedding_fn,
            retrieve_fn=retrieve_fn,
        )
        intent_result = first_turn_ctx.first_turn_intent
        suggested_action = first_turn_ctx.suggested_action
        policy_hints = first_turn_ctx.first_turn_policy_hints
        source_text = first_turn_ctx.first_turn_text
    else:
        from app.workflows.seller_notification_detection import normalize_persian_arabic_digits
        from app.workflows.vendor_ticket_intent_detection import detect_vendor_ticket_intent

        parts: list[str] = []
        for value in (
            ticket.original_vendor_issue_preview,
            ticket.latest_vendor_message,
            ticket.recent_context_preview,
        ):
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
        source_text = " ".join(parts)
        intent_result = detect_vendor_ticket_intent(
            source_text,
            ticket_label=ticket.ticket_label,
            route_label=ticket.route_label,
        )
        normalized = normalize_persian_arabic_digits(source_text) if source_text else ""
        suggested_action = _suggested_action_for_intent(
            intent_result.intent,
            normalized_text=normalized,
        ).value
        policy_hints = tuple(hints or ())
        if not policy_hints and cfg.knowledge_hints_enabled:
            from app.operator_console.knowledge_hints import fetch_knowledge_hints_for_ticket

            policy_hints = fetch_knowledge_hints_for_ticket(
                ticket,
                settings=cfg,
                store=store,
                query_embedding_fn=query_embedding_fn,
                retrieve_fn=retrieve_fn,
            )

    case_payload = _operator_ticket_as_case(ticket)
    messages = build_offline_draft_messages(
        case_payload,
        intent_result=intent_result,
        suggested_action=suggested_action,
        policy_hints=policy_hints,
        mode=draft_mode,
        first_turn_context=first_turn_ctx,
        settings=cfg,
    )
    thread_texts = (
        _thread_texts_from_ticket(ticket)
        if draft_mode == DraftGenerationMode.FIRST_TURN_ONLY
        else None
    )
    assert_prompt_messages_safe(
        messages,
        forbidden_values=extract_forbidden_values_from_operator_ticket(
            ticket,
            mode=draft_mode,
        ),
        mode=draft_mode,
        first_turn_text=first_turn_text_from_ticket(ticket)
        if draft_mode == DraftGenerationMode.FIRST_TURN_ONLY
        else None,
        thread_texts=thread_texts,
        ticket=ticket if draft_mode == DraftGenerationMode.FIRST_TURN_ONLY else None,
    )
    _ = list_included_prompt_fields(
        case_payload,
        intent_result=intent_result,
        suggested_action=suggested_action,
        policy_hints=policy_hints,
        mode=draft_mode,
    )

    model = cfg.operator_draft_model.strip() or "gpt-4o-mini"
    _style, _max_sent, _target, hard_max = resolve_draft_style_limits(cfg)
    max_chars = min(cfg.operator_draft_max_chars, hard_max)
    draft_result = generate_draft_with_conceptual_intent(
        messages,
        detected_intent=intent_result.detected_intent,
        provider="openai",
        model=model,
        generate_fn=generate_fn or generate_text,
        max_chars=max_chars,
        source_text=source_text,
    )
    assert_draft_reply_safe(draft_result.draft_reply, max_chars=max_chars)
    entity_warnings = getattr(intent_result, "entity_warnings_summary", None)
    completion = apply_draft_completion_calibration(
        draft_result.draft_reply,
        seller_text=source_text or "",
        suggested_action=suggested_action,
        detected_intent=intent_result.detected_intent,
        entity_warnings_summary=entity_warnings,
    )
    calibrated_draft = completion.draft_reply
    actionability = validate_actionability(
        suggested_action=suggested_action,
        entities=intent_result,
        seller_text=source_text or "",
        detected_intent=intent_result.detected_intent,
    )
    calibrated_draft, actionability = apply_actionability_to_draft(
        calibrated_draft,
        actionability,
        seller_text=source_text or "",
    )
    assert_draft_reply_safe(calibrated_draft, max_chars=max_chars)
    style_validation = apply_operational_short_style_checks(
        calibrated_draft,
        cfg,
    )
    _ = completion_calibration_metadata_row(completion)
    actionability_fields = actionability_metadata_row(actionability)

    entity_fields: dict[str, str | None] = {}
    if first_turn_ctx is not None:
        entity_fields = draft_entity_preview_fields(
            first_turn_ctx.first_turn_entities,
            context=first_turn_ctx,
        )

    record = DraftPreviewRecord(
        room_id=ticket.room_id,
        case_id=f"{ticket.room_id}__first_vendor_turn",
        draft_reply=calibrated_draft,
        detected_intent=intent_result.detected_intent,
        conceptual_intent_fa=draft_result.conceptual_intent_fa,
        suggested_action=suggested_action,
        knowledge_hint_document_types=tuple(h.document_type for h in policy_hints),
        draft_generated=True,
        generated_at=_utc_now_iso(),
        llm_model=model,
        llm_provider="openai",
        source="session_regenerate",
        entity_source=entity_fields.get("entity_source")
        or (
            first_turn_ctx.entity_source
            if first_turn_ctx is not None
            else ENTITY_SOURCE_ORIGINAL_VENDOR_ISSUE
        ),
        entity_extraction_source=entity_fields.get("entity_extraction_source"),
        entity_extraction_source_char_count=entity_fields.get(
            "entity_extraction_source_char_count"
        ),
        display_preview_char_count=entity_fields.get("display_preview_char_count"),
        draft_entity_source=entity_fields.get("draft_entity_source"),
        draft_extracted_order_ids=entity_fields.get("draft_extracted_order_ids"),
        draft_extracted_product_ids=entity_fields.get("draft_extracted_product_ids"),
        draft_extracted_tracking_code=entity_fields.get("draft_extracted_tracking_code"),
        draft_extracted_tracking_carrier=entity_fields.get("draft_extracted_tracking_carrier"),
        draft_extracted_iban=entity_fields.get("draft_extracted_iban"),
        draft_extracted_iban_masked=entity_fields.get("draft_extracted_iban_masked"),
        draft_entity_warnings_summary=entity_fields.get("draft_entity_warnings_summary"),
        draft_style=style_validation.draft_style,
        draft_char_count=style_validation.draft_char_count,
        draft_style_ok=style_validation.draft_style_ok,
        draft_style_warnings=style_validation.draft_style_warnings,
        actionability_actionable=actionability_fields.get("actionability_actionable"),
        actionability_missing_entities=actionability_fields.get("actionability_missing_entities"),
        actionability_validation_reason=actionability_fields.get(
            "actionability_validation_reason",
        ),
        requires_identifier_request=actionability_fields.get("requires_identifier_request"),
    )
    assert_draft_preview_record_safe(record.to_public_dict())
    return record


SESSION_DRAFT_OVERRIDES_KEY = "operator_draft_session_overrides"


def get_session_draft_overrides(session_state: Mapping[str, Any]) -> dict[str, DraftPreviewRecord]:
    """Return room_id → session-regenerated draft map from Streamlit-like state."""
    raw = session_state.get(SESSION_DRAFT_OVERRIDES_KEY, {})
    if not isinstance(raw, dict):
        return {}
    out: dict[str, DraftPreviewRecord] = {}
    for key, value in raw.items():
        if isinstance(value, DraftPreviewRecord):
            out[str(key)] = value
    return out


def store_session_draft(session_state: dict[str, Any], record: DraftPreviewRecord) -> None:
    """Persist a regenerated draft in session-only storage (not JSONL/DB)."""
    bucket = session_state.setdefault(SESSION_DRAFT_OVERRIDES_KEY, {})
    if not isinstance(bucket, dict):
        bucket = {}
        session_state[SESSION_DRAFT_OVERRIDES_KEY] = bucket
    bucket[record.room_id] = record


def load_draft_preview_for_ticket(
    ticket: OperatorTicket,
    *,
    suggestions_path: Path | str,
    session_overrides: Mapping[str, DraftPreviewRecord] | None = None,
    load_offline: bool = True,
    settings: AppSettings | None = None,
) -> DraftPreviewRecord | None:
    """Session regenerated draft wins; else optional offline JSONL lookup."""
    overrides = session_overrides or {}
    if ticket.room_id in overrides:
        enriched = enrich_draft_preview_with_first_turn_entities(
            overrides[ticket.room_id],
            ticket,
            settings=settings,
        )
        return enrich_draft_preview_with_actionability(enriched, ticket)
    if not load_offline:
        return None
    by_room, by_case = load_offline_draft_suggestions(suggestions_path)
    row = find_draft_for_room_or_case(
        ticket.room_id,
        by_room=by_room,
        by_case=by_case,
    )
    if row is None:
        return None
    record = build_draft_preview_record(row)
    enriched = enrich_draft_preview_with_first_turn_entities(record, ticket, settings=settings)
    return enrich_draft_preview_with_actionability(enriched, ticket)
