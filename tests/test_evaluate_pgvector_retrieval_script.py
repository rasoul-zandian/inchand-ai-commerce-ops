"""Tests for PgVector retrieval eval script (no live DB, no OpenAI)."""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest
from app.config import AppSettings
from app.rag.evaluation import RetrievalEvalCase, RetrievalEvalReport, RetrievalEvalResult
from app.rag.types import RAGDocument, RAGResult
from app.rag.vector_store import InMemoryVectorStore
from app.rag.vector_store_factory import VectorStoreConfig
from scripts.evaluate_pgvector_retrieval import (
    format_eval_report_lines,
    main,
    pgvector_provider_error,
    print_eval_report,
    run_pgvector_retrieval_eval,
)


def test_pgvector_provider_error_when_not_pgvector() -> None:
    cfg = VectorStoreConfig(provider="memory")
    err = pgvector_provider_error(cfg)
    assert err is not None
    assert "pgvector" in err


def test_pgvector_provider_error_none_for_pgvector() -> None:
    cfg = VectorStoreConfig(
        provider="pgvector",
        database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
    )
    assert pgvector_provider_error(cfg) is None


def test_main_fails_when_vector_store_provider_not_pgvector(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = AppSettings(
        vector_store_provider="memory",
        pgvector_database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
    )
    monkeypatch.setattr(
        "scripts.evaluate_pgvector_retrieval.get_settings",
        lambda: settings,
    )
    assert main() == 1
    captured = capsys.readouterr()
    assert "pgvector retrieval eval: failed" in captured.err
    assert "VECTOR_STORE_PROVIDER must be 'pgvector'" in captured.err
    assert "secret" not in captured.out + captured.err
    assert "postgresql://" not in captured.out + captured.err


def test_format_eval_report_all_passed() -> None:
    report = RetrievalEvalReport(
        total_cases=2,
        passed_cases=2,
        failed_cases=0,
        pass_rate=1.0,
        results=[],
    )
    lines = format_eval_report_lines(report)
    assert lines[0] == "pgvector retrieval eval: passed"
    assert any("pass_rate=1.0000" in line for line in lines)
    assert "all retrieval eval cases passed" in lines


def test_format_eval_report_failed_case_details() -> None:
    report = RetrievalEvalReport(
        total_cases=1,
        passed_cases=0,
        failed_cases=1,
        pass_rate=0.0,
        results=[
            RetrievalEvalResult(
                case_id="case-a",
                query="q",
                passed=False,
                retrieved_document_ids=["doc-x"],
                expected_document_ids=["doc-a"],
                matched_document_ids=[],
                missing_document_ids=["doc-a"],
                retrieved_source_types=["policy"],
                required_source_types=["approved_pattern"],
                missing_source_types=["approved_pattern"],
                top_k=5,
            )
        ],
    )
    text = "\n".join(format_eval_report_lines(report))
    assert "pgvector retrieval eval: failed" in text
    assert "case_id=case-a" in text
    assert "missing_document_ids=['doc-a']" in text
    assert "missing_source_types=['approved_pattern']" in text
    assert "retrieved_document_ids=['doc-x']" in text


def test_print_eval_report_json_mode() -> None:
    report = RetrievalEvalReport(
        total_cases=0,
        passed_cases=0,
        failed_cases=0,
        pass_rate=0.0,
        results=[],
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_eval_report(report, output_json=True)
    payload = buf.getvalue()
    assert '"total_cases": 0' in payload
    assert "postgresql" not in payload.lower()


def test_run_eval_uses_monkeypatched_store_and_retrieve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AppSettings(
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
        pgvector_table="rag_vector_records_16",
        pgvector_dimensions=16,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
    )
    fake_store = InMemoryVectorStore()
    cases = [
        RetrievalEvalCase(
            case_id="eval-1",
            query="test query",
            expected_document_ids=["doc-1"],
            top_k=3,
        )
    ]
    fake_result = RAGResult(
        documents=[
            RAGDocument(
                document_id="doc-1",
                title="t",
                content="c",
                source_type="policy",
            )
        ],
        provider="semantic",
    )

    def fake_retrieve(_query: str, _top_k: int) -> RAGResult:
        return fake_result

    report = run_pgvector_retrieval_eval(
        settings,
        fake_store,
        cases,
        retrieve_fn=fake_retrieve,
    )
    assert report.pass_rate == 1.0
    assert report.passed_cases == 1


def test_main_exits_zero_when_all_cases_pass(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = AppSettings(
        vector_store_provider="pgvector",
        pgvector_database_url="postgresql://user:secret@127.0.0.1:5432/inchand_ai",
        pgvector_table="rag_vector_records_16",
        pgvector_dimensions=16,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
    )
    cases = [
        RetrievalEvalCase(
            case_id="eval-ok",
            query="q",
            expected_document_ids=["doc-1"],
            top_k=2,
        )
    ]
    fake_result = RAGResult(
        documents=[
            RAGDocument(
                document_id="doc-1",
                title="t",
                content="c",
                source_type="policy",
            )
        ],
        provider="semantic",
    )

    monkeypatch.setattr(
        "scripts.evaluate_pgvector_retrieval.get_settings",
        lambda: settings,
    )
    monkeypatch.setattr(
        "scripts.evaluate_pgvector_retrieval.create_vector_store",
        lambda _config: InMemoryVectorStore(),
    )
    monkeypatch.setattr(
        "scripts.evaluate_pgvector_retrieval.default_vendor_ticket_eval_cases",
        lambda: cases,
    )
    monkeypatch.setattr(
        "scripts.evaluate_pgvector_retrieval.semantic_retrieve",
        lambda *_args, **_kwargs: fake_result,
    )
    monkeypatch.delenv("OUTPUT_JSON", raising=False)

    assert main() == 0
    out = capsys.readouterr().out
    assert "pgvector retrieval eval: passed" in out
    assert "all retrieval eval cases passed" in out
    assert "postgresql://" not in out
    assert "secret" not in out


def test_main_output_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = RetrievalEvalReport(
        total_cases=1,
        passed_cases=1,
        failed_cases=0,
        pass_rate=1.0,
        mean_recall_at_k=1.0,
        mean_hit_rate=1.0,
        mean_mrr=1.0,
        results=[],
        metadata={"pgvector_table": "rag_vector_records_16"},
    )
    monkeypatch.setattr(
        "scripts.evaluate_pgvector_retrieval.run_eval",
        lambda: (
            report,
            VectorStoreConfig(
                provider="pgvector",
                database_url="postgresql://secret@localhost/db",
                table_name="rag_vector_records_16",
                dimensions=16,
            ),
        ),
    )
    monkeypatch.setenv("OUTPUT_JSON", "true")
    monkeypatch.setattr(
        "scripts.evaluate_pgvector_retrieval.report_exit_code_for_quality_gates",
        lambda _report, _thresholds=None: 0,
    )
    assert main() == 0
    out = capsys.readouterr().out
    assert '"pass_rate": 1.0' in out
    assert "secret" not in out
    assert "postgresql" not in out.lower()
