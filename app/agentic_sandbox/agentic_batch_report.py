"""Batch agentic sandbox runs for first-vendor tickets (observability only)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_graph import (
    NODE_ORDER,
    initial_state_from_ticket,
    resolve_ticket_for_sandbox,
    run_agentic_sandbox_workflow,
)
from app.agentic_sandbox.langsmith_tracing import (
    LangSmithTracingStatus,
    configure_agentic_sandbox_langsmith_tracing,
)
from app.agentic_sandbox.policy_relevance import is_policy_relevant_signals
from app.agentic_sandbox.report_paths import (
    DEFAULT_BATCH_REPORT_MD,
    DEFAULT_BATCH_RUNS_JSONL,
    DEFAULT_BATCH_SUMMARY_JSON,
)
from app.config import AppSettings, get_settings
from app.evals.first_turn_draft_context import first_turn_text_from_ticket
from app.operator_console.console_loader import (
    load_conversation_snapshot_index,
    load_operator_tickets,
)
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS
from app.operator_console.first_vendor_filter import (
    filter_first_vendor_tickets,
    first_meaningful_sender_type,
    is_first_vendor_ticket,
)
from app.tickets.conversation_models import ConversationTicketSnapshot

_SUPPORT_FIRST_SENDERS = frozenset({"support_agent", "finance_agent"})


@dataclass(frozen=True)
class FirstVendorRoomSelection:
    """First-vendor room ids eligible for batch sandbox runs."""

    total_candidate_rooms: int
    first_vendor_rooms: int
    excluded_support_first: int
    excluded_no_snapshot: int
    excluded_not_first_vendor: int
    room_ids: tuple[str, ...]


@dataclass(frozen=True)
class AgenticBatchRunRow:
    """Safe per-room batch result (no full draft or transcript)."""

    room_id: str
    ticket_label: str | None
    route_label: str | None
    node_statuses: dict[str, str]
    safety_status: str | None
    detected_intent: str | None
    conceptual_intent_fa: str | None
    suggested_action: str | None
    actionability_actionable: bool | None
    missing_required_entities: str | None
    order_id_count: int
    product_id_count: int
    has_tracking_code: bool
    knowledge_hints_enabled: bool
    knowledge_hint_count: int
    knowledge_hint_document_types: tuple[str, ...]
    draft_char_count: int
    human_review_required: bool
    execution_allowed: bool
    customer_send_allowed: bool
    success: bool
    errors: tuple[str, ...]
    entity_extraction_source: str | None = None
    entity_extraction_source_char_count: int | None = None
    display_preview_char_count: int | None = None
    draft_provider: str | None = None
    openai_draft_quality_rate: float | None = None
    generic_reply_rate: float | None = None
    concise_reply_rate: float | None = None
    fallback_to_mock_rate: float | None = None
    over_questioning_rate: float | None = None
    unnecessary_clarification_rate: float | None = None
    operational_completion_success_rate: float | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "ticket_label": self.ticket_label,
            "route_label": self.route_label,
            "node_statuses": dict(self.node_statuses),
            "safety_status": self.safety_status,
            "detected_intent": self.detected_intent,
            "conceptual_intent_fa": self.conceptual_intent_fa,
            "suggested_action": self.suggested_action,
            "actionability_actionable": self.actionability_actionable,
            "missing_required_entities": self.missing_required_entities,
            "order_id_count": self.order_id_count,
            "product_id_count": self.product_id_count,
            "has_tracking_code": self.has_tracking_code,
            "knowledge_hints_enabled": self.knowledge_hints_enabled,
            "knowledge_hint_count": self.knowledge_hint_count,
            "knowledge_hint_document_types": list(self.knowledge_hint_document_types),
            "draft_char_count": self.draft_char_count,
            "human_review_required": self.human_review_required,
            "execution_allowed": self.execution_allowed,
            "customer_send_allowed": self.customer_send_allowed,
            "success": self.success,
            "errors": list(self.errors),
            "entity_extraction_source": self.entity_extraction_source,
            "entity_extraction_source_char_count": self.entity_extraction_source_char_count,
            "display_preview_char_count": self.display_preview_char_count,
            "draft_provider": self.draft_provider,
            "openai_draft_quality_rate": self.openai_draft_quality_rate,
            "generic_reply_rate": self.generic_reply_rate,
            "concise_reply_rate": self.concise_reply_rate,
            "fallback_to_mock_rate": self.fallback_to_mock_rate,
            "over_questioning_rate": self.over_questioning_rate,
            "unnecessary_clarification_rate": self.unnecessary_clarification_rate,
            "operational_completion_success_rate": self.operational_completion_success_rate,
        }


@dataclass
class AgenticBatchSummary:
    """Aggregate metrics over batch sandbox runs."""

    generated_at_utc: str
    replay_jsonl: str
    redacted_jsonl: str | None
    provider: str
    limit_applied: int | None
    total_candidate_rooms: int
    first_vendor_rooms: int
    excluded_support_first: int
    excluded_no_snapshot: int
    processed_count: int
    success_count: int
    error_count: int
    safety_passed_count: int
    human_review_required_count: int
    execution_allowed_true_count: int
    customer_send_allowed_true_count: int
    missing_identifier_count: int
    actionable_count: int
    by_detected_intent: dict[str, int] = field(default_factory=dict)
    by_suggested_action: dict[str, int] = field(default_factory=dict)
    by_actionability: dict[str, int] = field(default_factory=dict)
    node_error_counts: dict[str, int] = field(default_factory=dict)
    average_draft_char_count: float = 0.0
    rooms_with_errors: tuple[str, ...] = ()
    langsmith_tracing_enabled: bool = False
    langsmith_project: str | None = None
    knowledge_hints_enabled: bool = False
    knowledge_hint_coverage_rate: float = 0.0
    policy_relevant_runs: int = 0
    policy_relevant_with_hints: int = 0
    policy_relevant_without_hints: int = 0
    by_draft_provider: dict[str, int] = field(default_factory=dict)
    openai_draft_quality_rate: float = 0.0
    generic_reply_rate: float = 0.0
    concise_reply_rate: float = 0.0
    fallback_to_mock_rate: float = 0.0
    over_questioning_rate: float = 0.0
    unnecessary_clarification_rate: float = 0.0
    operational_completion_success_rate: float = 0.0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "replay_jsonl": self.replay_jsonl,
            "redacted_jsonl": self.redacted_jsonl,
            "provider": self.provider,
            "limit_applied": self.limit_applied,
            "total_candidate_rooms": self.total_candidate_rooms,
            "first_vendor_rooms": self.first_vendor_rooms,
            "excluded_support_first": self.excluded_support_first,
            "excluded_no_snapshot": self.excluded_no_snapshot,
            "processed_count": self.processed_count,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "safety_passed_count": self.safety_passed_count,
            "human_review_required_count": self.human_review_required_count,
            "execution_allowed_true_count": self.execution_allowed_true_count,
            "customer_send_allowed_true_count": self.customer_send_allowed_true_count,
            "missing_identifier_count": self.missing_identifier_count,
            "actionable_count": self.actionable_count,
            "by_detected_intent": dict(self.by_detected_intent),
            "by_suggested_action": dict(self.by_suggested_action),
            "by_actionability": dict(self.by_actionability),
            "node_error_counts": dict(self.node_error_counts),
            "average_draft_char_count": self.average_draft_char_count,
            "rooms_with_errors": list(self.rooms_with_errors),
            "langsmith_tracing_enabled": self.langsmith_tracing_enabled,
            "langsmith_project": self.langsmith_project,
            "knowledge_hints_enabled": self.knowledge_hints_enabled,
            "knowledge_hint_coverage_rate": self.knowledge_hint_coverage_rate,
            "policy_relevant_runs": self.policy_relevant_runs,
            "policy_relevant_with_hints": self.policy_relevant_with_hints,
            "policy_relevant_without_hints": self.policy_relevant_without_hints,
            "by_draft_provider": dict(self.by_draft_provider),
            "openai_draft_quality_rate": self.openai_draft_quality_rate,
            "generic_reply_rate": self.generic_reply_rate,
            "concise_reply_rate": self.concise_reply_rate,
            "fallback_to_mock_rate": self.fallback_to_mock_rate,
            "over_questioning_rate": self.over_questioning_rate,
            "unnecessary_clarification_rate": self.unnecessary_clarification_rate,
            "operational_completion_success_rate": self.operational_completion_success_rate,
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _average_optional(values: Sequence[float | None]) -> float:
    present = [value for value in values if value is not None]
    if not present:
        return 0.0
    return round(sum(present) / len(present), 4)


def _is_policy_relevant_batch_row(row: AgenticBatchRunRow) -> bool:
    return is_policy_relevant_signals(
        detected_intent=row.detected_intent,
        conceptual_intent_fa=row.conceptual_intent_fa,
        suggested_action=row.suggested_action,
        ticket_label=row.ticket_label,
        route_label=row.route_label,
    )


def load_first_vendor_room_ids(
    replay_jsonl: Path | str,
    *,
    redacted_jsonl: Path | str | None = None,
    limit: int | None = None,
) -> FirstVendorRoomSelection:
    """Return room_ids where the first meaningful sender is seller/vendor."""
    replay_path = Path(replay_jsonl)
    redacted_path = Path(redacted_jsonl) if redacted_jsonl is not None else None

    tickets = load_operator_tickets(
        replay_path,
        redacted_tickets_path=redacted_path,
    )
    snapshot_index: dict[str, ConversationTicketSnapshot] = {}
    if redacted_path is not None and redacted_path.is_file():
        snapshot_index = load_conversation_snapshot_index(redacted_path)

    excluded_support_first = 0
    excluded_no_snapshot = 0
    excluded_not_first_vendor = 0

    for ticket in tickets:
        snapshot = snapshot_index.get(ticket.room_id)
        if snapshot is None:
            excluded_no_snapshot += 1
            continue
        if is_first_vendor_ticket(snapshot):
            continue
        first = first_meaningful_sender_type(snapshot.messages)
        if first in _SUPPORT_FIRST_SENDERS:
            excluded_support_first += 1
        elif first is not None:
            excluded_not_first_vendor += 1

    if snapshot_index:
        eligible = filter_first_vendor_tickets(tickets, snapshot_index=snapshot_index)
    else:
        eligible = [
            ticket
            for ticket in tickets
            if ticket.original_vendor_issue_preview
            and str(ticket.original_vendor_issue_preview).strip()
        ]

    room_ids = [ticket.room_id for ticket in eligible]
    if limit is not None and limit > 0:
        room_ids = room_ids[:limit]

    return FirstVendorRoomSelection(
        total_candidate_rooms=len(tickets),
        first_vendor_rooms=len(eligible),
        excluded_support_first=excluded_support_first,
        excluded_no_snapshot=excluded_no_snapshot,
        excluded_not_first_vendor=excluded_not_first_vendor,
        room_ids=tuple(room_ids),
    )


def _node_statuses_from_state(state: dict[str, Any]) -> dict[str, str]:
    statuses: dict[str, str] = {node: "pending" for node in NODE_ORDER}
    for entry in state.get("node_results") or []:
        if not isinstance(entry, dict):
            continue
        node = entry.get("node")
        status = entry.get("status")
        if isinstance(node, str) and node in statuses and isinstance(status, str):
            statuses[node] = status
    return statuses


def _hint_document_types(hints: list[Any] | None) -> tuple[str, ...]:
    if not hints:
        return ()
    types: list[str] = []
    for item in hints:
        if isinstance(item, dict):
            doc_type = item.get("document_type")
            if doc_type and str(doc_type).strip():
                types.append(str(doc_type).strip())
    return tuple(dict.fromkeys(types))


def _entity_counts(entities: dict[str, Any] | None) -> tuple[int, int, bool]:
    if not entities:
        return 0, 0, False
    orders = entities.get("order_ids") or []
    products = entities.get("product_ids") or []
    tracking = entities.get("tracking_code")
    order_count = len(orders) if isinstance(orders, list) else 0
    product_count = len(products) if isinstance(products, list) else 0
    has_tracking = bool(tracking and str(tracking).strip())
    return order_count, product_count, has_tracking


def state_to_batch_row(
    state: dict[str, Any],
    *,
    success: bool,
    knowledge_hints_enabled: bool = False,
    errors: list[str] | None = None,
) -> AgenticBatchRunRow:
    """Build safe JSONL row from final graph state (no draft body)."""
    actionability = state.get("actionability") or {}
    if not isinstance(actionability, dict):
        actionability = {}
    entities = state.get("extracted_entities") or {}
    if not isinstance(entities, dict):
        entities = {}
    order_count, product_count, has_tracking = _entity_counts(entities)
    hints = state.get("knowledge_hints") or []
    hint_count = len(hints) if isinstance(hints, list) else 0
    hint_doc_types = _hint_document_types(hints if isinstance(hints, list) else None)
    draft = state.get("draft_reply")
    draft_chars = len(draft) if isinstance(draft, str) else 0
    merged_errors = list(state.get("errors") or [])
    if errors:
        merged_errors.extend(errors)

    openai_meta = state.get("openai_draft_metrics") or {}
    if not isinstance(openai_meta, dict):
        openai_meta = {}
    sufficiency_meta = state.get("operational_sufficiency_metrics") or {}
    if not isinstance(sufficiency_meta, dict):
        sufficiency_meta = {}
    draft_provider_raw = state.get("draft_provider")
    draft_provider = (
        str(draft_provider_raw).strip()
        if isinstance(draft_provider_raw, str) and draft_provider_raw.strip()
        else None
    )

    return AgenticBatchRunRow(
        room_id=str(state.get("room_id") or ""),
        ticket_label=state.get("ticket_label"),
        route_label=state.get("route_label"),
        node_statuses=_node_statuses_from_state(state),
        safety_status=state.get("safety_status"),
        detected_intent=state.get("detected_intent"),
        conceptual_intent_fa=state.get("conceptual_intent_fa"),
        suggested_action=state.get("suggested_action"),
        actionability_actionable=actionability.get("actionability_actionable"),
        missing_required_entities=actionability.get("actionability_missing_entities"),
        order_id_count=order_count,
        product_id_count=product_count,
        has_tracking_code=has_tracking,
        knowledge_hints_enabled=knowledge_hints_enabled,
        knowledge_hint_count=hint_count,
        knowledge_hint_document_types=hint_doc_types,
        draft_char_count=draft_chars,
        human_review_required=bool(state.get("human_review_required")),
        execution_allowed=bool(state.get("execution_allowed")),
        customer_send_allowed=bool(state.get("customer_send_allowed")),
        success=success,
        errors=tuple(merged_errors),
        entity_extraction_source=(
            str(state["entity_extraction_source"]).strip()
            if state.get("entity_extraction_source")
            else (
                str(entities.get("entity_source")).strip()
                if entities.get("entity_source")
                else None
            )
        ),
        entity_extraction_source_char_count=(
            int(state["entity_extraction_source_char_count"])
            if state.get("entity_extraction_source_char_count") is not None
            else None
        ),
        display_preview_char_count=(
            int(state["display_preview_char_count"])
            if state.get("display_preview_char_count") is not None
            else None
        ),
        draft_provider=draft_provider,
        openai_draft_quality_rate=_optional_float(openai_meta.get("openai_draft_quality_rate")),
        generic_reply_rate=_optional_float(openai_meta.get("generic_reply_rate")),
        concise_reply_rate=_optional_float(openai_meta.get("concise_reply_rate")),
        fallback_to_mock_rate=_optional_float(openai_meta.get("fallback_to_mock_rate")),
        over_questioning_rate=_optional_float(sufficiency_meta.get("over_questioning_rate")),
        unnecessary_clarification_rate=_optional_float(
            sufficiency_meta.get("unnecessary_clarification_rate"),
        ),
        operational_completion_success_rate=_optional_float(
            sufficiency_meta.get("operational_completion_success_rate"),
        ),
    )


def error_batch_row(
    room_id: str,
    *,
    error: str,
    ticket_label: str | None = None,
    route_label: str | None = None,
    knowledge_hints_enabled: bool = False,
) -> AgenticBatchRunRow:
    """Minimal row when a room fails before or during graph execution."""
    return AgenticBatchRunRow(
        room_id=room_id,
        ticket_label=ticket_label,
        route_label=route_label,
        node_statuses={node: "skipped" for node in NODE_ORDER},
        safety_status=None,
        detected_intent=None,
        conceptual_intent_fa=None,
        suggested_action=None,
        actionability_actionable=None,
        missing_required_entities=None,
        order_id_count=0,
        product_id_count=0,
        has_tracking_code=False,
        knowledge_hints_enabled=knowledge_hints_enabled,
        knowledge_hint_count=0,
        knowledge_hint_document_types=(),
        draft_char_count=0,
        human_review_required=True,
        execution_allowed=False,
        customer_send_allowed=False,
        success=False,
        errors=(error,),
    )


def run_agentic_sandbox_batch(
    room_ids: Sequence[str],
    *,
    replay_jsonl: Path | str,
    redacted_jsonl: Path | str | None = None,
    settings: AppSettings | None = None,
    provider: str = "mock",
    model: str = "mock-vendor-ticket-drafter",
    generate_fn: Any | None = None,
    enable_knowledge_hints: bool = False,
) -> list[AgenticBatchRunRow]:
    """Run sandbox graph per room; continue on errors."""
    cfg = settings or get_settings()
    sandbox_cfg = cfg.model_copy(
        update={"knowledge_hints_enabled": enable_knowledge_hints},
    )
    rows: list[AgenticBatchRunRow] = []

    for room_id in room_ids:
        try:
            ticket = resolve_ticket_for_sandbox(
                room_id,
                replay_jsonl=replay_jsonl,
                redacted_jsonl=redacted_jsonl,
            )
        except ValueError as exc:
            rows.append(
                error_batch_row(
                    room_id,
                    error=f"resolve_ticket: {exc}",
                    knowledge_hints_enabled=enable_knowledge_hints,
                ),
            )
            continue

        if not first_turn_text_from_ticket(ticket).strip():
            rows.append(
                error_batch_row(
                    room_id,
                    error="missing original_vendor_issue_preview",
                    ticket_label=ticket.ticket_label,
                    route_label=ticket.route_label,
                    knowledge_hints_enabled=enable_knowledge_hints,
                ),
            )
            continue

        try:
            initial = initial_state_from_ticket(
                ticket,
                llm_provider=provider,
                llm_model=model,
                generate_fn=generate_fn,
                knowledge_hints_enabled=enable_knowledge_hints,
            )
            final = run_agentic_sandbox_workflow(initial, settings=sandbox_cfg)
            success = (
                final.get("safety_status") == "passed"
                and bool(final.get("draft_reply"))
                and not final.get("errors")
            )
            rows.append(
                state_to_batch_row(
                    final,
                    success=success,
                    knowledge_hints_enabled=enable_knowledge_hints,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            rows.append(
                error_batch_row(
                    room_id,
                    error=f"run_workflow: {exc}",
                    ticket_label=ticket.ticket_label,
                    route_label=ticket.route_label,
                    knowledge_hints_enabled=enable_knowledge_hints,
                ),
            )

    return rows


def summarize_agentic_batch_runs(
    run_rows: Sequence[AgenticBatchRunRow],
    *,
    selection: FirstVendorRoomSelection,
    replay_jsonl: str,
    redacted_jsonl: str | None = None,
    provider: str = "mock",
    limit_applied: int | None = None,
    tracing: LangSmithTracingStatus | None = None,
    generated_at_utc: str | None = None,
    knowledge_hints_enabled: bool = False,
) -> AgenticBatchSummary:
    """Aggregate safe batch metrics."""
    processed = len(run_rows)
    success_count = sum(1 for row in run_rows if row.success)
    error_count = sum(1 for row in run_rows if row.errors)
    safety_passed = sum(1 for row in run_rows if row.safety_status == "passed")
    human_review = sum(1 for row in run_rows if row.human_review_required)
    execution_true = sum(1 for row in run_rows if row.execution_allowed is True)
    customer_send_true = sum(1 for row in run_rows if row.customer_send_allowed is True)
    missing_id = sum(
        1
        for row in run_rows
        if row.actionability_actionable is False
        or (row.missing_required_entities and str(row.missing_required_entities).strip())
    )
    actionable = sum(1 for row in run_rows if row.actionability_actionable is True)

    by_intent: Counter[str] = Counter()
    by_action: Counter[str] = Counter()
    by_actionability: Counter[str] = Counter()
    node_errors: Counter[str] = Counter()
    draft_chars: list[int] = []
    rooms_with_errors: list[str] = []
    by_draft_provider: Counter[str] = Counter()
    quality_rates: list[float | None] = []
    generic_rates: list[float | None] = []
    concise_rates: list[float | None] = []
    fallback_rates: list[float | None] = []
    over_questioning_rates: list[float | None] = []
    unnecessary_clarification_rates: list[float | None] = []
    operational_completion_rates: list[float | None] = []

    for row in run_rows:
        if row.detected_intent:
            by_intent[str(row.detected_intent)] += 1
        if row.suggested_action:
            by_action[str(row.suggested_action)] += 1
        if row.actionability_actionable is True:
            by_actionability["actionable"] += 1
        elif row.actionability_actionable is False:
            by_actionability["missing_identifiers"] += 1
        else:
            by_actionability["unknown"] += 1
        if row.errors:
            rooms_with_errors.append(row.room_id)
        for node, status in row.node_statuses.items():
            if status == "failed":
                node_errors[node] += 1
        if row.draft_char_count > 0:
            draft_chars.append(row.draft_char_count)
        if row.draft_provider:
            by_draft_provider[str(row.draft_provider)] += 1
        if row.openai_draft_quality_rate is not None:
            quality_rates.append(row.openai_draft_quality_rate)
        if row.generic_reply_rate is not None:
            generic_rates.append(row.generic_reply_rate)
        if row.concise_reply_rate is not None:
            concise_rates.append(row.concise_reply_rate)
        if row.fallback_to_mock_rate is not None:
            fallback_rates.append(row.fallback_to_mock_rate)
        if row.over_questioning_rate is not None:
            over_questioning_rates.append(row.over_questioning_rate)
        if row.unnecessary_clarification_rate is not None:
            unnecessary_clarification_rates.append(row.unnecessary_clarification_rate)
        if row.operational_completion_success_rate is not None:
            operational_completion_rates.append(row.operational_completion_success_rate)

    avg_draft = round(sum(draft_chars) / len(draft_chars), 1) if draft_chars else 0.0

    policy_relevant = 0
    policy_with_hints = 0
    for row in run_rows:
        if not _is_policy_relevant_batch_row(row):
            continue
        policy_relevant += 1
        if row.knowledge_hint_count > 0:
            policy_with_hints += 1
    policy_without_hints = policy_relevant - policy_with_hints

    return AgenticBatchSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        replay_jsonl=replay_jsonl,
        redacted_jsonl=redacted_jsonl,
        provider=provider,
        limit_applied=limit_applied,
        total_candidate_rooms=selection.total_candidate_rooms,
        first_vendor_rooms=selection.first_vendor_rooms,
        excluded_support_first=selection.excluded_support_first,
        excluded_no_snapshot=selection.excluded_no_snapshot,
        processed_count=processed,
        success_count=success_count,
        error_count=error_count,
        safety_passed_count=safety_passed,
        human_review_required_count=human_review,
        execution_allowed_true_count=execution_true,
        customer_send_allowed_true_count=customer_send_true,
        missing_identifier_count=missing_id,
        actionable_count=actionable,
        by_detected_intent=dict(sorted(by_intent.items())),
        by_suggested_action=dict(sorted(by_action.items())),
        by_actionability=dict(sorted(by_actionability.items())),
        node_error_counts=dict(sorted(node_errors.items())),
        average_draft_char_count=avg_draft,
        rooms_with_errors=tuple(rooms_with_errors),
        langsmith_tracing_enabled=bool(tracing.enabled) if tracing else False,
        langsmith_project=tracing.project if tracing else None,
        knowledge_hints_enabled=knowledge_hints_enabled,
        knowledge_hint_coverage_rate=_rate(policy_with_hints, policy_relevant),
        policy_relevant_runs=policy_relevant,
        policy_relevant_with_hints=policy_with_hints,
        policy_relevant_without_hints=policy_without_hints,
        by_draft_provider=dict(sorted(by_draft_provider.items())),
        openai_draft_quality_rate=_average_optional(quality_rates),
        generic_reply_rate=_average_optional(generic_rates),
        concise_reply_rate=_average_optional(concise_rates),
        fallback_to_mock_rate=_average_optional(fallback_rates),
        over_questioning_rate=_average_optional(over_questioning_rates),
        unnecessary_clarification_rate=_average_optional(unnecessary_clarification_rates),
        operational_completion_success_rate=_average_optional(operational_completion_rates),
    )


def _recommended_inspection_targets(summary: AgenticBatchSummary) -> list[str]:
    targets: list[str] = []
    if summary.execution_allowed_true_count > 0:
        targets.append(
            "Investigate any row with execution_allowed=true (must remain false).",
        )
    if summary.customer_send_allowed_true_count > 0:
        targets.append(
            "Investigate any row with customer_send_allowed=true (must remain false).",
        )
    if summary.error_count > 0:
        targets.append(
            f"Review {summary.error_count} errored rooms: "
            f"{', '.join(summary.rooms_with_errors[:8])}"
            f"{'…' if len(summary.rooms_with_errors) > 8 else ''}",
        )
    if summary.missing_identifier_count > 0:
        targets.append(
            f"Calibrate identifier-request drafts ({summary.missing_identifier_count} "
            "rooms with missing identifiers).",
        )
    if summary.knowledge_hints_enabled and summary.policy_relevant_without_hints > 0:
        targets.append(
            f"Review {summary.policy_relevant_without_hints} policy-relevant rooms with "
            f"zero hints (coverage {summary.knowledge_hint_coverage_rate:.1%}).",
        )
    weak_actions = sorted(
        summary.by_suggested_action.items(),
        key=lambda item: item[1],
    )
    if weak_actions:
        action, count = weak_actions[-1]
        targets.append(f"Inspect suggested_action `{action}` ({count} rooms in batch).")
    if summary.node_error_counts:
        node, count = max(summary.node_error_counts.items(), key=lambda item: item[1])
        targets.append(f"Node `{node}` failed {count} time(s) — check sandbox wiring.")
    if not targets:
        targets.append(
            "Batch looks healthy at aggregate level — spot-check individual rooms in JSONL."
        )
    return targets


def render_agentic_batch_report_markdown(summary: AgenticBatchSummary) -> str:
    """Render aggregate batch markdown (no transcripts, drafts, or prompts)."""
    lines = [
        "# Agentic Sandbox Batch Report",
        "",
        f"**Generated (UTC):** {summary.generated_at_utc}  ",
        f"**Replay:** `{summary.replay_jsonl}`  ",
    ]
    if summary.redacted_jsonl:
        lines.append(f"**Redacted:** `{summary.redacted_jsonl}`  ")
    lines.extend(
        [
            f"**Provider:** `{summary.provider}`  ",
            "**Scope:** Sandbox observability only — first-vendor rooms, no execution/send.",
            "",
            "## Boundaries",
            "",
            "| Policy | Value |",
            "|--------|-------|",
            "| First-vendor filter | seller/vendor first non-internal sender only |",
            "| `execution_allowed` | must stay **false** |",
            "| `customer_send_allowed` | must stay **false** |",
            "| `human_review_required` | **true** |",
            "| Batch JSONL | no full draft text, no transcripts |",
            "",
            "## First-vendor filtering",
            "",
            f"- **total_candidate_rooms:** {summary.total_candidate_rooms}",
            f"- **first_vendor_rooms (eligible):** {summary.first_vendor_rooms}",
            f"- **excluded_support_first:** {summary.excluded_support_first}",
            f"- **excluded_no_snapshot:** {summary.excluded_no_snapshot}",
            f"- **limit_applied:** "
            f"{summary.limit_applied if summary.limit_applied is not None else 'none'}",
            f"- **processed_count:** {summary.processed_count}",
            "",
            "## Run metrics",
            "",
            f"- **success_count:** {summary.success_count}",
            f"- **error_count:** {summary.error_count}",
            f"- **safety_passed_count:** {summary.safety_passed_count}",
            f"- **average_draft_char_count:** {summary.average_draft_char_count}",
            "",
            "## Knowledge hint coverage",
            "",
            f"- **knowledge_hints_enabled:** {summary.knowledge_hints_enabled}",
            f"- **policy_relevant_runs:** {summary.policy_relevant_runs}",
            f"- **policy_relevant_with_hints:** {summary.policy_relevant_with_hints}",
            f"- **policy_relevant_without_hints:** {summary.policy_relevant_without_hints}",
            f"- **knowledge_hint_coverage_rate:** {summary.knowledge_hint_coverage_rate:.1%}",
            "",
            "## Safety metrics",
            "",
            f"- **human_review_required_count:** {summary.human_review_required_count}",
            f"- **execution_allowed_true_count:** {summary.execution_allowed_true_count}",
            f"- **customer_send_allowed_true_count:** {summary.customer_send_allowed_true_count}",
            "",
            "## Actionability metrics",
            "",
            f"- **actionable_count:** {summary.actionable_count}",
            f"- **missing_identifier_count:** {summary.missing_identifier_count}",
            "",
            "## detected_intent distribution",
            "",
            "| Intent | Count |",
            "|--------|------:|",
        ],
    )
    if summary.by_detected_intent:
        for intent, count in sorted(
            summary.by_detected_intent.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"| `{intent}` | {count} |")
    else:
        lines.append("| *(none)* | 0 |")
    lines.extend(
        ["", "## suggested_action distribution", "", "| Action | Count |", "|--------|------:|"]
    )
    if summary.by_suggested_action:
        for action, count in sorted(
            summary.by_suggested_action.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            lines.append(f"| `{action}` | {count} |")
    else:
        lines.append("| *(none)* | 0 |")
    lines.extend(
        ["", "## actionability distribution", "", "| Bucket | Count |", "|--------|------:|"]
    )
    for bucket, count in summary.by_actionability.items():
        lines.append(f"| {bucket} | {count} |")
    lines.extend(["", "## Node errors", ""])
    if summary.node_error_counts:
        for node, count in summary.node_error_counts.items():
            lines.append(f"- `{node}`: {count}")
    else:
        lines.append("*(No node failures recorded.)*")
    lines.extend(["", "## Recommended next inspection targets", ""])
    for index, target in enumerate(_recommended_inspection_targets(summary), start=1):
        lines.append(f"{index}. {target}")
    if summary.langsmith_tracing_enabled:
        lines.extend(
            [
                "",
                "## LangSmith",
                "",
                f"- Tracing enabled for batch (project: `{summary.langsmith_project}`).",
            ],
        )
    lines.extend(
        [
            "",
            "## Governance",
            "",
            "- Per-room details: `reports/agentic_sandbox_batch_runs.jsonl` (counts only).",
            "- Not wired to operator console or production graph.",
            "",
        ],
    )
    return "\n".join(lines)


def assert_batch_output_safe(content: str) -> None:
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"batch output must not contain forbidden token: {token}")
    for token in (
        "conversation transcript",
        "gold_reference_reply",
        '"messages"',
        '"snippet":',
        "retrieved_context",
    ):
        if token in lowered:
            raise ValueError(f"batch output must not contain forbidden token: {token}")


def write_batch_outputs(
    run_rows: Sequence[AgenticBatchRunRow],
    summary: AgenticBatchSummary,
    *,
    runs_jsonl: Path = DEFAULT_BATCH_RUNS_JSONL,
    summary_json: Path = DEFAULT_BATCH_SUMMARY_JSON,
    report_md: Path = DEFAULT_BATCH_REPORT_MD,
) -> tuple[Path, Path, Path]:
    """Write JSONL rows, JSON summary, and markdown report."""
    runs_jsonl.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    report_md.parent.mkdir(parents=True, exist_ok=True)

    jsonl_lines = [json.dumps(row.to_json_dict(), ensure_ascii=False) for row in run_rows]
    jsonl_text = "\n".join(jsonl_lines) + ("\n" if jsonl_lines else "")
    summary_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    markdown = render_agentic_batch_report_markdown(summary)

    assert_batch_output_safe(jsonl_text)
    assert_batch_output_safe(summary_text)
    assert_batch_output_safe(markdown)

    runs_jsonl.write_text(jsonl_text, encoding="utf-8")
    summary_json.write_text(summary_text, encoding="utf-8")
    report_md.write_text(markdown, encoding="utf-8")
    return runs_jsonl, summary_json, report_md


def build_agentic_batch_report(
    *,
    replay_jsonl: Path | str,
    redacted_jsonl: Path | str | None = None,
    settings: AppSettings | None = None,
    provider: str = "mock",
    model: str | None = None,
    generate_fn: Any | None = None,
    limit: int | None = None,
    enable_langsmith: bool = False,
    langsmith_project: str | None = None,
    enable_knowledge_hints: bool = False,
    runs_jsonl: Path = DEFAULT_BATCH_RUNS_JSONL,
    summary_json: Path = DEFAULT_BATCH_SUMMARY_JSON,
    report_md: Path = DEFAULT_BATCH_REPORT_MD,
) -> AgenticBatchSummary:
    """Full batch pipeline: select rooms, run graph, summarize, write outputs."""
    cfg = settings or get_settings()
    model_name = (
        (model or cfg.openai_draft_model or "gpt-4o-mini").strip()
        if provider.strip().lower() == "openai"
        else (model or "mock-vendor-ticket-drafter").strip()
    )
    replay_str = str(replay_jsonl)
    redacted_str = str(redacted_jsonl) if redacted_jsonl is not None else None

    tracing = configure_agentic_sandbox_langsmith_tracing(
        enabled=enable_langsmith,
        project=langsmith_project,
        settings=cfg,
    )

    selection = load_first_vendor_room_ids(
        replay_jsonl,
        redacted_jsonl=redacted_jsonl,
        limit=limit,
    )
    run_rows = run_agentic_sandbox_batch(
        selection.room_ids,
        replay_jsonl=replay_jsonl,
        redacted_jsonl=redacted_jsonl,
        settings=cfg,
        provider=provider,
        model=model_name,
        generate_fn=generate_fn,
        enable_knowledge_hints=enable_knowledge_hints,
    )
    summary = summarize_agentic_batch_runs(
        run_rows,
        selection=selection,
        replay_jsonl=replay_str,
        redacted_jsonl=redacted_str,
        provider=provider,
        limit_applied=limit,
        tracing=tracing,
        knowledge_hints_enabled=enable_knowledge_hints,
    )
    write_batch_outputs(
        run_rows, summary, runs_jsonl=runs_jsonl, summary_json=summary_json, report_md=report_md
    )
    return summary
