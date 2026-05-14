"""Vendor ticket and evaluation shapes for offline data readiness (no live systems)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VendorTicketRecord(BaseModel):
    """Normalized vendor ticket row for imports, anonymization, and future services."""

    ticket_id: str
    created_at: str | None = None
    vendor_id_hash: str | None = None
    subject: str
    body: str
    category: str | None = None
    status: str | None = None
    support_reply: str | None = None
    reply_approved: bool | None = None
    escalated: bool | None = None
    resolution_time_hours: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VendorTicketEvaluationExample(BaseModel):
    """Golden-style example for offline evaluation of ticket understanding and drafts."""

    example_id: str
    input_subject: str
    input_body: str
    expected_intent: str | None = None
    expected_reply: str | None = None
    expected_escalation: bool | None = None
    quality_notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGTicketExample(BaseModel):
    """Document-shaped ticket snippet for future RAG indexing (approved content only)."""

    document_id: str
    title: str
    content: str
    intent: str | None = None
    source_ticket_id: str | None = None
    approved: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
