"""Build review-queue contract objects from workflow state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from app.nodes.vendor_ticket import build_review_queue_metadata
from app.review_queue.models import ReviewQueueItem
from app.state.commerce_state import CommerceAIState


def _state_dict(state: CommerceAIState) -> dict[str, Any]:
    return dict(state)


def _compact_review_metadata(data: dict[str, Any]) -> dict[str, Any]:
    """Operational metadata only; excludes drafts, secrets, and retrieval payloads."""
    meta: dict[str, Any] = {}
    routing_reasons = data.get("routing_reasons")
    if routing_reasons:
        meta["routing_reasons"] = list(routing_reasons)
    qa_summary = data.get("qa_summary")
    if isinstance(qa_summary, str) and qa_summary.strip():
        meta["qa_summary"] = qa_summary.strip()
    detected_intent = data.get("detected_intent")
    if isinstance(detected_intent, str) and detected_intent.strip():
        meta["detected_intent"] = detected_intent.strip()
    ticket_id = data.get("ticket_id")
    if isinstance(ticket_id, str) and ticket_id.strip():
        meta["ticket_id"] = ticket_id.strip()
    vendor_id = data.get("vendor_id")
    if isinstance(vendor_id, str) and vendor_id.strip():
        meta["vendor_id"] = vendor_id.strip()
    room_id = data.get("room_id")
    if isinstance(room_id, str) and room_id.strip():
        meta["room_id"] = room_id.strip()
    ticket_label = data.get("ticket_label")
    if isinstance(ticket_label, str) and ticket_label.strip():
        meta["ticket_label"] = ticket_label.strip()
    ticket_subtype = data.get("ticket_subtype")
    if isinstance(ticket_subtype, str) and ticket_subtype.strip():
        meta["ticket_subtype"] = ticket_subtype.strip()
    return meta


def build_review_queue_item(state: CommerceAIState) -> ReviewQueueItem:
    """Materialize a review-queue contract item from current workflow state."""
    data = _state_dict(state)
    queue_meta = build_review_queue_metadata(cast(CommerceAIState, data))
    workflow_type = data.get("workflow_type")
    workflow_type_str = (
        workflow_type.value if hasattr(workflow_type, "value") else str(workflow_type or "unknown")
    )
    room_id = data.get("room_id")
    if room_id is None:
        session_id = data.get("session_id")
        room_id = session_id if isinstance(session_id, str) else None
    request_id = data.get("request_id")
    workflow_run_id = request_id if isinstance(request_id, str) else None
    item_metadata = _compact_review_metadata(data)
    department_route = queue_meta.get("department_route")
    if isinstance(department_route, dict):
        item_metadata["department_route"] = department_route

    return ReviewQueueItem(
        review_item_id=str(uuid.uuid4()),
        workflow_type=workflow_type_str,
        workflow_run_id=workflow_run_id,
        room_id=room_id if isinstance(room_id, str) else None,
        review_category=str(queue_meta["review_category"]),
        review_priority=str(queue_meta["review_priority"]),
        review_reason=str(queue_meta["review_reason"]),
        requires_human_approval=bool(queue_meta["requires_human_approval"]),
        route_label=queue_meta.get("route_label")
        if isinstance(queue_meta.get("route_label"), str)
        else None,
        qa_requires_attention=bool(queue_meta.get("qa_requires_attention")),
        qa_issue_count=int(queue_meta.get("qa_issue_count") or 0),
        risk_score=queue_meta.get("risk_score")
        if isinstance(queue_meta.get("risk_score"), (int, float))
        else None,
        confidence_score=queue_meta.get("confidence_score")
        if isinstance(queue_meta.get("confidence_score"), (int, float))
        else None,
        created_at=datetime.now(UTC),
        metadata=item_metadata,
    )
