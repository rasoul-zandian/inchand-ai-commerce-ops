"""Tests for retrieval backend comparison script (no live DB, no OpenAI)."""

from __future__ import annotations

import json

import pytest
from app.config import AppSettings
from app.rag.evaluation import RetrievalEvalCase, RetrievalEvalReport, RetrievalEvalResult
from scripts.compare_retrieval_backends import (
    build_comparison_payload,
    comparison_exit_code,
    eval_results_differ,
    format_comparison_lines,
    main,
    resolve_baseline_provider_mode,
    run_comparison,
)


def _result(
    case_id: str,
    *,
    passed: bool,
    retrieved: list[str],
    missing: list[str],
) -> RetrievalEvalResult:
    recall = 1.0 if not missing else (len(retrieved) / max(len(retrieved) + len(missing), 1))
    return RetrievalEvalResult(
        case_id=case_id,
        query="q",
        passed=passed,
        retrieved_document_ids=retrieved,
        expected_document_ids=retrieved + missing,
        matched_document_ids=retrieved,
        missing_document_ids=missing,
        retrieved_source_types=["policy"],
        required_source_types=[],
        missing_source_types=[],
        top_k=5,
        recall_at_k=recall,
        hit_rate=1.0 if retrieved else 0.0,
        mrr=1.0 if retrieved else 0.0,
        first_match_rank=1 if retrieved else None,
    )


def _report(*results: RetrievalEvalResult) -> RetrievalEvalReport:
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    failed = total - passed
    return RetrievalEvalReport(
        total_cases=total,
        passed_cases=passed,
        failed_cases=failed,
        pass_rate=(passed / total) if total else 0.0,
        mean_recall_at_k=sum(r.recall_at_k for r in results) / total if total else 0.0,
        mean_hit_rate=sum(r.hit_rate for r in results) / total if total else 0.0,
        mean_mrr=sum(r.mrr for r in results) / total if total else 0.0,
        results=list(results),
    )


def test_eval_results_differ_on_passed() -> None:
    a = _result("c1", passed=True, retrieved=["d1"], missing=[])
    b = _result("c1", passed=False, retrieved=["d1"], missing=[])
    assert eval_results_differ(a, b)


def test_eval_results_differ_on_missing_ids() -> None:
    a = _result("c1", passed=False, retrieved=[], missing=["d1"])
    b = _result("c1", passed=False, retrieved=["d1"], missing=[])
    assert eval_results_differ(a, b)


def test_eval_results_differ_on_retrieved_ids() -> None:
    a = _result("c1", passed=True, retrieved=["d1"], missing=[])
    b = _result("c1", passed=True, retrieved=["d2"], missing=[])
    assert eval_results_differ(a, b)


def test_build_comparison_payload_detects_differences() -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d2"], missing=[]))
    payload = build_comparison_payload(baseline, pgvector)
    assert payload["comparison"]["cases_with_different_results"] == 1
    assert payload["comparison"]["pass_rate_delta"] == 0.0
    diff = payload["comparison"]["different_cases"][0]
    assert diff["case_id"] == "a"
    assert diff["baseline_retrieved_document_ids"] == ["d1"]
    assert diff["pgvector_retrieved_document_ids"] == ["d2"]


def test_format_comparison_lines_no_secrets() -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    payload = build_comparison_payload(baseline, pgvector)
    text = "\n".join(format_comparison_lines(payload))
    assert "retrieval backend comparison" in text
    assert "provider=in_memory" in text
    assert "baseline_provider=default" in text
    assert "provider=pgvector" in text
    assert "cases_with_different_results=0" in text
    assert "postgresql" not in text.lower()
    assert "database_url" not in text


def test_resolve_baseline_provider_mode_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BASELINE_PROVIDER", raising=False)
    assert resolve_baseline_provider_mode("") == "default"
    assert resolve_baseline_provider_mode("default") == "default"
    assert resolve_baseline_provider_mode(None) == "default"


def test_resolve_baseline_provider_mode_same_embedding() -> None:
    assert resolve_baseline_provider_mode("same_embedding") == "same_embedding"


def test_resolve_baseline_provider_mode_invalid() -> None:
    with pytest.raises(ValueError, match="BASELINE_PROVIDER"):
        resolve_baseline_provider_mode("invalid")


def test_run_comparison_default_uses_default_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    default_calls: list[int] = []
    same_calls: list[int] = []

    def _default() -> RetrievalEvalReport:
        default_calls.append(1)
        return baseline

    def _same(**_kwargs: object) -> RetrievalEvalReport:
        same_calls.append(1)
        return baseline

    monkeypatch.setattr(
        "scripts.compare_retrieval_backends.run_default_vendor_ticket_retrieval_eval",
        _default,
    )
    monkeypatch.setattr(
        "scripts.compare_retrieval_backends.run_same_embedding_in_memory_retrieval_eval",
        _same,
    )
    settings = AppSettings(
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
        pgvector_dimensions=16,
    )
    payload = run_comparison(
        settings,
        baseline_provider_mode="default",
        pgvector_runner=lambda _s, _c: pgvector,
        cases_loader=list,
    )
    assert default_calls == [1]
    assert same_calls == []
    assert payload["baseline_provider"] == "default"
    assert "embedding_provider" not in payload["baseline"]


def test_run_comparison_same_embedding_invokes_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    same_kwargs: list[dict[str, object]] = []

    def _same(
        *,
        embedding_provider: str,
        embedding_model: str,
        cases: list[RetrievalEvalCase] | None = None,
    ) -> RetrievalEvalReport:
        same_kwargs.append(
            {
                "embedding_provider": embedding_provider,
                "embedding_model": embedding_model,
                "cases": cases,
            }
        )
        return baseline

    monkeypatch.setattr(
        "scripts.compare_retrieval_backends.run_same_embedding_in_memory_retrieval_eval",
        _same,
    )
    settings = AppSettings(
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        pgvector_dimensions=1536,
    )
    payload = run_comparison(
        settings,
        baseline_provider_mode="same_embedding",
        pgvector_runner=lambda _s, _c: pgvector,
        cases_loader=list,
    )
    assert len(same_kwargs) == 1
    assert same_kwargs[0]["embedding_provider"] == "openai"
    assert same_kwargs[0]["embedding_model"] == "text-embedding-3-small"
    assert payload["baseline_provider"] == "same_embedding"
    assert payload["embedding_provider"] == "openai"


def test_run_same_embedding_in_memory_uses_semantic_retrieve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.evaluation import run_same_embedding_in_memory_retrieval_eval
    from app.rag.types import RAGDocument, RAGResult

    store_builds: list[tuple[str, str]] = []

    def _documents() -> list[RAGDocument]:
        return [
            RAGDocument(
                document_id="d1",
                title="t",
                content="content",
                source_type="policy",
            )
        ]

    def _build_store(
        documents: list[RAGDocument],
        *,
        embedding_provider: str,
        embedding_model: str,
    ) -> object:
        _ = documents
        store_builds.append((embedding_provider, embedding_model))
        return object()

    def _semantic_retrieve(
        query: str,
        *,
        store: object,
        top_k: int,
        embedding_provider: str,
        embedding_model: str,
    ) -> RAGResult:
        _ = (query, store, top_k, embedding_provider, embedding_model)
        return RAGResult(documents=[], provider="semantic", metadata={})

    def _evaluate_cases(
        cases: list[RetrievalEvalCase],
        *,
        retrieve_fn: object,
    ) -> RetrievalEvalReport:
        _ = cases
        retrieve_fn("q", 5)
        return _report(_result("a", passed=True, retrieved=["d1"], missing=[]))

    monkeypatch.setattr(
        "app.rag.bootstrap.default_vendor_ticket_documents",
        _documents,
    )
    monkeypatch.setattr(
        "app.rag.semantic_retriever.build_in_memory_store_from_documents",
        _build_store,
    )
    monkeypatch.setattr(
        "app.rag.semantic_retriever.semantic_retrieve",
        _semantic_retrieve,
    )
    monkeypatch.setattr(
        "app.rag.evaluation.evaluate_retrieval_cases",
        _evaluate_cases,
    )
    report = run_same_embedding_in_memory_retrieval_eval(
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        cases=[],
    )
    assert store_builds == [("mock", "mock-embedding-small")]
    assert report.metadata.get("baseline_provider") == "same_embedding"


def test_format_comparison_lines_same_embedding_labels() -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    payload = build_comparison_payload(
        baseline,
        pgvector,
        baseline_provider_mode="same_embedding",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
    )
    text = "\n".join(format_comparison_lines(payload))
    assert "baseline_provider=same_embedding" in text
    assert "embedding_provider=openai" in text
    assert "embedding_model=text-embedding-3-small" in text
    assert "sk-" not in text


def test_build_comparison_payload_json_metadata() -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    payload = build_comparison_payload(
        baseline,
        pgvector,
        baseline_provider_mode="same_embedding",
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
    )
    assert payload["baseline_provider"] == "same_embedding"
    assert payload["embedding_provider"] == "mock"
    assert payload["embedding_model"] == "mock-embedding-small"
    assert payload["baseline"]["baseline_provider"] == "same_embedding"
    assert payload["pgvector"]["embedding_provider"] == "mock"


def test_comparison_exit_code_requires_full_pass_and_match() -> None:
    from app.rag.evaluation import RetrievalQualityThresholds

    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    payload = build_comparison_payload(baseline, pgvector)
    strict = RetrievalQualityThresholds(enabled=True)
    assert comparison_exit_code(payload, strict) == 0

    pgvector_fail = _report(_result("a", passed=False, retrieved=[], missing=["d1"]))
    payload_fail = build_comparison_payload(baseline, pgvector_fail)
    assert comparison_exit_code(payload_fail, strict) == 1


def test_main_json_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    monkeypatch.setattr(
        "scripts.compare_retrieval_backends.run_comparison",
        lambda *args, **kwargs: build_comparison_payload(baseline, pgvector),
    )
    monkeypatch.setenv("OUTPUT_JSON", "true")
    assert main() == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["baseline"]["provider"] == "in_memory"
    assert data["baseline"]["baseline_provider"] == "default"
    assert data["baseline_provider"] == "default"
    assert data["pgvector"]["provider"] == "pgvector"
    assert "secret" not in out.lower()


def test_main_fails_when_pgvector_provider_not_set(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = AppSettings(
        vector_store_provider="memory",
        pgvector_database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
    )
    monkeypatch.setattr(
        "scripts.compare_retrieval_backends.get_settings",
        lambda: settings,
    )
    assert main() == 1
    captured = capsys.readouterr()
    assert "VECTOR_STORE_PROVIDER must be 'pgvector'" in captured.err
    assert "secret" not in captured.out + captured.err
    assert "postgresql://" not in captured.out + captured.err


def test_run_comparison_monkeypatched_reports() -> None:
    baseline = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    pgvector = _report(_result("a", passed=True, retrieved=["d1"], missing=[]))
    settings = AppSettings(
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
        pgvector_table="rag_vector_records_16",
        pgvector_dimensions=16,
    )

    payload = run_comparison(
        settings,
        baseline_runner=lambda: baseline,
        pgvector_runner=lambda _settings, _cases: pgvector,
        cases_loader=list,
    )
    text = "\n".join(format_comparison_lines(payload))
    assert "pass_rate_delta=0.0000" in text
    assert comparison_exit_code(payload) == 0
    assert "postgresql" not in text.lower()
