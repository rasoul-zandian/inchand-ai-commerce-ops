"""Data models for the internal operator console (aggregate fields only)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.operator_console.knowledge_hints import KnowledgeHint


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class OperatorTicket:
    """One ticket row for operator review (HITL-safe aggregate fields only)."""

    room_id: str
    ticket_label: str | None
    route_label: str | None
    assigned_department: str | None
    review_priority: str | None
    suggested_action: str | None
    suggested_priority: str | None
    escalation_recommended: bool | None
    duplicate_possible: bool | None
    confidence_band: str | None
    retrieval_gate_decision: str | None
    retrieval_result_count: int | None
    ticket_text_preview: str | None
    open_ticket_preview: str | None
    original_vendor_issue_preview: str | None
    latest_vendor_message: str | None
    recent_context_preview: str | None
    seller_notification_detected: bool | None = None
    seller_intent_type: str | None = None
    seller_notification_type: str | None = None
    seller_operational_request_type: str | None = None
    extracted_order_id: str | None = None
    extracted_order_ids: str | None = None
    extracted_tracking_code: str | None = None
    extracted_product_ids: str | None = None
    extracted_tracking_carrier: str | None = None
    extracted_iban: str | None = None
    extracted_iban_masked: str | None = None
    entity_warnings_summary: str | None = None
    seller_notification_shipment_status: str | None = None
    detected_intent: str | None = None
    intent_confidence_band: str | None = None
    intent_reasons_summary: str | None = None
    intent_related_document_types: str | None = None
    suggested_action_reason: str | None = None
    knowledge_hints: tuple[KnowledgeHint, ...] = field(default_factory=tuple)
    full_first_vendor_message_text: str | None = None

    def with_knowledge_hints(
        self,
        hints: tuple[KnowledgeHint, ...] | list[KnowledgeHint],
    ) -> OperatorTicket:
        """Return a copy of this ticket with attached read-only knowledge hints."""
        return replace(self, knowledge_hints=tuple(hints))

    @classmethod
    def from_hitl_payload(cls, payload: Mapping[str, Any]) -> OperatorTicket:
        room_id = _optional_str(payload.get("room_id"))
        if not room_id:
            raise ValueError("HITL payload requires room_id")
        return cls(
            room_id=room_id,
            ticket_label=_optional_str(payload.get("ticket_label")),
            route_label=_optional_str(payload.get("route_label")),
            assigned_department=_optional_str(payload.get("assigned_department")),
            review_priority=_optional_str(payload.get("review_priority")),
            suggested_action=_optional_str(payload.get("ai_assist_suggested_action")),
            suggested_action_reason=_optional_str(
                payload.get("ai_assist_suggested_action_reason"),
            ),
            suggested_priority=_optional_str(payload.get("ai_assist_suggested_priority")),
            escalation_recommended=_optional_bool(payload.get("ai_assist_escalation_recommended")),
            duplicate_possible=_optional_bool(payload.get("ai_assist_duplicate_possible")),
            confidence_band=_optional_str(payload.get("ai_assist_confidence_band")),
            retrieval_gate_decision=_optional_str(payload.get("retrieval_gate_decision")),
            retrieval_result_count=_optional_int(payload.get("retrieval_result_count")),
            ticket_text_preview=_optional_str(payload.get("ticket_text_preview")),
            open_ticket_preview=_optional_str(payload.get("open_ticket_preview")),
            original_vendor_issue_preview=_optional_str(
                payload.get("original_vendor_issue_preview"),
            ),
            latest_vendor_message=_optional_str(payload.get("latest_vendor_message")),
            recent_context_preview=_optional_str(payload.get("recent_context_preview")),
            seller_notification_detected=_optional_bool(
                payload.get("seller_notification_detected"),
            ),
            seller_intent_type=_optional_str(payload.get("seller_intent_type")),
            seller_notification_type=_optional_str(payload.get("seller_notification_type")),
            seller_operational_request_type=_optional_str(
                payload.get("seller_operational_request_type"),
            ),
            extracted_order_id=_optional_str(payload.get("extracted_order_id")),
            extracted_order_ids=_optional_str(payload.get("extracted_order_ids")),
            extracted_tracking_code=_optional_str(payload.get("extracted_tracking_code")),
            extracted_product_ids=_optional_str(payload.get("extracted_product_ids")),
            extracted_tracking_carrier=_optional_str(payload.get("extracted_tracking_carrier")),
            extracted_iban=_optional_str(payload.get("extracted_iban")),
            extracted_iban_masked=_optional_str(payload.get("extracted_iban_masked")),
            entity_warnings_summary=_optional_str(payload.get("entity_warnings_summary")),
            seller_notification_shipment_status=_optional_str(
                payload.get("seller_notification_shipment_status"),
            ),
            detected_intent=_optional_str(payload.get("detected_intent")),
            intent_confidence_band=_optional_str(payload.get("intent_confidence_band")),
            intent_reasons_summary=_optional_str(payload.get("intent_reasons_summary")),
            intent_related_document_types=_optional_str(
                payload.get("intent_related_document_types"),
            ),
        )

    @property
    def display_label(self) -> str:
        return f"{self.room_id} · {self.ticket_label or 'unknown'}"


def ticket_row_display_label(row_number: int, ticket: OperatorTicket) -> str:
    """Visible list label with 1-based index over the filtered ticket set."""
    if row_number < 1:
        raise ValueError("row_number must be at least 1")
    label = ticket.ticket_label or "unknown"
    return f"#{row_number} — Ticket {ticket.room_id} · {label}"


@dataclass(frozen=True)
class ConsoleMetrics:
    """Aggregate metrics for the filtered ticket set."""

    total_tickets: int
    escalation_count: int
    duplicate_count: int
    action_distribution: dict[str, int] = field(default_factory=dict)


def compute_console_metrics(tickets: list[OperatorTicket]) -> ConsoleMetrics:
    actions: Counter[str] = Counter()
    escalation = 0
    duplicate = 0
    for ticket in tickets:
        action = ticket.suggested_action or "(none)"
        actions[action] += 1
        if ticket.escalation_recommended is True:
            escalation += 1
        if ticket.duplicate_possible is True:
            duplicate += 1
    return ConsoleMetrics(
        total_tickets=len(tickets),
        escalation_count=escalation,
        duplicate_count=duplicate,
        action_distribution=dict(sorted(actions.items())),
    )
