"""Offline RAG ingestion helpers (no network, no OpenAI, no DB)."""

from __future__ import annotations

from app.rag.ingestion import (
    chunk_text,
    evaluation_example_to_rag_document,
    rag_document_to_chunks,
    ticket_record_to_rag_document,
)
from app.rag.types import RAGDocument
from app.schemas.ticket_data import VendorTicketEvaluationExample, VendorTicketRecord


def test_ticket_record_to_rag_document_shape() -> None:
    record = VendorTicketRecord(
        ticket_id="t-1",
        subject="عنوان",
        body="متن",
        support_reply="پاسخ",
        category="billing",
        status="closed",
        reply_approved=True,
        escalated=False,
        resolution_time_hours=12.5,
        metadata={"anonymized": True},
    )
    doc = ticket_record_to_rag_document(record)
    assert doc.document_id == "ticket-t-1"
    assert doc.title == "عنوان"
    assert "عنوان" in doc.content and "متن" in doc.content and "پاسخ" in doc.content
    assert doc.source_type == "vendor_ticket"
    assert doc.metadata.get("category") == "billing"
    assert doc.metadata.get("status") == "closed"
    assert doc.metadata.get("reply_approved") is True
    assert doc.metadata.get("escalated") is False
    assert doc.metadata.get("resolution_time_hours") == 12.5
    assert doc.metadata.get("anonymized") is True


def test_ticket_record_skips_anonymized_if_absent() -> None:
    record = VendorTicketRecord(ticket_id="t-2", subject="س", body="ب", metadata={})
    doc = ticket_record_to_rag_document(record)
    assert "anonymized" not in doc.metadata


def test_evaluation_example_to_rag_document_shape() -> None:
    ex = VendorTicketEvaluationExample(
        example_id="e-1",
        input_subject="موضوع",
        input_body="بدنه",
        expected_reply="پاسخ طلایی",
        quality_notes="یادداشت",
        expected_intent="billing",
        expected_escalation=False,
    )
    doc = evaluation_example_to_rag_document(ex)
    assert doc.document_id == "eval-e-1"
    assert doc.title == "موضوع"
    assert "بدنه" in doc.content and "پاسخ طلایی" in doc.content and "یادداشت" in doc.content
    assert doc.source_type == "evaluation_example"
    assert doc.metadata.get("expected_intent") == "billing"
    assert doc.metadata.get("expected_escalation") is False


def test_chunk_text_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("", chunk_size=10, overlap=2) == []


def test_chunk_text_overlap_behavior() -> None:
    text = "abcdefghij"
    chunks = chunk_text(text, chunk_size=4, overlap=2)
    assert chunks[0] == "abcd"
    assert chunks[1] == "cdef"
    assert chunks[0][-2:] == chunks[1][:2]


def test_rag_document_to_chunks_metadata_and_ids() -> None:
    base = RAGDocument(
        document_id="ticket-x",
        title="T",
        content="0123456789",
        source_type="vendor_ticket",
        score=0.5,
        metadata={"region": "eu"},
    )
    chunks = rag_document_to_chunks(base, chunk_size=4, overlap=2)
    assert len(chunks) == 4
    assert [c.document_id for c in chunks] == [
        "ticket-x-chunk-0",
        "ticket-x-chunk-1",
        "ticket-x-chunk-2",
        "ticket-x-chunk-3",
    ]
    for i, c in enumerate(chunks):
        assert c.title == "T"
        assert c.source_type == "vendor_ticket"
        assert c.score == 0.5
        assert c.metadata.get("region") == "eu"
        assert c.metadata.get("parent_document_id") == "ticket-x"
        assert c.metadata.get("chunk_index") == i
        assert c.metadata.get("chunk_count") == 4


def test_rag_document_to_chunks_ordering() -> None:
    base = RAGDocument(
        document_id="d",
        title="t",
        content="abcdefgh",
        source_type="s",
        metadata={},
    )
    parts = chunk_text(base.content, chunk_size=3, overlap=1)
    chunks = rag_document_to_chunks(base, chunk_size=3, overlap=1)
    assert [c.content for c in chunks] == parts
