"""Load and validate official operational knowledge markdown (inventory only)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.hitl.ticket_text_preview import _contains_unredacted_pii
from app.knowledge.knowledge_models import (
    KnowledgeDocument,
    KnowledgeDocumentType,
    KnowledgeSourceLane,
    KnowledgeVisibility,
)

_OFFICIAL_TYPES = frozenset(
    {
        KnowledgeDocumentType.SETTLEMENT_RULES,
        KnowledgeDocumentType.PRODUCT_PUBLISHING_RULES,
        KnowledgeDocumentType.PROHIBITED_GOODS,
        KnowledgeDocumentType.VENDOR_GENERAL_POLICY,
        KnowledgeDocumentType.SUPPORT_FAQ,
        KnowledgeDocumentType.REFUND_RETURN_RULES,
        KnowledgeDocumentType.SHIPPING_DELIVERY_RULES,
    },
)

_REQUIRED_META_KEYS = frozenset(
    {
        "doc_id",
        "title",
        "document_type",
        "visibility",
        "source_lane",
        "owner",
        "language",
        "version",
        "last_reviewed_at",
    },
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

_CUSTOMER_DATA_MARKERS = (
    "user_input",
    '"messages"',
    "messages[",
    "conversation_transcript",
    "raw_transcript",
)


def load_knowledge_markdown_files(path: Path) -> Iterator[Path]:
    """Yield ``*.md`` files directly under ``path`` (non-recursive)."""
    if not path.is_dir():
        return
    for child in sorted(path.iterdir()):
        if child.is_file() and child.suffix.lower() == ".md":
            yield child


def _parse_simple_frontmatter_kv(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        k = key.strip()
        v = value.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def _split_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    lines = markdown.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("knowledge document must start with YAML frontmatter (---)")
    meta_lines: list[str] = []
    i = 1
    while i < len(lines):
        if lines[i].strip() == "---":
            break
        meta_lines.append(lines[i])
        i += 1
    else:
        raise ValueError("knowledge document frontmatter must end with ---")
    body = "\n".join(lines[i + 1 :]).strip()
    return _parse_simple_frontmatter_kv("\n".join(meta_lines)), body


def _count_sections(body: str) -> int:
    """Count markdown headings (lines starting with # after optional whitespace)."""
    n = 0
    for line in body.splitlines():
        if re.match(r"^\s*#+\s+\S", line):
            n += 1
    return n


def parse_knowledge_document(path: Path) -> tuple[KnowledgeDocument, str]:
    """Parse one markdown file into ``KnowledgeDocument`` and body text."""
    raw = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(raw)
    missing = sorted(_REQUIRED_META_KEYS - set(meta))
    if missing:
        raise ValueError(f"missing required frontmatter keys: {', '.join(missing)}")

    try:
        doc_type = KnowledgeDocumentType(meta["document_type"])
    except ValueError as exc:
        raise ValueError(f"invalid document_type: {meta.get('document_type')}") from exc
    try:
        visibility = KnowledgeVisibility(meta["visibility"])
    except ValueError as exc:
        raise ValueError(f"invalid visibility: {meta.get('visibility')}") from exc
    try:
        source_lane = KnowledgeSourceLane(meta["source_lane"])
    except ValueError as exc:
        raise ValueError(f"invalid source_lane: {meta.get('source_lane')}") from exc

    if source_lane is not KnowledgeSourceLane.OFFICIAL_POLICY:
        raise ValueError("official knowledge markdown must set source_lane: official_policy")
    if doc_type not in _OFFICIAL_TYPES:
        raise ValueError(
            "document_type must be an official policy type (not historical_ticket_memory)",
        )

    doc = KnowledgeDocument(
        doc_id=meta["doc_id"].strip(),
        title=meta["title"].strip(),
        document_type=doc_type,
        visibility=visibility,
        source_lane=source_lane,
        source_path=str(path.resolve()),
        version=meta["version"].strip(),
        owner=meta["owner"].strip(),
        language=meta["language"].strip(),
        last_reviewed_at=meta["last_reviewed_at"].strip(),
        section_count=_count_sections(body),
        char_count=len(body),
    )
    if not doc.doc_id or not doc.title:
        raise ValueError("doc_id and title must be non-empty")
    return doc, body


def validate_knowledge_document(document: KnowledgeDocument, body: str) -> None:
    """Fail closed on empty body, secrets, customer-data markers, or PII-like text."""
    if not body.strip():
        raise ValueError("knowledge document body is empty")
    lowered = body.lower()
    combined = f"{document.title}\n{body}".lower()
    for phrase in _SECRET_PHRASES:
        if phrase in combined:
            raise ValueError(f"knowledge document must not contain secret-like token: {phrase}")
    for marker in _CUSTOMER_DATA_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"knowledge document must not contain raw customer-data marker: {marker}",
            )
    if _contains_unredacted_pii(body) or _contains_unredacted_pii(document.title):
        raise ValueError("knowledge document contains unredacted PII-like patterns")


@dataclass(frozen=True)
class OfficialKnowledgeInventory:
    """Result of scanning an official knowledge directory."""

    documents: tuple[KnowledgeDocument, ...]
    warnings: tuple[str, ...]


def build_knowledge_inventory(path: Path) -> OfficialKnowledgeInventory:
    """Load all valid ``*.md`` under ``path``; collect warnings for skipped files."""
    documents: list[KnowledgeDocument] = []
    warnings: list[str] = []
    if not path.is_dir():
        warnings.append(f"official knowledge path is not a directory: {path}")
        return OfficialKnowledgeInventory(documents=tuple(), warnings=tuple(warnings))

    for md_path in load_knowledge_markdown_files(path):
        try:
            doc, body = parse_knowledge_document(md_path)
            validate_knowledge_document(doc, body)
        except ValueError as exc:
            warnings.append(f"{md_path.name}: {exc}")
            continue
        documents.append(doc)

    return OfficialKnowledgeInventory(
        documents=tuple(documents),
        warnings=tuple(warnings),
    )


def knowledge_document_to_dict(document: KnowledgeDocument) -> dict[str, Any]:
    """JSON-serialize a ``KnowledgeDocument`` (paths and metadata only)."""
    return {
        "doc_id": document.doc_id,
        "title": document.title,
        "document_type": document.document_type.value,
        "visibility": document.visibility.value,
        "source_lane": document.source_lane.value,
        "source_path": document.source_path,
        "version": document.version,
        "owner": document.owner,
        "language": document.language,
        "last_reviewed_at": document.last_reviewed_at,
        "section_count": document.section_count,
        "char_count": document.char_count,
    }
