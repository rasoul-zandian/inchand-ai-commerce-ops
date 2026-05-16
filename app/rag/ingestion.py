"""Offline ingestion: records to RAG documents and character-based chunking."""

from __future__ import annotations

from typing import Any

from app.rag.types import RAGDocument
from app.schemas.ticket_data import VendorTicketEvaluationExample, VendorTicketRecord


def ticket_record_to_rag_document(record: VendorTicketRecord) -> RAGDocument:
    """Map a vendor ticket row to a single plain-text RAG document (no chunking/embeddings)."""
    parts: list[str] = [record.subject.strip(), record.body.strip()]
    if record.support_reply:
        parts.append(record.support_reply.strip())
    content = "\n\n".join(p for p in parts if p)

    metadata: dict[str, Any] = {
        "category": record.category,
        "status": record.status,
        "reply_approved": record.reply_approved,
        "escalated": record.escalated,
        "resolution_time_hours": record.resolution_time_hours,
    }
    if "anonymized" in record.metadata:
        metadata["anonymized"] = record.metadata["anonymized"]

    return RAGDocument(
        document_id=f"ticket-{record.ticket_id}",
        title=record.subject,
        content=content,
        source_type="vendor_ticket",
        score=None,
        metadata=metadata,
    )


def evaluation_example_to_rag_document(example: VendorTicketEvaluationExample) -> RAGDocument:
    """Map an evaluation golden example to a RAG document for offline corpora."""
    parts: list[str] = [example.input_body.strip()]
    if example.expected_reply:
        parts.append(example.expected_reply.strip())
    if example.quality_notes:
        parts.append(example.quality_notes.strip())
    content = "\n\n".join(p for p in parts if p)

    return RAGDocument(
        document_id=f"eval-{example.example_id}",
        title=example.input_subject,
        content=content,
        source_type="evaluation_example",
        score=None,
        metadata={
            "expected_intent": example.expected_intent,
            "expected_escalation": example.expected_escalation,
        },
    )


def chunk_text(
    text: str,
    *,
    chunk_size: int = 400,
    overlap: int = 40,
) -> list[str]:
    """Split text into fixed-size character windows with overlap (deterministic, no tokenizer)."""
    if not text:
        return []
    if chunk_size <= 0:
        return []

    overlap_clamped = max(0, overlap)
    if overlap_clamped >= chunk_size:
        overlap_clamped = max(0, chunk_size - 1)

    step = chunk_size - overlap_clamped
    if step <= 0:
        step = 1

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        chunks.append(text[start:end])
        if end >= n:
            break
        start += step
    return chunks


def rag_document_to_chunks(
    document: RAGDocument,
    *,
    chunk_size: int = 400,
    overlap: int = 40,
) -> list[RAGDocument]:
    """Split a document into chunk-level RAGDocument rows (metadata carries parent linkage)."""
    parts = chunk_text(document.content, chunk_size=chunk_size, overlap=overlap)
    if not parts:
        return []

    chunk_count = len(parts)
    out: list[RAGDocument] = []
    for i, chunk_content in enumerate(parts):
        meta = {
            **document.metadata,
            "parent_document_id": document.document_id,
            "chunk_index": i,
            "chunk_count": chunk_count,
        }
        out.append(
            RAGDocument(
                document_id=f"{document.document_id}-chunk-{i}",
                title=document.title,
                content=chunk_content,
                source_type=document.source_type,
                score=document.score,
                metadata=meta,
            )
        )
    return out
