"""Chunk operational knowledge for future retrieval (metadata-rich; no embedding/index)."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.hitl.ticket_text_preview import _contains_unredacted_pii
from app.knowledge.historical_ticket_memory import (
    HistoricalTicketMemoryInventory,
    build_historical_ticket_memory_inventory,
    load_historical_reply_benchmark_summary,
)
from app.knowledge.knowledge_loader import (
    parse_knowledge_document,
    validate_knowledge_document,
)
from app.knowledge.knowledge_models import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeSourceLane,
    KnowledgeVisibility,
)

OFFICIAL_POLICY_PRIORITY_RANK = 10
HISTORICAL_MEMORY_PRIORITY_RANK = 1

CONFLICT_RESOLUTION = "official_policy_overrides_historical_memory"

_HEADING_RE = re.compile(r"^(#{1,2})\s+(.+?)\s*$")

_FORBIDDEN_FIELD_MARKERS = (
    "user_input",
    "draft_response",
    "final_response",
    "customer_reply",
    "generated_response",
    '"messages"',
    "messages[",
    "conversation transcript",
    "conversation_transcript",
    "gold_reference_reply",
    "snapshot_before_reply",
)

_SECRET_PHRASES = (
    "sk-",
    "begin private key",
    "openai_api_key",
    "postgresql://",
    "mongodb://",
    "aws_secret",
    "api_key=",
)


@dataclass(frozen=True)
class KnowledgeChunk:
    """One retrievable unit with lane metadata (text only; no vectors)."""

    chunk_id: str
    source_lane: KnowledgeSourceLane
    document_type: KnowledgeDocumentType
    doc_id: str
    title: str
    section_title: str
    text: str
    visibility: KnowledgeVisibility
    owner: str
    language: str
    version: str
    priority_rank: int
    char_count: int

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_lane": self.source_lane.value,
            "document_type": self.document_type.value,
            "doc_id": self.doc_id,
            "title": self.title,
            "section_title": self.section_title,
            "text": self.text,
            "visibility": self.visibility.value,
            "owner": self.owner,
            "language": self.language,
            "version": self.version,
            "priority_rank": self.priority_rank,
            "char_count": self.char_count,
        }


def _slug_part(text: str) -> str:
    cleaned = re.sub(r"[^\w\u0600-\u06FF]+", "_", text.strip(), flags=re.UNICODE)
    cleaned = cleaned.strip("_").lower()
    return cleaned[:80] or "section"


def assert_chunk_safe(text: str) -> None:
    """Fail closed if chunk text may leak secrets, transcripts, or PII."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("chunk text is empty")
    lowered = stripped.lower()
    for phrase in _SECRET_PHRASES:
        if phrase in lowered:
            raise ValueError(f"chunk must not contain secret-like token: {phrase}")
    for marker in _FORBIDDEN_FIELD_MARKERS:
        if marker in lowered:
            raise ValueError(f"chunk must not contain forbidden marker: {marker}")
    if _contains_unredacted_pii(stripped):
        raise ValueError("chunk contains unredacted PII-like patterns")


def _split_markdown_sections(body: str) -> list[tuple[str, str]]:
    """Split body on ``#`` / ``##`` headings; return (section_title, section_text)."""
    lines = body.splitlines()
    sections: list[tuple[str, str]] = []
    h1_title: str | None = None
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        if current_title is None and not current_lines:
            return
        title = current_title or "(preamble)"
        text = "\n".join(current_lines).strip()
        if text:
            sections.append((title, text))
        current_lines = []

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            flush()
            level = len(match.group(1))
            heading_text = match.group(2).strip()
            if level == 1:
                h1_title = heading_text
                current_title = heading_text
            else:
                if h1_title:
                    current_title = f"{h1_title} — {heading_text}"
                else:
                    current_title = heading_text
            current_lines = []
        else:
            current_lines.append(line)

    flush()
    return sections


def chunk_knowledge_document(
    document: KnowledgeDocument,
    body: str,
    *,
    priority_rank: int = OFFICIAL_POLICY_PRIORITY_RANK,
) -> tuple[list[KnowledgeChunk], int]:
    """Chunk one official document by markdown headings; return (chunks, skipped_unsafe)."""
    chunks: list[KnowledgeChunk] = []
    skipped = 0
    sections = _split_markdown_sections(body)
    if not sections and body.strip():
        sections = [(document.title, body.strip())]

    for section_title, section_text in sections:
        text = section_text.strip()
        if not text:
            skipped += 1
            continue
        try:
            assert_chunk_safe(text)
        except ValueError:
            skipped += 1
            continue
        slug = _slug_part(section_title)
        chunk_id = f"{document.doc_id}__{slug}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                source_lane=document.source_lane,
                document_type=document.document_type,
                doc_id=document.doc_id,
                title=document.title,
                section_title=section_title,
                text=text,
                visibility=document.visibility,
                owner=document.owner,
                language=document.language,
                version=document.version,
                priority_rank=priority_rank,
                char_count=len(text),
            ),
        )
    return chunks, skipped


def build_official_policy_chunks(path: Path) -> tuple[list[KnowledgeChunk], int]:
    """Load and chunk all valid official markdown under ``path``."""
    all_chunks: list[KnowledgeChunk] = []
    skipped_total = 0
    if not path.is_dir():
        return all_chunks, skipped_total

    for md_path in sorted(path.iterdir()):
        if not md_path.is_file() or md_path.suffix.lower() != ".md":
            continue
        try:
            doc, body = parse_knowledge_document(md_path)
            validate_knowledge_document(doc, body)
        except ValueError:
            skipped_total += 1
            continue
        part, skipped = chunk_knowledge_document(doc, body)
        all_chunks.extend(part)
        skipped_total += skipped

    return all_chunks, skipped_total


def _format_label_counts(label_map: dict[str, int]) -> str:
    if not label_map:
        return "none"
    return ", ".join(f"{k}={v}" for k, v in sorted(label_map.items()))


def _historical_aggregate_texts(inv: HistoricalTicketMemoryInventory) -> list[tuple[str, str]]:
    """Return (section_title, aggregate text) pairs — no raw ticket or gold content."""
    if inv.total_cases == 0:
        return [
            (
                "benchmark_overview",
                "Historical support benchmark summary is empty or not loaded; "
                "reference memory lane has no evaluated cases yet.",
            ),
        ]

    texts: list[tuple[str, str]] = []
    texts.append(
        (
            "benchmark_overview",
            (
                f"Historical support benchmark contains {inv.total_cases} evaluated "
                "seller→support reply cases across "
                f"{_format_label_counts(inv.cases_by_label)} workflows. "
                "This lane is operational reference memory only, not authoritative policy."
            ),
        ),
    )
    if inv.cases_by_label:
        texts.append(
            (
                "cases_by_ticket_label",
                "Historical benchmark cases by ticket_label: "
                f"{_format_label_counts(inv.cases_by_label)}.",
            ),
        )
    if inv.cases_by_responder_role:
        texts.append(
            (
                "cases_by_responder_role",
                "Historical benchmark cases by responder_role: "
                f"{_format_label_counts(inv.cases_by_responder_role)}.",
            ),
        )
    skip_parts: list[str] = []
    if inv.skipped_unsafe is not None:
        skip_parts.append(f"skipped_unsafe={inv.skipped_unsafe}")
    if inv.skipped_no_support_reply is not None:
        skip_parts.append(f"skipped_no_support_reply={inv.skipped_no_support_reply}")
    if inv.tickets_processed is not None:
        skip_parts.append(f"tickets_processed={inv.tickets_processed}")
    if skip_parts:
        texts.append(
            (
                "benchmark_build_stats",
                "Historical benchmark build statistics: " + "; ".join(skip_parts) + ".",
            ),
        )
    if inv.benchmark_generated_at_utc:
        texts.append(
            (
                "benchmark_generated_at",
                f"Historical benchmark summary generated_at_utc: {inv.benchmark_generated_at_utc}.",
            ),
        )
    return texts


def build_historical_memory_chunks(
    summary: dict[str, Any] | None,
    *,
    source_summary_path: str | None = None,
) -> tuple[list[KnowledgeChunk], int]:
    """Build aggregate-only historical memory chunks (priority_rank=1)."""
    inv = build_historical_ticket_memory_inventory(
        summary,
        source_summary_path=source_summary_path,
    )
    doc_id = "historical_ticket_memory_v1"
    title = "Historical ticket memory (benchmark aggregates)"
    chunks: list[KnowledgeChunk] = []
    skipped = 0

    for section_title, text in _historical_aggregate_texts(inv):
        try:
            assert_chunk_safe(text)
        except ValueError:
            skipped += 1
            continue
        chunk_id = f"{doc_id}__{section_title}"
        chunks.append(
            KnowledgeChunk(
                chunk_id=chunk_id,
                source_lane=KnowledgeSourceLane.HISTORICAL_MEMORY,
                document_type=KnowledgeDocumentType.HISTORICAL_TICKET_MEMORY,
                doc_id=doc_id,
                title=title,
                section_title=section_title,
                text=text,
                visibility=KnowledgeVisibility.PRIVATE_INTERNAL,
                owner="operations",
                language="fa",
                version="1",
                priority_rank=HISTORICAL_MEMORY_PRIORITY_RANK,
                char_count=len(text),
            ),
        )
    return chunks, skipped


def build_combined_knowledge_chunks(
    *,
    official_path: Path,
    historical_summary_path: Path,
) -> tuple[list[KnowledgeChunk], int]:
    """Official policy chunks first, then historical memory aggregates."""
    official, skip_official = build_official_policy_chunks(official_path)
    summary = load_historical_reply_benchmark_summary(historical_summary_path)
    hist_path = (
        str(historical_summary_path.resolve()) if historical_summary_path.is_file() else None
    )
    historical, skip_hist = build_historical_memory_chunks(
        summary,
        source_summary_path=hist_path,
    )
    return official + historical, skip_official + skip_hist


def summarize_knowledge_chunks(
    chunks: list[KnowledgeChunk],
    *,
    skipped_unsafe: int = 0,
    official_path: str = "",
    historical_summary_path: str = "",
) -> dict[str, Any]:
    """Aggregate metrics for preview JSON / summary reports."""
    by_lane: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    sizes = [c.char_count for c in chunks]
    official_count = sum(1 for c in chunks if c.source_lane is KnowledgeSourceLane.OFFICIAL_POLICY)
    historical_count = sum(
        1 for c in chunks if c.source_lane is KnowledgeSourceLane.HISTORICAL_MEMORY
    )
    for chunk in chunks:
        by_lane[chunk.source_lane.value] += 1
        by_type[chunk.document_type.value] += 1

    avg_size = round(sum(sizes) / len(sizes), 2) if sizes else 0.0
    return {
        "conflict_resolution": CONFLICT_RESOLUTION,
        "total_chunks": len(chunks),
        "chunks_by_source_lane": dict(sorted(by_lane.items())),
        "chunks_by_document_type": dict(sorted(by_type.items())),
        "official_policy_chunk_count": official_count,
        "historical_memory_chunk_count": historical_count,
        "skipped_unsafe": skipped_unsafe,
        "average_chunk_size": avg_size,
        "max_chunk_size": max(sizes) if sizes else 0,
        "official_policy_priority_rank": OFFICIAL_POLICY_PRIORITY_RANK,
        "historical_memory_priority_rank": HISTORICAL_MEMORY_PRIORITY_RANK,
        "official_path": official_path,
        "historical_summary_path": historical_summary_path,
    }


def write_chunks_jsonl(chunks: list[KnowledgeChunk], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.to_json_dict(), ensure_ascii=False) + "\n")
