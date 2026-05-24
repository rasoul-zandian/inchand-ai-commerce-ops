"""Tests for knowledge chunk sandbox embedding/index (mock; no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.knowledge.knowledge_chunking import chunk_knowledge_document
from app.knowledge.knowledge_embedding_index import (
    build_knowledge_record_id,
    build_knowledge_vector_records,
    generate_knowledge_embeddings,
    load_knowledge_chunks,
    query_knowledge_pgvector,
    rank_knowledge_search_results,
    validate_knowledge_record_id,
)
from app.knowledge.knowledge_loader import parse_knowledge_document
from app.knowledge.knowledge_models import KnowledgeSourceLane
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import VectorSearchResult


def _official_md() -> str:
    return """---
doc_id: rules_v1
title: قوانین
document_type: settlement_rules
visibility: private_internal
source_lane: official_policy
owner: operations
language: fa
version: 1
last_reviewed_at: 2026-05-20
---

# خلاصه قانون

متن فارسی تسویه TODO.
"""


def _write_chunks_jsonl(path: Path) -> None:
    doc_path = path.parent / "doc.md"
    doc_path.write_text(_official_md(), encoding="utf-8")
    doc, body = parse_knowledge_document(doc_path)
    chunks, _ = chunk_knowledge_document(doc, body)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_json_dict(), ensure_ascii=False) + "\n")
    hist = {
        "chunk_id": "historical_ticket_memory_v1__benchmark_overview",
        "source_lane": "historical_memory",
        "document_type": "historical_ticket_memory",
        "doc_id": "historical_ticket_memory_v1",
        "title": "Historical memory",
        "section_title": "benchmark_overview",
        "text": ("Historical support benchmark contains 10 evaluated seller→support cases."),
        "visibility": "private_internal",
        "owner": "operations",
        "language": "fa",
        "version": "1",
        "priority_rank": 1,
        "char_count": 60,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(hist, ensure_ascii=False) + "\n")


def test_load_knowledge_chunks(tmp_path: Path) -> None:
    jsonl = tmp_path / "chunks.jsonl"
    _write_chunks_jsonl(jsonl)
    loaded = load_knowledge_chunks(jsonl)
    assert len(loaded) >= 2


def test_build_vector_records_metadata_and_record_id(tmp_path: Path) -> None:
    jsonl = tmp_path / "chunks.jsonl"
    _write_chunks_jsonl(jsonl)
    loaded = load_knowledge_chunks(jsonl)
    batch = generate_knowledge_embeddings(
        loaded,
        provider="mock",
        model="mock-knowledge",
        dimensions=1536,
    )
    records = build_knowledge_vector_records(
        batch,
        namespace="knowledge_operations_sandbox",
        index_version="knowledge_v1",
    )
    official = next(r for r in records if "official_policy" in r.record_id)
    validate_knowledge_record_id(official.record_id)
    assert official.record_id.startswith("knowledge::official_policy::")
    assert official.metadata["priority_rank"] == 10
    assert official.metadata["conflict_resolution"] == "official_policy_overrides_historical_memory"
    assert official.metadata["namespace"] == "knowledge_operations_sandbox"
    assert "متن فارسی" in official.content


def test_record_id_format_helper() -> None:
    from app.knowledge.knowledge_chunking import KnowledgeChunk
    from app.knowledge.knowledge_models import KnowledgeDocumentType, KnowledgeVisibility

    chunk = KnowledgeChunk(
        chunk_id="settlement_rules_v1__summary",
        source_lane=KnowledgeSourceLane.OFFICIAL_POLICY,
        document_type=KnowledgeDocumentType.SETTLEMENT_RULES,
        doc_id="settlement_rules_v1",
        title="T",
        section_title="S",
        text="body",
        visibility=KnowledgeVisibility.PRIVATE_INTERNAL,
        owner="operations",
        language="fa",
        version="1",
        priority_rank=10,
        char_count=4,
    )
    rid = build_knowledge_record_id(chunk)
    assert rid == "knowledge::official_policy::settlement_rules::settlement_rules_v1__summary"


def test_mock_embeddings_no_network(tmp_path: Path) -> None:
    jsonl = tmp_path / "chunks.jsonl"
    _write_chunks_jsonl(jsonl)
    loaded = load_knowledge_chunks(jsonl)
    batch = generate_knowledge_embeddings(
        loaded,
        provider="mock",
        model="mock-knowledge",
        dimensions=1536,
    )
    assert batch.provider == "mock"
    assert len(batch.vectors) == len(loaded)
    assert all(len(v) == 1536 for v in batch.vectors)


def test_openai_requires_confirm() -> None:
    with pytest.raises(ValueError, match="confirm_real_openai"):
        generate_knowledge_embeddings(
            [],
            provider="openai",
            model="text-embedding-3-small",
            confirm_real_openai=False,
        )


def test_rank_official_before_historical_by_priority() -> None:
    def _hit(lane: str, priority: int, score: float) -> VectorSearchResult:
        return VectorSearchResult(
            record=VectorRecord(
                record_id=f"knowledge::{lane}::support_faq::id",
                document_id="d",
                content="text",
                vector=[0.0] * 16,
                dimensions=16,
                embedding_provider="mock",
                embedding_model="m",
                source_type="knowledge_operations",
                metadata={
                    "source_lane": lane,
                    "priority_rank": priority,
                    "namespace": "knowledge_operations_sandbox",
                    "index_version": "knowledge_v1",
                    "chunk_id": "c",
                    "section_title": "s",
                    "document_type": "support_faq",
                },
            ),
            score=score,
        )

    ranked = rank_knowledge_search_results(
        [
            _hit("historical_memory", 1, 0.99),
            _hit("official_policy", 10, 0.50),
        ],
    )
    assert ranked[0].record.metadata["source_lane"] == "official_policy"


def test_reject_unsafe_production_db_url() -> None:
    with pytest.raises(ValueError, match="production|staging"):
        assert_sandbox_database_url("postgresql://user:pass@prod-db.amazonaws.com/inchand")


def test_query_output_safe_fields(tmp_path: Path) -> None:
    jsonl = tmp_path / "chunks.jsonl"
    _write_chunks_jsonl(jsonl)
    loaded = load_knowledge_chunks(jsonl)
    batch = generate_knowledge_embeddings(
        loaded,
        provider="mock",
        model="mock-knowledge",
        dimensions=1536,
    )
    records = build_knowledge_vector_records(
        batch,
        namespace="knowledge_operations_sandbox",
        index_version="knowledge_v1",
    )

    def fake_search(query_vector: list[float], top_k: int) -> list[VectorSearchResult]:
        _ = query_vector
        return [
            VectorSearchResult(record=records[0], score=0.9),
            VectorSearchResult(record=records[-1], score=0.95),
        ][:top_k]

    hits = query_knowledge_pgvector(
        "تسویه فروشنده",
        namespace="knowledge_operations_sandbox",
        index_version="knowledge_v1",
        database_url="postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
        provider="mock",
        dimensions=1536,
        top_k=2,
        search_fn=fake_search,
    )
    assert hits
    assert set(hits[0]) == {
        "chunk_id",
        "source_lane",
        "document_type",
        "section_title",
        "score",
        "priority_rank",
        "text_snippet",
    }
    assert len(hits[0]["text_snippet"]) <= 300
    assert hits[0]["source_lane"] == "official_policy"
    dumped = json.dumps(hits, ensure_ascii=False)
    assert "gold_reference_reply" not in dumped
