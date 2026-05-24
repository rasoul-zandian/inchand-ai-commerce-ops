"""Tests for sandbox knowledge retrieval tool (fake store; no network)."""

from __future__ import annotations

import pytest
from app.corpus_planning.pgvector_sandbox_indexing import assert_sandbox_database_url
from app.knowledge.knowledge_retrieval_tool import (
    KnowledgeRetrievalHit,
    KnowledgeRetrievalRequest,
    KnowledgeRetrievalResponse,
    assert_safe_knowledge_retrieval_response,
    execute_sandbox_knowledge_retrieval,
    validate_knowledge_index_version,
    validate_knowledge_namespace,
    validate_knowledge_retrieval_request,
)
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import InMemoryVectorStore
from scripts.run_sandbox_knowledge_retrieval_tool import main as run_tool_main


def _knowledge_record(
    *,
    chunk_id: str,
    source_lane: str,
    document_type: str,
    content: str,
    vector: list[float],
    priority_rank: int,
    namespace: str = "knowledge_operations_sandbox",
    index_version: str = "knowledge_v1_openai",
) -> VectorRecord:
    return VectorRecord(
        record_id=f"knowledge::{source_lane}::{document_type}::{chunk_id}",
        document_id=chunk_id,
        content=content,
        vector=vector,
        dimensions=len(vector),
        embedding_provider="mock",
        embedding_model="mock-knowledge",
        source_type="knowledge_operations",
        metadata={
            "chunk_id": chunk_id,
            "source_lane": source_lane,
            "document_type": document_type,
            "section_title": "section-a",
            "namespace": namespace,
            "index_version": index_version,
            "priority_rank": priority_rank,
        },
    )


def _store_with_records(records: list[VectorRecord]) -> InMemoryVectorStore:
    store = InMemoryVectorStore()
    store.upsert(records)
    return store


def test_validate_namespace_and_index_version() -> None:
    assert validate_knowledge_namespace("knowledge_operations_sandbox") == (
        "knowledge_operations_sandbox"
    )
    assert validate_knowledge_index_version("knowledge_v1_openai") == "knowledge_v1_openai"
    with pytest.raises(ValueError, match="namespace"):
        validate_knowledge_namespace("vendor_ticket")
    with pytest.raises(ValueError, match="index_version"):
        validate_knowledge_index_version("pilot_v1")


def test_rejects_forbidden_query_marker() -> None:
    with pytest.raises(ValueError, match="forbidden"):
        validate_knowledge_retrieval_request(
            {
                "query": 'bad "messages": [ leak',
                "namespace": "knowledge_operations_sandbox",
                "index_version": "knowledge_v1_openai",
                "top_k": 5,
            },
        )


def test_official_priority_ranking() -> None:
    query = [1.0, 0.0, 0.0]
    historical_vec = [0.99, 0.01, 0.0]
    official_vec = [0.50, 0.50, 0.0]
    store = _store_with_records(
        [
            _knowledge_record(
                chunk_id="hist-1",
                source_lane="historical_memory",
                document_type="historical_ticket_memory",
                content="Historical benchmark aggregate summary only.",
                vector=historical_vec,
                priority_rank=1,
            ),
            _knowledge_record(
                chunk_id="settle-1",
                source_lane="official_policy",
                document_type="settlement_rules",
                content="Settlement policy summary for vendors.",
                vector=official_vec,
                priority_rank=10,
            ),
        ],
    )
    request = KnowledgeRetrievalRequest(
        query="vendor settlement timing",
        namespace="knowledge_operations_sandbox",
        index_version="knowledge_v1_openai",
        top_k=2,
        prefer_official_policy=True,
    )
    response = execute_sandbox_knowledge_retrieval(
        request,
        store,
        lambda _text: query,
    )
    assert response.hits[0].source_lane == "official_policy"
    assert response.retrieval_activated is False
    assert response.sandbox_only is True


def test_snippet_truncation_max_300() -> None:
    long_text = "x" * 400
    hit = KnowledgeRetrievalHit(
        chunk_id="c1",
        source_lane="official_policy",
        document_type="settlement_rules",
        section_title="s",
        score=0.5,
        priority_rank=10,
        snippet="y" * 300,
    )
    response = KnowledgeRetrievalResponse(
        hits=[hit],
        result_count=1,
        official_policy_hit_count=1,
        historical_memory_hit_count=0,
    )
    assert_safe_knowledge_retrieval_response(response)
    assert len(hit.snippet) <= 300

    store = _store_with_records(
        [
            _knowledge_record(
                chunk_id="long-1",
                source_lane="official_policy",
                document_type="support_faq",
                content=long_text,
                vector=[1.0, 0.0, 0.0],
                priority_rank=10,
            ),
        ],
    )
    response = execute_sandbox_knowledge_retrieval(
        KnowledgeRetrievalRequest(
            query="faq topic",
            namespace="knowledge_operations_sandbox",
            index_version="knowledge_v1_openai",
            top_k=1,
        ),
        store,
        lambda _text: [1.0, 0.0, 0.0],
    )
    assert len(response.hits[0].snippet) <= 300


def test_allowed_document_types_filter() -> None:
    store = _store_with_records(
        [
            _knowledge_record(
                chunk_id="pub-1",
                source_lane="official_policy",
                document_type="product_publishing_rules",
                content="Publishing rules text.",
                vector=[1.0, 0.0, 0.0],
                priority_rank=10,
            ),
            _knowledge_record(
                chunk_id="set-1",
                source_lane="official_policy",
                document_type="settlement_rules",
                content="Settlement rules text.",
                vector=[0.0, 1.0, 0.0],
                priority_rank=10,
            ),
        ],
    )
    response = execute_sandbox_knowledge_retrieval(
        KnowledgeRetrievalRequest(
            query="rules",
            namespace="knowledge_operations_sandbox",
            index_version="knowledge_v1_openai",
            top_k=5,
            allowed_document_types=["product_publishing_rules"],
        ),
        store,
        lambda _text: [1.0, 0.0, 0.0],
    )
    assert response.result_count == 1
    assert response.hits[0].document_type == "product_publishing_rules"


def test_rejects_unsafe_production_db_url() -> None:
    with pytest.raises(ValueError, match="production|staging"):
        assert_sandbox_database_url("postgresql://user:pass@prod-db.amazonaws.com/db")


def test_cli_requires_confirm_sandbox(capsys: pytest.CaptureFixture[str]) -> None:
    code = run_tool_main(
        [
            "--query",
            "test",
            "--namespace",
            "knowledge_operations_sandbox",
            "--index-version",
            "knowledge_v1_openai",
        ],
    )
    assert code == 1
    assert "--confirm-sandbox" in capsys.readouterr().err


def test_retrieval_activated_always_false() -> None:
    store = _store_with_records([])
    response = execute_sandbox_knowledge_retrieval(
        KnowledgeRetrievalRequest(
            query="empty index",
            namespace="knowledge_operations_sandbox",
            index_version="knowledge_v1_openai",
            top_k=3,
        ),
        store,
        lambda _text: [1.0, 0.0, 0.0],
    )
    assert response.retrieval_activated is False
    assert response.result_count == 0
