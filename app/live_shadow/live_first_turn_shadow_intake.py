"""Live first-turn shadow intake — agentic graph on live tickets (read-only, no send/execute)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.agentic_sandbox.agentic_batch_report import (
    assert_batch_output_safe,
    error_batch_row,
    state_to_batch_row,
)
from app.agentic_sandbox.agentic_graph import (
    initial_state_from_ticket,
    run_agentic_sandbox_workflow,
)
from app.agentic_sandbox.policy_relevance import is_policy_relevant_signals
from app.config import AppSettings, get_settings
from app.evals.first_turn_draft_context import first_turn_text_from_ticket
from app.live_feed.open_ticket_snapshot import (
    build_open_ticket_snapshot,
    extract_full_first_vendor_message,
)
from app.live_feed.ticket_feed_adapter import fetch_recent_vendor_tickets
from app.live_feed.ticket_models import LiveVendorTicket
from app.operator_console.console_models import OperatorTicket
from app.operator_console.draft_review_feedback import _FORBIDDEN_TEXT_SUBSTRINGS
from app.operator_console.first_vendor_filter import (
    first_meaningful_sender_type,
    is_first_vendor_ticket,
)
from app.tickets.conversation_models import ConversationMessage, ConversationTicketSnapshot

DEFAULT_LIVE_SHADOW_RUNS_JSONL = Path("reports/live_shadow_first_turn_runs.jsonl")
DEFAULT_LIVE_SHADOW_SUMMARY_JSON = Path("reports/live_shadow_first_turn_summary.json")

_SUPPORT_SENDERS = frozenset({"support_agent", "finance_agent"})
_INTERNAL_FIRST_SENDERS = frozenset({"system", "unknown"})
_OPEN_TICKET_STATUSES = frozenset({"open", "new", "pending", "pending_review", "pending-review"})
_FORBIDDEN_ROW_KEYS = frozenset(
    {
        "draft_reply",
        "messages",
        "user_input",
        "full_first_vendor_message_text",
        "first_turn_extraction_text",
        "first_turn_text",
        "raw_prompt",
        "retrieved_context",
        "conversation_transcript",
        "transcript",
        "gold_reference_reply",
    },
)


@dataclass(frozen=True)
class LiveShadowFilterStats:
    """Counts from first-turn shadow eligibility filtering."""

    total_live_seen: int
    eligible_first_turn: int
    skipped_multi_turn: int
    skipped_support_started: int
    skipped_internal_started: int
    skipped_closed: int
    skipped_not_first_vendor: int
    skipped_missing_snapshot: int
    skipped_missing_first_turn: int
    skipped_not_open_status: int
    skipped_already_processed: int


@dataclass(frozen=True)
class LiveFirstTurnShadowRow:
    """Safe per-ticket live shadow graph result (no draft body or transcript)."""

    room_id: str
    shadow_processed_at_utc: str
    first_turn_signature: str
    intake_source: str
    provider: str
    processing_latency_ms: int
    live_ticket_updated_at_utc: str | None
    ticket_status: str | None
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

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "room_id": self.room_id,
            "shadow_processed_at_utc": self.shadow_processed_at_utc,
            "first_turn_signature": self.first_turn_signature,
            "intake_source": self.intake_source,
            "provider": self.provider,
            "processing_latency_ms": self.processing_latency_ms,
            "live_ticket_updated_at_utc": self.live_ticket_updated_at_utc,
            "ticket_status": self.ticket_status,
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
        }


@dataclass
class LiveFirstTurnShadowSummary:
    """Aggregate metrics for one live shadow intake run."""

    generated_at_utc: str
    intake_source: str
    live_feed_source: str
    provider: str
    knowledge_hints_enabled: bool
    limit_applied: int | None
    since_hours: float | None
    dedupe_enabled: bool
    dry_run: bool
    total_live_seen: int
    eligible_first_turn: int
    skipped_multi_turn: int
    skipped_support_started: int
    skipped_internal_started: int
    skipped_closed: int
    skipped_not_first_vendor: int
    skipped_missing_snapshot: int
    skipped_missing_first_turn: int
    skipped_not_open_status: int
    skipped_already_processed: int
    processed_count: int
    graph_success_count: int
    graph_success_rate: float
    safety_pass_count: int
    safety_pass_rate: float
    average_latency_ms: float
    missing_identifier_count: int
    missing_identifier_rate: float
    draft_generation_count: int
    draft_generation_rate: float
    policy_relevant_runs: int = 0
    policy_relevant_with_hints: int = 0
    knowledge_hint_coverage_rate: float = 0.0
    execution_allowed_true_count: int = 0
    customer_send_allowed_true_count: int = 0
    rooms_with_errors: tuple[str, ...] = ()
    runs_jsonl: str = ""
    by_detected_intent: dict[str, int] = field(default_factory=dict)
    by_suggested_action: dict[str, int] = field(default_factory=dict)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "generated_at_utc": self.generated_at_utc,
            "intake_source": self.intake_source,
            "live_feed_source": self.live_feed_source,
            "provider": self.provider,
            "knowledge_hints_enabled": self.knowledge_hints_enabled,
            "limit_applied": self.limit_applied,
            "since_hours": self.since_hours,
            "dedupe_enabled": self.dedupe_enabled,
            "dry_run": self.dry_run,
            "total_live_seen": self.total_live_seen,
            "eligible_first_turn": self.eligible_first_turn,
            "skipped_multi_turn": self.skipped_multi_turn,
            "skipped_support_started": self.skipped_support_started,
            "skipped_internal_started": self.skipped_internal_started,
            "skipped_closed": self.skipped_closed,
            "skipped_not_first_vendor": self.skipped_not_first_vendor,
            "skipped_missing_snapshot": self.skipped_missing_snapshot,
            "skipped_missing_first_turn": self.skipped_missing_first_turn,
            "skipped_not_open_status": self.skipped_not_open_status,
            "skipped_already_processed": self.skipped_already_processed,
            "processed_count": self.processed_count,
            "graph_success_count": self.graph_success_count,
            "graph_success_rate": self.graph_success_rate,
            "safety_pass_count": self.safety_pass_count,
            "safety_pass_rate": self.safety_pass_rate,
            "average_latency_ms": self.average_latency_ms,
            "missing_identifier_count": self.missing_identifier_count,
            "missing_identifier_rate": self.missing_identifier_rate,
            "draft_generation_count": self.draft_generation_count,
            "draft_generation_rate": self.draft_generation_rate,
            "policy_relevant_runs": self.policy_relevant_runs,
            "policy_relevant_with_hints": self.policy_relevant_with_hints,
            "knowledge_hint_coverage_rate": self.knowledge_hint_coverage_rate,
            "execution_allowed_true_count": self.execution_allowed_true_count,
            "customer_send_allowed_true_count": self.customer_send_allowed_true_count,
            "rooms_with_errors": list(self.rooms_with_errors),
            "runs_jsonl": self.runs_jsonl,
            "by_detected_intent": dict(self.by_detected_intent),
            "by_suggested_action": dict(self.by_suggested_action),
        }


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _sanitize_shadow_errors(errors: Sequence[str]) -> tuple[str, ...]:
    """Redact credential-like substrings from persisted error messages."""
    redacted: list[str] = []
    sensitive_markers = (
        "openai_api_key",
        "api_key",
        "sk-",
        "postgresql://",
        "begin private key",
    )
    for error in errors:
        text = str(error).strip()
        if not text:
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in sensitive_markers):
            redacted.append("workflow_error_redacted")
        else:
            redacted.append(text[:500])
    return tuple(redacted)


def _first_vendor_message(snapshot: ConversationTicketSnapshot) -> ConversationMessage | None:
    for message in snapshot.messages:
        if message.sender_type in {"seller", "vendor"}:
            return message
    return None


def compute_first_turn_signature(ticket: LiveVendorTicket) -> str:
    """Stable signature for dedupe (room + first vendor message identity)."""
    snapshot = ticket.snapshot
    if snapshot is None:
        return hashlib.sha256(ticket.room_id.encode()).hexdigest()[:16]
    first = _first_vendor_message(snapshot)
    parts = [ticket.room_id]
    if first is not None:
        parts.append(first.message_id)
        if first.timestamp is not None:
            parts.append(first.timestamp.isoformat())
        parts.append(first.text[:120])
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:16]


def _has_support_reply(snapshot: ConversationTicketSnapshot) -> bool:
    return any(message.sender_type in _SUPPORT_SENDERS for message in snapshot.messages)


def _is_closed_ticket(snapshot: ConversationTicketSnapshot) -> bool:
    if snapshot.closed_at is not None:
        return True
    status = (snapshot.status or "").strip().lower()
    return status in {"closed", "resolved", "cancelled"}


def _is_open_ticket(snapshot: ConversationTicketSnapshot) -> bool:
    if _is_closed_ticket(snapshot):
        return False
    status = (snapshot.status or "").strip().lower()
    if not status:
        return True
    return status in _OPEN_TICKET_STATUSES or "pending" in status or status == "open"


def operator_ticket_from_live_ticket(ticket: LiveVendorTicket) -> OperatorTicket:
    """Build HITL-safe operator ticket from live snapshot (redacted open-ticket path)."""
    if ticket.snapshot is None:
        raise ValueError(f"live ticket {ticket.room_id}: snapshot required")
    snapshot = ticket.snapshot
    open_snap = build_open_ticket_snapshot(snapshot)
    full_first = extract_full_first_vendor_message(snapshot)
    return OperatorTicket(
        room_id=ticket.room_id,
        ticket_label=ticket.ticket_label or snapshot.ticket_label,
        route_label=None,
        assigned_department=ticket.assigned_department,
        review_priority=ticket.review_priority,
        suggested_action=None,
        suggested_priority=None,
        escalation_recommended=None,
        duplicate_possible=None,
        confidence_band=None,
        retrieval_gate_decision=None,
        retrieval_result_count=None,
        ticket_text_preview=open_snap.open_ticket_preview,
        open_ticket_preview=open_snap.open_ticket_preview,
        original_vendor_issue_preview=open_snap.original_vendor_issue_preview,
        latest_vendor_message=open_snap.latest_vendor_message,
        recent_context_preview=open_snap.recent_context_preview,
        full_first_vendor_message_text=full_first,
    )


def load_live_candidate_tickets(
    source_path: Path | str,
    *,
    limit: int | None = None,
    since_hours: float | None = None,
) -> list[LiveVendorTicket]:
    """Load recent live tickets from the configured JSONL feed."""
    tickets = fetch_recent_vendor_tickets(source_path, limit=limit or 10_000)
    if since_hours is not None and since_hours > 0:
        cutoff = datetime.now(tz=UTC) - timedelta(hours=since_hours)
        tickets = [
            ticket
            for ticket in tickets
            if ticket.updated_at is not None and ticket.updated_at >= cutoff
        ]
    if limit is not None and limit > 0:
        tickets = tickets[:limit]
    return tickets


def classify_shadow_eligibility(
    ticket: LiveVendorTicket,
    *,
    processed_keys: set[tuple[str, str]] | None = None,
    dedupe: bool = True,
) -> tuple[bool, str | None]:
    """Return (eligible, skip_reason) for one live ticket."""
    snapshot = ticket.snapshot
    if snapshot is None:
        return False, "missing_snapshot"
    if _is_closed_ticket(snapshot):
        return False, "closed_ticket"
    if not _is_open_ticket(snapshot):
        return False, "not_open_status"
    first = first_meaningful_sender_type(snapshot.messages)
    if first in _SUPPORT_SENDERS:
        return False, "support_started"
    if first in _INTERNAL_FIRST_SENDERS or first is None:
        return False, "internal_started"
    if not is_first_vendor_ticket(snapshot):
        return False, "not_first_vendor"
    if _has_support_reply(snapshot):
        return False, "multi_turn"
    open_snap = build_open_ticket_snapshot(snapshot)
    if not open_snap.original_vendor_issue_preview:
        return False, "missing_first_turn"
    if dedupe and processed_keys is not None:
        signature = compute_first_turn_signature(ticket)
        if (ticket.room_id, signature) in processed_keys:
            return False, "already_processed"
    return True, None


def filter_first_turn_shadow_eligible(
    tickets: Sequence[LiveVendorTicket],
    *,
    processed_keys: set[tuple[str, str]] | None = None,
    dedupe: bool = True,
) -> tuple[list[LiveVendorTicket], LiveShadowFilterStats]:
    """Filter live tickets to first-turn seller-initiated shadow scope."""
    eligible: list[LiveVendorTicket] = []
    stats = {
        "skipped_multi_turn": 0,
        "skipped_support_started": 0,
        "skipped_internal_started": 0,
        "skipped_closed": 0,
        "skipped_not_first_vendor": 0,
        "skipped_missing_snapshot": 0,
        "skipped_missing_first_turn": 0,
        "skipped_not_open_status": 0,
        "skipped_already_processed": 0,
    }
    for ticket in tickets:
        ok, reason = classify_shadow_eligibility(
            ticket,
            processed_keys=processed_keys,
            dedupe=dedupe,
        )
        if ok:
            eligible.append(ticket)
            continue
        if reason == "multi_turn":
            stats["skipped_multi_turn"] += 1
        elif reason == "support_started":
            stats["skipped_support_started"] += 1
        elif reason in {"internal_started", "missing_snapshot"}:
            stats["skipped_internal_started"] += int(reason == "internal_started")
            stats["skipped_missing_snapshot"] += int(reason == "missing_snapshot")
        elif reason == "closed_ticket":
            stats["skipped_closed"] += 1
        elif reason == "not_open_status":
            stats["skipped_not_open_status"] += 1
        elif reason == "not_first_vendor":
            stats["skipped_not_first_vendor"] += 1
        elif reason == "missing_first_turn":
            stats["skipped_missing_first_turn"] += 1
        elif reason == "already_processed":
            stats["skipped_already_processed"] += 1
    return eligible, LiveShadowFilterStats(
        total_live_seen=len(tickets),
        eligible_first_turn=len(eligible),
        **stats,
    )


def build_shadow_processing_batch(
    eligible: Sequence[LiveVendorTicket],
    *,
    limit: int | None = None,
) -> list[LiveVendorTicket]:
    """Cap eligible tickets for one intake run."""
    batch = list(eligible)
    if limit is not None and limit > 0:
        batch = batch[:limit]
    return batch


def load_shadow_dedupe_keys(runs_jsonl: Path) -> set[tuple[str, str]]:
    """Load (room_id, first_turn_signature) keys from prior shadow runs."""
    if not runs_jsonl.is_file():
        return set()
    keys: set[tuple[str, str]] = set()
    for line in runs_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        room_id = row.get("room_id")
        signature = row.get("first_turn_signature")
        if isinstance(room_id, str) and isinstance(signature, str):
            keys.add((room_id, signature))
    return keys


def build_shadow_result_row(
    batch_row: Any,
    *,
    shadow_processed_at_utc: str,
    first_turn_signature: str,
    provider: str,
    processing_latency_ms: int,
    live_ticket_updated_at_utc: str | None,
    ticket_status: str | None,
    intake_source: str = "live",
) -> LiveFirstTurnShadowRow:
    """Wrap safe batch row with live shadow metadata."""
    return LiveFirstTurnShadowRow(
        room_id=batch_row.room_id,
        shadow_processed_at_utc=shadow_processed_at_utc,
        first_turn_signature=first_turn_signature,
        intake_source=intake_source,
        provider=provider,
        processing_latency_ms=processing_latency_ms,
        live_ticket_updated_at_utc=live_ticket_updated_at_utc,
        ticket_status=ticket_status,
        ticket_label=batch_row.ticket_label,
        route_label=batch_row.route_label,
        node_statuses=dict(batch_row.node_statuses),
        safety_status=batch_row.safety_status,
        detected_intent=batch_row.detected_intent,
        conceptual_intent_fa=batch_row.conceptual_intent_fa,
        suggested_action=batch_row.suggested_action,
        actionability_actionable=batch_row.actionability_actionable,
        missing_required_entities=batch_row.missing_required_entities,
        order_id_count=batch_row.order_id_count,
        product_id_count=batch_row.product_id_count,
        has_tracking_code=batch_row.has_tracking_code,
        knowledge_hints_enabled=batch_row.knowledge_hints_enabled,
        knowledge_hint_count=batch_row.knowledge_hint_count,
        knowledge_hint_document_types=tuple(batch_row.knowledge_hint_document_types),
        draft_char_count=batch_row.draft_char_count,
        human_review_required=batch_row.human_review_required,
        execution_allowed=batch_row.execution_allowed,
        customer_send_allowed=batch_row.customer_send_allowed,
        success=batch_row.success,
        errors=_sanitize_shadow_errors(batch_row.errors),
        entity_extraction_source=batch_row.entity_extraction_source,
        entity_extraction_source_char_count=batch_row.entity_extraction_source_char_count,
        display_preview_char_count=batch_row.display_preview_char_count,
    )


def run_shadow_graph_for_ticket(
    ticket: LiveVendorTicket,
    *,
    settings: AppSettings | None = None,
    provider: str = "mock",
    model: str = "mock-vendor-ticket-drafter",
    generate_fn: Any | None = None,
    enable_knowledge_hints: bool = False,
) -> tuple[LiveFirstTurnShadowRow, dict[str, Any]]:
    """Run agentic sandbox graph for one live ticket; return safe row + final state."""
    cfg = settings or get_settings()
    sandbox_cfg = cfg.model_copy(update={"knowledge_hints_enabled": enable_knowledge_hints})
    processed_at = _utc_now_iso()
    signature = compute_first_turn_signature(ticket)
    snapshot = ticket.snapshot
    ticket_status = None
    if snapshot is not None:
        ticket_status = snapshot.status or ("closed" if snapshot.closed_at else "open")
    live_updated = ticket.updated_at.isoformat() if ticket.updated_at else None

    start = time.perf_counter()
    try:
        operator_ticket = operator_ticket_from_live_ticket(ticket)
    except ValueError as exc:
        batch_row = error_batch_row(
            ticket.room_id,
            error=f"operator_ticket: {exc}",
            ticket_label=ticket.ticket_label,
            knowledge_hints_enabled=enable_knowledge_hints,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        row = build_shadow_result_row(
            batch_row,
            shadow_processed_at_utc=processed_at,
            first_turn_signature=signature,
            provider=provider,
            processing_latency_ms=latency_ms,
            live_ticket_updated_at_utc=live_updated,
            ticket_status=ticket_status,
        )
        assert_live_shadow_row_safe(row)
        return row, {}

    if not first_turn_text_from_ticket(operator_ticket).strip():
        batch_row = error_batch_row(
            ticket.room_id,
            error="missing original_vendor_issue_preview",
            ticket_label=operator_ticket.ticket_label,
            knowledge_hints_enabled=enable_knowledge_hints,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)
        row = build_shadow_result_row(
            batch_row,
            shadow_processed_at_utc=processed_at,
            first_turn_signature=signature,
            provider=provider,
            processing_latency_ms=latency_ms,
            live_ticket_updated_at_utc=live_updated,
            ticket_status=ticket_status,
        )
        assert_live_shadow_row_safe(row)
        return row, {}

    try:
        initial = initial_state_from_ticket(
            operator_ticket,
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
        batch_row = state_to_batch_row(
            final,
            success=success,
            knowledge_hints_enabled=enable_knowledge_hints,
        )
    except Exception as exc:  # noqa: BLE001
        batch_row = error_batch_row(
            ticket.room_id,
            error=f"run_workflow: {exc}",
            ticket_label=operator_ticket.ticket_label,
            knowledge_hints_enabled=enable_knowledge_hints,
        )
        final = {}

    latency_ms = int((time.perf_counter() - start) * 1000)
    row = build_shadow_result_row(
        batch_row,
        shadow_processed_at_utc=processed_at,
        first_turn_signature=signature,
        provider=provider,
        processing_latency_ms=latency_ms,
        live_ticket_updated_at_utc=live_updated,
        ticket_status=ticket_status,
    )
    assert_live_shadow_row_safe(row)
    _assert_shadow_safety_flags(row)
    return row, final if isinstance(final, dict) else {}


def assert_live_shadow_row_safe(row: LiveFirstTurnShadowRow) -> None:
    """Fail closed if a shadow row contains forbidden keys or content."""
    payload = json.dumps(row.to_json_dict(), ensure_ascii=False)
    assert_live_shadow_output_safe(payload)
    for key in row.to_json_dict():
        if key in _FORBIDDEN_ROW_KEYS:
            raise ValueError(f"live shadow row must not contain key: {key}")


def assert_live_shadow_output_safe(content: str) -> None:
    """Fail closed on transcript/prompt/snippet leakage in persisted output."""
    assert_batch_output_safe(content)
    lowered = content.lower()
    for token in _FORBIDDEN_TEXT_SUBSTRINGS:
        if token.lower() in lowered:
            raise ValueError(f"live shadow output must not contain forbidden token: {token}")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return
    rows = parsed if isinstance(parsed, list) else [parsed]
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key in row:
            if key in _FORBIDDEN_ROW_KEYS:
                raise ValueError(f"live shadow output must not contain forbidden key: {key}")


def _assert_shadow_safety_flags(row: LiveFirstTurnShadowRow) -> None:
    if not row.human_review_required:
        raise ValueError("live shadow requires human_review_required=true")
    if row.execution_allowed:
        raise ValueError("live shadow requires execution_allowed=false")
    if row.customer_send_allowed:
        raise ValueError("live shadow requires customer_send_allowed=false")


def write_shadow_batch_jsonl(
    rows: Sequence[LiveFirstTurnShadowRow],
    *,
    runs_jsonl: Path = DEFAULT_LIVE_SHADOW_RUNS_JSONL,
    append: bool = True,
) -> Path:
    """Write safe shadow rows to JSONL (append by default)."""
    runs_jsonl.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row.to_json_dict(), ensure_ascii=False) for row in rows]
    text_block = "\n".join(lines) + ("\n" if lines else "")
    for line in lines:
        assert_live_shadow_output_safe(line)
    if append and runs_jsonl.is_file() and text_block:
        existing = runs_jsonl.read_text(encoding="utf-8")
        if existing and not existing.endswith("\n"):
            runs_jsonl.write_text(existing + "\n" + text_block, encoding="utf-8")
        else:
            with runs_jsonl.open("a", encoding="utf-8") as handle:
                handle.write(text_block)
    else:
        runs_jsonl.write_text(text_block, encoding="utf-8")
    return runs_jsonl


def summarize_live_shadow_runs(
    rows: Sequence[LiveFirstTurnShadowRow],
    *,
    filter_stats: LiveShadowFilterStats,
    live_feed_source: str,
    provider: str,
    knowledge_hints_enabled: bool,
    limit_applied: int | None,
    since_hours: float | None,
    dedupe_enabled: bool,
    dry_run: bool,
    runs_jsonl: Path,
    generated_at_utc: str | None = None,
) -> LiveFirstTurnShadowSummary:
    """Aggregate live shadow intake metrics."""
    processed = len(rows)
    graph_success = sum(1 for row in rows if row.success)
    safety_pass = sum(1 for row in rows if row.safety_status == "passed")
    latencies = [row.processing_latency_ms for row in rows]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0.0
    missing_id = sum(
        1
        for row in rows
        if row.actionability_actionable is False
        or (row.missing_required_entities and str(row.missing_required_entities).strip())
    )
    draft_generated = sum(1 for row in rows if row.draft_char_count > 0)
    execution_true = sum(1 for row in rows if row.execution_allowed)
    customer_send_true = sum(1 for row in rows if row.customer_send_allowed)
    rooms_with_errors = tuple(row.room_id for row in rows if row.errors)

    by_intent: dict[str, int] = {}
    by_action: dict[str, int] = {}
    policy_relevant = 0
    policy_with_hints = 0
    for row in rows:
        if row.detected_intent:
            by_intent[row.detected_intent] = by_intent.get(row.detected_intent, 0) + 1
        if row.suggested_action:
            by_action[row.suggested_action] = by_action.get(row.suggested_action, 0) + 1
        if is_policy_relevant_signals(
            detected_intent=row.detected_intent,
            conceptual_intent_fa=row.conceptual_intent_fa,
            suggested_action=row.suggested_action,
            ticket_label=row.ticket_label,
            route_label=row.route_label,
        ):
            policy_relevant += 1
            if row.knowledge_hint_count > 0:
                policy_with_hints += 1

    return LiveFirstTurnShadowSummary(
        generated_at_utc=generated_at_utc or _utc_now_iso(),
        intake_source="live",
        live_feed_source=live_feed_source,
        provider=provider,
        knowledge_hints_enabled=knowledge_hints_enabled,
        limit_applied=limit_applied,
        since_hours=since_hours,
        dedupe_enabled=dedupe_enabled,
        dry_run=dry_run,
        total_live_seen=filter_stats.total_live_seen,
        eligible_first_turn=filter_stats.eligible_first_turn,
        skipped_multi_turn=filter_stats.skipped_multi_turn,
        skipped_support_started=filter_stats.skipped_support_started,
        skipped_internal_started=filter_stats.skipped_internal_started,
        skipped_closed=filter_stats.skipped_closed,
        skipped_not_first_vendor=filter_stats.skipped_not_first_vendor,
        skipped_missing_snapshot=filter_stats.skipped_missing_snapshot,
        skipped_missing_first_turn=filter_stats.skipped_missing_first_turn,
        skipped_not_open_status=filter_stats.skipped_not_open_status,
        skipped_already_processed=filter_stats.skipped_already_processed,
        processed_count=processed,
        graph_success_count=graph_success,
        graph_success_rate=_rate(graph_success, processed),
        safety_pass_count=safety_pass,
        safety_pass_rate=_rate(safety_pass, processed),
        average_latency_ms=avg_latency,
        missing_identifier_count=missing_id,
        missing_identifier_rate=_rate(missing_id, processed),
        draft_generation_count=draft_generated,
        draft_generation_rate=_rate(draft_generated, processed),
        policy_relevant_runs=policy_relevant,
        policy_relevant_with_hints=policy_with_hints,
        knowledge_hint_coverage_rate=_rate(policy_with_hints, policy_relevant),
        execution_allowed_true_count=execution_true,
        customer_send_allowed_true_count=customer_send_true,
        rooms_with_errors=rooms_with_errors,
        runs_jsonl=str(runs_jsonl),
        by_detected_intent=by_intent,
        by_suggested_action=by_action,
    )


def is_live_shadow_intake_recently_active(
    summary_path: Path | str = DEFAULT_LIVE_SHADOW_SUMMARY_JSON,
    *,
    within_hours: float = 24.0,
) -> bool:
    """True when a live shadow summary was generated recently (console indicator)."""
    path = Path(summary_path)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict) or data.get("intake_source") != "live":
        return False
    generated = _parse_timestamp(data.get("generated_at_utc"))
    if generated is None:
        return False
    return generated >= datetime.now(tz=UTC) - timedelta(hours=within_hours)


def run_live_first_turn_shadow_intake(
    *,
    source_path: Path | str | None = None,
    runs_jsonl: Path = DEFAULT_LIVE_SHADOW_RUNS_JSONL,
    summary_json: Path = DEFAULT_LIVE_SHADOW_SUMMARY_JSON,
    settings: AppSettings | None = None,
    provider: str = "mock",
    model: str | None = None,
    generate_fn: Any | None = None,
    limit: int | None = 25,
    since_hours: float | None = None,
    enable_knowledge_hints: bool = False,
    dedupe: bool = True,
    dry_run: bool = False,
    overwrite: bool = False,
) -> LiveFirstTurnShadowSummary:
    """Load live tickets, filter, run shadow graph, persist safe artifacts."""
    cfg = settings or get_settings()
    feed_path = Path(source_path or cfg.live_feed_source_path)
    model_name = model or cfg.llm_model

    if summary_json.exists() and not overwrite:
        raise FileExistsError(
            f"live shadow summary exists: {summary_json} (use --overwrite)",
        )

    if overwrite and not dry_run:
        runs_jsonl.parent.mkdir(parents=True, exist_ok=True)
        runs_jsonl.write_text("", encoding="utf-8")

    candidates = load_live_candidate_tickets(
        feed_path,
        limit=10_000,
        since_hours=since_hours,
    )
    processed_keys = load_shadow_dedupe_keys(runs_jsonl) if dedupe else set()
    eligible, filter_stats = filter_first_turn_shadow_eligible(
        candidates,
        processed_keys=processed_keys,
        dedupe=dedupe,
    )
    batch = build_shadow_processing_batch(eligible, limit=limit)

    rows: list[LiveFirstTurnShadowRow] = []
    if not dry_run:
        for ticket in batch:
            row, _ = run_shadow_graph_for_ticket(
                ticket,
                settings=cfg,
                provider=provider,
                model=model_name,
                generate_fn=generate_fn,
                enable_knowledge_hints=enable_knowledge_hints,
            )
            rows.append(row)

    summary = summarize_live_shadow_runs(
        rows,
        filter_stats=filter_stats,
        live_feed_source=str(feed_path),
        provider=provider,
        knowledge_hints_enabled=enable_knowledge_hints,
        limit_applied=limit,
        since_hours=since_hours,
        dedupe_enabled=dedupe,
        dry_run=dry_run,
        runs_jsonl=runs_jsonl,
    )

    if not dry_run and rows:
        write_shadow_batch_jsonl(
            rows,
            runs_jsonl=runs_jsonl,
            append=not overwrite,
        )

    summary_text = json.dumps(summary.to_json_dict(), ensure_ascii=False, indent=2) + "\n"
    assert_live_shadow_output_safe(summary_text)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    summary_json.write_text(summary_text, encoding="utf-8")
    return summary
