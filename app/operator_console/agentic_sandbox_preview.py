"""Read-only agentic sandbox graph preview for the operator console (session-only)."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
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
        }


def build_agentic_preview_input_from_ticket(
    ticket: OperatorTicket,
    *,
    settings: AppSettings | None = None,
) -> AgenticSandboxState:
    """Build sandbox initial state from HITL-safe ticket fields (first-turn only)."""
    cfg = settings or get_settings()
    provider = cfg.operator_agentic_sandbox_provider.strip().lower()
    model = cfg.openai_draft_model if provider == "openai" else "mock-vendor-ticket-drafter"
    return graph_initial_from_ticket(
        ticket,
        llm_provider=provider,
        llm_model=model,
        generate_fn=None,
        knowledge_hints_enabled=cfg.operator_agentic_sandbox_knowledge_hints_enabled,
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
    )


def _optional_count_display(value: int | None) -> str:
    return str(value) if value is not None else "—"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
) -> AgenticSandboxPreviewResult:
    """Run sandbox LangGraph for one ticket; return session-safe preview metadata only."""
    cfg = settings or get_settings()
    initial = build_agentic_preview_input_from_ticket(ticket, settings=cfg)
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
