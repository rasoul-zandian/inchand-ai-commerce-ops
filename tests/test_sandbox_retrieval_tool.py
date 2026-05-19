"""Tests for sandbox retrieval tool executor (fake store; no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.pilot_retrieval_eval import PilotScopedVectorStore
from app.corpus_planning.retrieval_tool_models import (
    RetrievalToolMetadataFilter,
    RetrievalToolRequest,
)
from app.corpus_planning.sandbox_retrieval_tool import (
    execute_sandbox_retrieval_tool,
    execute_sandbox_retrieval_tool_to_dict,
)
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import InMemoryVectorStore
from scripts.run_sandbox_retrieval_tool import main as run_tool_main


def _pilot_record(
    *,
    suffix: str,
    ticket_label: str,
    vector: list[float],
    route_label: str = "billing_review",
    review_priority: str = "normal",
    namespace: str = "vendor_ticket_real_pilot_balanced",
    index_version: str = "pilot_balanced_v1",
) -> VectorRecord:
    return VectorRecord(
        record_id=f"pilot::{namespace}::{index_version}::{suffix}",
        document_id=suffix,
        content=f"room_id=ROOM_{suffix}|ticket_label={ticket_label}",
        vector=vector,
        dimensions=len(vector),
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        source_type=namespace,
        metadata={
            "ticket_label": ticket_label,
            "route_label": route_label,
            "review_priority": review_priority,
            "namespace": namespace,
            "index_version": index_version,
        },
    )


def _scoped_store(
    records: list[VectorRecord],
    *,
    namespace: str = "vendor_ticket_real_pilot_balanced",
    index_version: str = "pilot_balanced_v1",
) -> PilotScopedVectorStore:
    inner = InMemoryVectorStore()
    inner.upsert(records)
    return PilotScopedVectorStore(inner, namespace=namespace, index_version=index_version)


def test_execute_applies_metadata_filter() -> None:
    query = [1.0] + [0.0] * 15
    fund_vector = [0.99, 0.01] + [0.0] * 14
    support_vector = [0.0, 1.0] + [0.0] * 14
    store = _scoped_store(
        [
            _pilot_record(suffix="fund-1", ticket_label="fund", vector=fund_vector),
            _pilot_record(
                suffix="support-1",
                ticket_label="support",
                vector=support_vector,
                route_label="general_vendor_support",
            ),
        ]
    )
    request = RetrievalToolRequest(
        query="settlement payment status",
        top_k=5,
        namespace="vendor_ticket_real_pilot_balanced",
        index_version="pilot_balanced_v1",
        metadata_filter=RetrievalToolMetadataFilter(ticket_label="fund"),
        eval_mode="metadata_filtered",
    )
    response = execute_sandbox_retrieval_tool(
        request,
        store,
        lambda _text: query,
        profile="semantic_pgvector",
    )
    assert response.result_count == 1
    assert response.results[0].ticket_label == "fund"
    assert response.retrieval_activated is False
    assert response.sandbox_only is True


def test_execute_vector_only_ignores_metadata_filter() -> None:
    query = [1.0] + [0.0] * 15
    store = _scoped_store(
        [
            _pilot_record(suffix="fund-1", ticket_label="fund", vector=query),
            _pilot_record(
                suffix="support-1",
                ticket_label="support",
                vector=[0.0, 1.0] + [0.0] * 14,
                route_label="general_vendor_support",
            ),
        ]
    )
    request = RetrievalToolRequest(
        query="settlement payment status",
        top_k=5,
        namespace="vendor_ticket_real_pilot_balanced",
        index_version="pilot_balanced_v1",
        metadata_filter=RetrievalToolMetadataFilter(ticket_label="fund"),
        eval_mode="vector_only",
    )
    response = execute_sandbox_retrieval_tool(
        request,
        store,
        lambda _text: query,
    )
    assert response.result_count >= 1
    labels = {item.ticket_label for item in response.results}
    assert "fund" in labels or "support" in labels


def test_response_has_no_raw_query_or_forbidden_fields() -> None:
    store = _scoped_store(
        [_pilot_record(suffix="fund-1", ticket_label="fund", vector=[1.0] + [0.0] * 15)]
    )
    request = RetrievalToolRequest(
        query="secret settlement phrase",
        top_k=3,
        namespace="vendor_ticket_real_pilot_balanced",
        index_version="pilot_balanced_v1",
    )
    payload = execute_sandbox_retrieval_tool_to_dict(
        request,
        store,
        lambda _text: [1.0] + [0.0] * 15,
    )
    serialized = json.dumps(payload)
    assert "secret settlement phrase" not in serialized
    assert '"query"' not in serialized
    assert "conversation_transcript" not in serialized
    assert '"vector"' not in serialized
    assert '"content"' not in serialized
    assert payload["query_hash"]
    assert payload["retrieval_activated"] is False
    assert payload["sandbox_only"] is True


def test_execute_rejects_scope_mismatch() -> None:
    store = _scoped_store(
        [_pilot_record(suffix="fund-1", ticket_label="fund", vector=[1.0] + [0.0] * 15)],
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )
    request = RetrievalToolRequest(
        query="test",
        top_k=3,
        namespace="vendor_ticket_real_pilot_balanced",
        index_version="pilot_balanced_v1",
    )
    with pytest.raises(ValueError, match="must match the request"):
        execute_sandbox_retrieval_tool(request, store, lambda _text: [1.0] + [0.0] * 15)


def test_cli_requires_confirm_sandbox(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )
    code = run_tool_main(
        [
            "--query",
            "settlement payment status",
            "--namespace",
            "vendor_ticket_real_pilot_balanced",
            "--index-version",
            "pilot_balanced_v1",
        ]
    )
    assert code == 1
    assert "--confirm-sandbox is required" in capsys.readouterr().err


def test_cli_success_with_fake_executor(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output = tmp_path / "sandbox_retrieval_tool.json"

    def fake_execute(*args: object, **kwargs: object) -> dict:
        _ = args, kwargs
        return {
            "results": [
                {
                    "record_id": (
                        "pilot::vendor_ticket_real_pilot_balanced::pilot_balanced_v1::fund-1"
                    ),
                    "score": 0.42,
                    "ticket_label": "fund",
                    "route_label": "billing_review",
                    "review_priority": "normal",
                }
            ],
            "retrieval_activated": False,
            "sandbox_only": True,
            "query_hash": "abc123456789abcd",
            "result_count": 1,
        }

    monkeypatch.setattr(
        "scripts.run_sandbox_retrieval_tool.build_pilot_pgvector_store",
        lambda *a, **k: object(),
    )
    monkeypatch.setattr(
        "scripts.run_sandbox_retrieval_tool.execute_sandbox_retrieval_tool_to_dict",
        fake_execute,
    )
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-printed")

    code = run_tool_main(
        [
            "--query",
            "settlement payment status",
            "--namespace",
            "vendor_ticket_real_pilot_balanced",
            "--index-version",
            "pilot_balanced_v1",
            "--ticket-label",
            "fund",
            "--confirm-sandbox",
            "--output",
            str(output),
            "--overwrite",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    err = capsys.readouterr().err
    assert "sk-" not in out
    assert "sk-" not in err
    assert "OPENAI_API_KEY" not in out
    assert "result_count=1" in out
    assert output.is_file()
