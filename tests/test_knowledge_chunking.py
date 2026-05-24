"""Tests for knowledge chunking (Step 163; no embedding/index)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.knowledge.knowledge_chunking import (
    HISTORICAL_MEMORY_PRIORITY_RANK,
    OFFICIAL_POLICY_PRIORITY_RANK,
    assert_chunk_safe,
    build_combined_knowledge_chunks,
    build_historical_memory_chunks,
    build_official_policy_chunks,
    chunk_knowledge_document,
    summarize_knowledge_chunks,
)
from app.knowledge.knowledge_loader import parse_knowledge_document
from app.knowledge.knowledge_models import KnowledgeSourceLane


def _official_md(*, doc_id: str = "rules_v1", doc_type: str = "settlement_rules") -> str:
    return f"""---
doc_id: {doc_id}
title: قوانین نمونه
document_type: {doc_type}
visibility: private_internal
source_lane: official_policy
owner: operations
language: fa
version: 1
last_reviewed_at: 2026-05-20
---

# خلاصه قانون

متن فارسی بخش اول TODO.

## شرایط اصلی

جزئیات بیشتر در این زیربخش.

# استثناها

بخش دوم با عنوان سطح یک.
"""


def test_markdown_heading_split_preserves_persian(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(_official_md(), encoding="utf-8")
    doc, body = parse_knowledge_document(path)
    chunks, skipped = chunk_knowledge_document(doc, body)
    assert skipped == 0
    assert len(chunks) >= 2
    texts = " ".join(c.text for c in chunks)
    assert "متن فارسی" in texts
    assert "جزئیات بیشتر" in texts
    assert any("خلاصه قانون" in c.section_title for c in chunks)
    assert any("شرایط اصلی" in c.section_title for c in chunks)


def test_metadata_preserved_on_chunks(tmp_path: Path) -> None:
    path = tmp_path / "doc.md"
    path.write_text(_official_md(doc_id="meta_v1"), encoding="utf-8")
    doc, body = parse_knowledge_document(path)
    chunks, _ = chunk_knowledge_document(doc, body)
    assert chunks
    c = chunks[0]
    assert c.doc_id == "meta_v1"
    assert c.source_lane is KnowledgeSourceLane.OFFICIAL_POLICY
    assert c.language == "fa"
    assert c.owner == "operations"
    assert c.version == "1"
    assert c.priority_rank == OFFICIAL_POLICY_PRIORITY_RANK


def test_official_priority_greater_than_historical() -> None:
    assert OFFICIAL_POLICY_PRIORITY_RANK > HISTORICAL_MEMORY_PRIORITY_RANK


def test_reject_unsafe_chunk_phone() -> None:
    with pytest.raises(ValueError, match="PII"):
        assert_chunk_safe("تماس 09121234567")


def test_reject_unsafe_chunk_forbidden_field() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        assert_chunk_safe("Contains draft_response in text")


def test_historical_chunks_aggregate_only_no_gold() -> None:
    summary = {
        "total_cases": 1386,
        "cases_by_label": {"support": 1164, "fund": 118, "complaint": 104},
        "cases_by_responder_role": {"support_agent": 1386},
        "skipped_unsafe": 94,
        "skipped_no_support_reply": 1,
        "tickets_processed": 166,
        "generated_at_utc": "2026-05-20T07:33:35+00:00",
    }
    chunks, skipped = build_historical_memory_chunks(summary)
    assert skipped == 0
    assert chunks
    dumped = json.dumps([c.to_json_dict() for c in chunks], ensure_ascii=False)
    assert "gold_reference_reply" not in dumped
    assert "snapshot_before_reply" not in dumped
    assert "1386" in dumped
    for c in chunks:
        assert c.priority_rank == HISTORICAL_MEMORY_PRIORITY_RANK
        assert c.source_lane is KnowledgeSourceLane.HISTORICAL_MEMORY


def test_build_official_policy_chunks_counts(tmp_path: Path) -> None:
    d = tmp_path / "ops"
    d.mkdir()
    (d / "a.md").write_text(_official_md(doc_id="a_v1"), encoding="utf-8")
    (d / "b.md").write_text(
        _official_md(doc_id="b_v1", doc_type="support_faq"),
        encoding="utf-8",
    )
    chunks, skipped = build_official_policy_chunks(d)
    assert skipped == 0
    assert len(chunks) >= 4


def test_summarize_knowledge_chunks_metrics(tmp_path: Path) -> None:
    official = tmp_path / "ops"
    official.mkdir()
    (official / "one.md").write_text(_official_md(), encoding="utf-8")
    summary_path = tmp_path / "hist.json"
    summary_path.write_text(
        json.dumps({"total_cases": 10, "cases_by_label": {"support": 10}}),
        encoding="utf-8",
    )
    chunks, skipped = build_combined_knowledge_chunks(
        official_path=official,
        historical_summary_path=summary_path,
    )
    stats = summarize_knowledge_chunks(chunks, skipped_unsafe=skipped)
    assert stats["total_chunks"] == len(chunks)
    assert stats["official_policy_chunk_count"] >= 2
    assert stats["historical_memory_chunk_count"] >= 1
    assert stats["conflict_resolution"] == "official_policy_overrides_historical_memory"
    assert stats["average_chunk_size"] > 0
    assert stats["max_chunk_size"] >= stats["average_chunk_size"]
