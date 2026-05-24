"""Typed models for operational knowledge (inventory; not retrieval)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class KnowledgeDocumentType(StrEnum):
    """Logical document categories (including lane placeholder for historical memory)."""

    SETTLEMENT_RULES = "settlement_rules"
    PRODUCT_PUBLISHING_RULES = "product_publishing_rules"
    PROHIBITED_GOODS = "prohibited_goods"
    VENDOR_GENERAL_POLICY = "vendor_general_policy"
    SUPPORT_FAQ = "support_faq"
    REFUND_RETURN_RULES = "refund_return_rules"
    SHIPPING_DELIVERY_RULES = "shipping_delivery_rules"
    HISTORICAL_TICKET_MEMORY = "historical_ticket_memory"


class KnowledgeVisibility(StrEnum):
    PRIVATE_INTERNAL = "private_internal"
    PUBLIC_SAFE = "public_safe"
    RESTRICTED = "restricted"


class KnowledgeSourceLane(StrEnum):
    OFFICIAL_POLICY = "official_policy"
    HISTORICAL_MEMORY = "historical_memory"


@dataclass(frozen=True)
class KnowledgeDocument:
    """One loaded official knowledge markdown file (parsed metadata + stats)."""

    doc_id: str
    title: str
    document_type: KnowledgeDocumentType
    visibility: KnowledgeVisibility
    source_lane: KnowledgeSourceLane
    source_path: str
    version: str
    owner: str
    language: str
    last_reviewed_at: str
    section_count: int
    char_count: int
