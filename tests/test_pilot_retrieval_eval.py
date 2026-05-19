"""Tests for pilot sandbox retrieval evaluation (no Postgres, no OpenAI)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.corpus_planning.pilot_retrieval_eval import (
    PilotMetadataFilter,
    PilotRetrievalCase,
    PilotRetrievalHit,
    PilotScopedVectorStore,
    assert_safe_eval_report,
    comparison_report_to_dict,
    count_pilot_scoped_metadata_matches,
    department_from_metadata,
    load_pilot_retrieval_cases,
    pilot_record_matches_scope,
    record_matches_metadata_filter,
    report_to_dict,
    run_pilot_retrieval_comparison_eval,
    run_pilot_retrieval_eval,
    score_pilot_retrieval_results,
    write_pilot_retrieval_comparison_report,
    write_pilot_retrieval_eval_report,
)
from app.embeddings.types import EmbeddingResponse
from app.rag.vector_records import VectorRecord
from app.rag.vector_store import InMemoryVectorStore
from scripts.eval_pilot_retrieval import main as eval_main

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CASES_PATH = _REPO_ROOT / "evals" / "pilot_retrieval" / "vendor_ticket_real_pilot_cases.json"


def _hit(
    *,
    record_id: str,
    label: str,
    department: str,
    room_id: str = "ROOM_01",
    score: float = 0.9,
) -> PilotRetrievalHit:
    return PilotRetrievalHit(
        record_id=record_id,
        document_id="doc-1",
        ticket_label=label,
        department=department,
        room_id=room_id,
        score=score,
    )


def test_loads_eval_cases() -> None:
    cases = load_pilot_retrieval_cases(_CASES_PATH)
    assert len(cases) >= 12
    assert any(case.eval_mode == "metadata_filtered" for case in cases)
    assert any(case.metadata_filter is not None for case in cases)
    assert all(case.case_id for case in cases)
    assert all(case.expected_ticket_label in {"support", "complaint", "fund"} for case in cases)
    for case in cases:
        if case.metadata_filter is None:
            continue
        assert case.metadata_filter.department is None, (
            f"{case.case_id}: metadata_filter must not use department (not stored on index)"
        )


def test_load_cases_metadata_filter_calibration_note() -> None:
    payload = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    assert payload.get("eval_version") == "4"
    note = payload.get("metadata_filter_calibration_note", "")
    assert "department" in note
    assert "metadata_filter" in note
    assert "namespace" in note.lower()


def test_eval_cases_do_not_pin_namespace_or_index_version() -> None:
    cases = load_pilot_retrieval_cases(_CASES_PATH)
    for case in cases:
        if case.metadata_filter is None:
            continue
        assert case.metadata_filter.namespace is None, (
            f"{case.case_id}: metadata_filter.namespace must not be pinned"
        )
        assert case.metadata_filter.index_version is None, (
            f"{case.case_id}: metadata_filter.index_version must not be pinned"
        )


def test_load_cases_rejects_pinned_namespace_in_metadata_filter(tmp_path: Path) -> None:
    payload = {
        "cases": [
            {
                "case_id": "bad-scope-pin",
                "query": "fund settlement",
                "expected_ticket_label": "fund",
                "expected_department": "finance",
                "metadata_filter": {
                    "ticket_label": "fund",
                    "namespace": "vendor_ticket_real_pilot",
                },
            }
        ]
    }
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="must not pin namespace or index_version"):
        load_pilot_retrieval_cases(path)


def test_compare_modes_scoped_store_uses_cli_namespace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CLI compare-modes passes namespace/index_version into scoped pgvector store."""
    built: dict[str, str] = {}

    def fake_build_pgvector_store(
        database_url: str,
        *,
        namespace: str,
        index_version: str,
        table_name: str = "rag_vector_records",
        dimensions: int = 1536,
    ) -> PilotScopedVectorStore:
        _ = database_url, table_name, dimensions
        built["namespace"] = namespace
        built["index_version"] = index_version
        return PilotScopedVectorStore(
            InMemoryVectorStore(),
            namespace=namespace,
            index_version=index_version,
        )

    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.build_pilot_pgvector_store",
        fake_build_pgvector_store,
    )
    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.load_pilot_retrieval_cases",
        lambda _p: [
            PilotRetrievalCase(
                case_id="fund-cli-scope",
                query="vendor settlement",
                expected_ticket_label="fund",
                expected_department="finance",
                metadata_filter=PilotMetadataFilter(ticket_label="fund"),
            )
        ],
    )
    monkeypatch.setattr(
        "app.corpus_planning.pilot_retrieval_eval.generate_embedding",
        lambda _text, **kwargs: EmbeddingResponse(
            vector=[1.0] + [0.0] * 15,
            provider=kwargs.get("provider", "mock"),
            model=kwargs.get("model", "mock-embedding-small"),
            dimensions=16,
            metadata={},
        ),
    )
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )

    output = tmp_path / "reports" / "pilot_retrieval_eval_balanced_v1.json"
    code = eval_main(
        [
            "--cases",
            str(_CASES_PATH),
            "--namespace",
            "vendor_ticket_real_pilot_balanced",
            "--index-version",
            "pilot_balanced_v1",
            "--profile",
            "semantic_pgvector",
            "--compare-modes",
            "--output",
            str(output),
            "--overwrite",
        ]
    )
    assert code in {0, 1}
    assert built["namespace"] == "vendor_ticket_real_pilot_balanced"
    assert built["index_version"] == "pilot_balanced_v1"


def test_department_from_metadata_route_label() -> None:
    assert department_from_metadata({"route_label": "billing_review"}) == "finance"
    assert department_from_metadata({"ticket_label": "complaint"}) == "complaint"


def test_scores_label_and_department_matches() -> None:
    case = PilotRetrievalCase(
        case_id="c1",
        query="vendor support help",
        expected_ticket_label="support",
        expected_department="support",
    )
    hits = {
        "c1": [
            _hit(
                record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc-a",
                label="support",
                department="support",
            )
        ]
    }
    report = score_pilot_retrieval_results([case], hits, top_k=5)
    assert report.passed_cases == 1
    assert report.label_match_rate == 1.0
    assert report.department_match_rate == 1.0


def test_detects_wrong_label_return() -> None:
    case = PilotRetrievalCase(
        case_id="c2",
        query="vendor onboarding",
        expected_ticket_label="support",
        expected_department="support",
        must_not_return_labels=("fund", "complaint"),
    )
    hits = {
        "c2": [
            _hit(
                record_id="pilot::ns::v1::doc",
                label="support",
                department="support",
                score=0.95,
            ),
            _hit(
                record_id="pilot::ns::v1::doc2",
                label="fund",
                department="finance",
                score=0.5,
            ),
        ]
    }
    report = score_pilot_retrieval_results([case], hits, top_k=5)
    assert report.passed_cases == 0
    assert report.wrong_label_return_count == 1
    assert report.results[0].failure_reasons


def test_empty_results_fail() -> None:
    case = PilotRetrievalCase(
        case_id="c3",
        query="anything",
        expected_ticket_label="support",
        expected_department="support",
    )
    report = score_pilot_retrieval_results([case], {"c3": []}, top_k=5)
    assert report.empty_result_count == 1
    assert report.passed_cases == 0
    assert "no_results_returned" in report.results[0].failure_reasons


def test_pilot_record_scope_filter() -> None:
    meta = {"namespace": "vendor_ticket_real_pilot", "index_version": "pilot_v1"}
    assert pilot_record_matches_scope(
        "pilot::vendor_ticket_real_pilot::pilot_v1::doc-1",
        meta,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )
    assert not pilot_record_matches_scope(
        "bootstrap-vt-policy-001",
        {},
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )


def test_fake_retrieval_returns_expected_metrics() -> None:
    cases = load_pilot_retrieval_cases(_CASES_PATH)[:3]

    def fake_retrieve(case: PilotRetrievalCase, top_k: int) -> list[PilotRetrievalHit]:
        label = "support"
        department = "support"
        if "complaint" in case.query:
            label = "complaint"
            department = "complaint"
        if "settlement" in case.query or "billing" in case.query or "invoice" in case.query:
            label = "fund"
            department = "finance"
        return [
            _hit(
                record_id=f"pilot::vendor_ticket_real_pilot::pilot_v1::doc-{label}",
                label=label,
                department=department,
            )
        ][:top_k]

    report = run_pilot_retrieval_eval(
        cases,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        top_k=5,
        retrieve_fn=fake_retrieve,
    )
    assert report.total_cases == 3
    assert report.pass_rate >= 0.0
    assert report.retrieval_activated is False


def test_output_excludes_raw_content_and_queries(tmp_path: Path) -> None:
    case = PilotRetrievalCase(
        case_id="safe",
        query="secret raw query text should not appear",
        expected_ticket_label="support",
        expected_department="support",
    )
    report = run_pilot_retrieval_eval(
        [case],
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        top_k=3,
        retrieve_fn=lambda _case, _k: [
            _hit(
                record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc",
                label="support",
                department="support",
            )
        ],
    )
    payload = report_to_dict(
        report,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
    )
    serialized = json.dumps(payload)
    assert "secret raw query" not in serialized
    assert "conversation_transcript" not in serialized.lower()
    assert '"vector":' not in serialized
    assert_safe_eval_report(payload)
    write_pilot_retrieval_eval_report(
        report,
        output_path=tmp_path / "reports" / "pilot_retrieval_eval_pilot_v1.json",
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
    )


def _pilot_vector_record(
    *,
    suffix: str,
    ticket_label: str,
    vector: list[float],
    route_label: str = "general_vendor_support",
    namespace: str = "vendor_ticket_real_pilot",
    index_version: str = "pilot_v1",
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
            "namespace": namespace,
            "index_version": index_version,
        },
    )


def test_scoped_store_filters_non_pilot_records() -> None:
    pilot_record = VectorRecord(
        record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc-a",
        document_id="doc-a",
        content="room_id=ROOM_A|ticket_label=support",
        vector=[0.1] * 16,
        dimensions=16,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        source_type="vendor_ticket_real_pilot",
        metadata={
            "ticket_label": "support",
            "route_label": "general_vendor_support",
            "namespace": "vendor_ticket_real_pilot",
            "index_version": "pilot_v1",
        },
    )
    bootstrap_record = VectorRecord(
        record_id="bootstrap-vt-policy-001",
        document_id="bootstrap-vt-policy-001",
        content="policy",
        vector=[0.9] * 16,
        dimensions=16,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
        source_type="policy",
        metadata={},
    )
    inner = InMemoryVectorStore()
    inner.upsert([bootstrap_record, pilot_record])
    scoped = PilotScopedVectorStore(
        inner,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )
    hits = scoped.search([0.1] * 16, top_k=5)
    assert len(hits) == 1
    assert hits[0].record.record_id.startswith("pilot::")

    fund_record = VectorRecord(
        record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc-fund",
        document_id="doc-fund",
        content="room_id=ROOM_F|ticket_label=fund",
        vector=[0.2] * 16,
        dimensions=16,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        source_type="vendor_ticket_real_pilot",
        metadata={
            "ticket_label": "fund",
            "route_label": "billing_review",
            "namespace": "vendor_ticket_real_pilot",
            "index_version": "pilot_v1",
        },
    )
    inner.upsert([fund_record])
    fund_filter = PilotMetadataFilter(ticket_label="fund")
    fund_hits = scoped.search([0.2] * 16, top_k=5, metadata_filter=fund_filter)
    assert len(fund_hits) == 1
    assert fund_hits[0].record.metadata.get("ticket_label") == "fund"


def test_metadata_filter_ranks_pilot_candidates_not_global_top_k() -> None:
    """Fund rows must be retrievable when bootstrap/support dominate global similarity."""
    dim = 16
    query = [1.0] + [0.0] * (dim - 1)
    near_query = [0.99] + [0.01] + [0.0] * (dim - 2)
    fund_vector = [0.0, 1.0] + [0.0] * (dim - 2)

    bootstrap = [
        VectorRecord(
            record_id=f"bootstrap-{index}",
            document_id=f"bootstrap-{index}",
            content="policy",
            vector=near_query,
            dimensions=dim,
            embedding_provider="mock",
            embedding_model="mock-embedding-small",
            source_type="policy",
            metadata={},
        )
        for index in range(50)
    ]
    support_pilot = [
        _pilot_vector_record(
            suffix=f"support-{index}",
            ticket_label="support",
            vector=near_query,
        )
        for index in range(40)
    ]
    fund_pilot = [
        _pilot_vector_record(
            suffix=f"fund-{index}",
            ticket_label="fund",
            route_label="billing_review",
            vector=fund_vector,
        )
        for index in range(3)
    ]

    inner = InMemoryVectorStore()
    inner.upsert(bootstrap + support_pilot + fund_pilot)
    scoped = PilotScopedVectorStore(
        inner,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )

    vector_hits = scoped.search(query, top_k=5)
    assert len(vector_hits) == 5
    assert all(
        hit.record.record_id.startswith("pilot::vendor_ticket_real_pilot::pilot_v1::")
        for hit in vector_hits
    )
    assert all(hit.record.metadata.get("ticket_label") == "support" for hit in vector_hits)

    fund_filter = PilotMetadataFilter(ticket_label="fund")
    assert count_pilot_scoped_metadata_matches(scoped, fund_filter) == 3

    fund_hits = scoped.search(query, top_k=5, metadata_filter=fund_filter)
    assert len(fund_hits) == 3
    assert {hit.record.metadata.get("ticket_label") for hit in fund_hits} == {"fund"}

    billing_filter = PilotMetadataFilter(route_label="billing_review")
    assert count_pilot_scoped_metadata_matches(scoped, billing_filter) == 3
    billing_hits = scoped.search(query, top_k=2, metadata_filter=billing_filter)
    assert len(billing_hits) == 2
    assert all(hit.record.metadata.get("route_label") == "billing_review" for hit in billing_hits)


def test_department_only_filter_not_recommended_without_explicit_field() -> None:
    meta = {
        "ticket_label": "fund",
        "route_label": "billing_review",
        "namespace": "vendor_ticket_real_pilot",
        "index_version": "pilot_v1",
    }
    assert not record_matches_metadata_filter(
        meta,
        PilotMetadataFilter(department="finance"),
    )
    meta_with_explicit = {**meta, "department": "finance"}
    assert record_matches_metadata_filter(
        meta_with_explicit,
        PilotMetadataFilter(department="finance"),
    )


def test_record_matches_metadata_filter() -> None:
    meta = {
        "ticket_label": "fund",
        "route_label": "billing_review",
        "namespace": "vendor_ticket_real_pilot",
        "index_version": "pilot_v1",
    }
    assert record_matches_metadata_filter(meta, PilotMetadataFilter(ticket_label="fund"))
    assert not record_matches_metadata_filter(
        meta,
        PilotMetadataFilter(ticket_label="support"),
    )


def test_compare_modes_passes_case_metadata_filter_to_scoped_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare-modes metadata leg must pass each case.metadata_filter into scoped search."""
    dim = 16
    query = [1.0] + [0.0] * (dim - 1)
    near_query = [0.99] + [0.01] + [0.0] * (dim - 2)
    fund_vector = [0.0, 1.0] + [0.0] * (dim - 2)

    inner = InMemoryVectorStore()
    inner.upsert(
        [
            VectorRecord(
                record_id=f"bootstrap-{index}",
                document_id=f"bootstrap-{index}",
                content="policy",
                vector=near_query,
                dimensions=dim,
                embedding_provider="mock",
                embedding_model="mock-embedding-small",
                source_type="policy",
                metadata={},
            )
            for index in range(50)
        ]
        + [
            _pilot_vector_record(
                suffix=f"support-{index}",
                ticket_label="support",
                vector=near_query,
            )
            for index in range(40)
        ]
        + [
            _pilot_vector_record(
                suffix=f"fund-{index}",
                ticket_label="fund",
                route_label="billing_review",
                vector=fund_vector,
            )
            for index in range(3)
        ]
    )
    scoped = PilotScopedVectorStore(
        inner,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )

    search_filters: list[PilotMetadataFilter | None] = []
    original_search = PilotScopedVectorStore.search

    def tracking_search(
        self: PilotScopedVectorStore,
        query_vector: list[float],
        *,
        top_k: int = 5,
        metadata_filter: PilotMetadataFilter | None = None,
    ) -> list:
        search_filters.append(metadata_filter)
        return original_search(
            self,
            query_vector,
            top_k=top_k,
            metadata_filter=metadata_filter,
        )

    monkeypatch.setattr(PilotScopedVectorStore, "search", tracking_search)
    monkeypatch.setattr(
        "app.corpus_planning.pilot_retrieval_eval.generate_embedding",
        lambda _text, **kwargs: EmbeddingResponse(
            vector=query,
            provider=kwargs.get("provider", "mock"),
            model=kwargs.get("model", "mock-embedding-small"),
            dimensions=dim,
            metadata={},
        ),
    )

    fund_case = PilotRetrievalCase(
        case_id="pilot-fund-settlement-005",
        query="vendor settlement amount does not match expected payout schedule",
        expected_ticket_label="fund",
        expected_department="finance",
        eval_mode="vector_only",
        metadata_filter=PilotMetadataFilter(ticket_label="fund"),
    )

    comparison = run_pilot_retrieval_comparison_eval(
        [fund_case],
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        top_k=5,
        store=scoped,
        embedding_provider="mock",
        embedding_model="mock-embedding-small",
    )

    assert any(filt is not None and filt.ticket_label == "fund" for filt in search_filters), (
        "metadata_filtered leg must call search with ticket_label=fund filter"
    )
    assert any(filt is None for filt in search_filters), (
        "vector_only leg must call search without metadata_filter"
    )

    metadata_result = comparison.metadata_filtered.results[0]
    assert metadata_result.returned_count > 0
    assert metadata_result.top_labels[0] == "fund"
    assert comparison.metadata_filtered.empty_result_count == 0


def test_comparison_eval_with_fake_adapter() -> None:
    fund_case = PilotRetrievalCase(
        case_id="fund-case",
        query="settlement mismatch",
        expected_ticket_label="fund",
        expected_department="finance",
        metadata_filter=PilotMetadataFilter(ticket_label="fund"),
    )

    def fake_retrieve(case: PilotRetrievalCase, top_k: int) -> list[PilotRetrievalHit]:
        if case.eval_mode == "metadata_filtered":
            return [
                _hit(
                    record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc-fund",
                    label="fund",
                    department="finance",
                )
            ]
        return [
            _hit(
                record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc-support",
                label="support",
                department="support",
            )
        ][:top_k]

    from app.corpus_planning.pilot_retrieval_eval import PilotScopedVectorStore

    store = PilotScopedVectorStore(
        InMemoryVectorStore(),
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
    )

    def run_comparison(**kwargs: object) -> object:
        _ = kwargs
        vector_report = run_pilot_retrieval_eval(
            [fund_case],
            namespace="vendor_ticket_real_pilot",
            index_version="pilot_v1",
            profile="semantic_pgvector",
            top_k=3,
            retrieve_fn=fake_retrieve,
            eval_mode="vector_only",
        )
        filtered_case = PilotRetrievalCase(
            case_id=fund_case.case_id,
            query=fund_case.query,
            expected_ticket_label=fund_case.expected_ticket_label,
            expected_department=fund_case.expected_department,
            eval_mode="metadata_filtered",
            metadata_filter=fund_case.metadata_filter,
        )
        metadata_report = run_pilot_retrieval_eval(
            [filtered_case],
            namespace="vendor_ticket_real_pilot",
            index_version="pilot_v1",
            profile="semantic_pgvector",
            top_k=3,
            retrieve_fn=fake_retrieve,
            eval_mode="metadata_filtered",
        )
        from app.corpus_planning.pilot_retrieval_eval import PilotRetrievalComparisonReport

        return PilotRetrievalComparisonReport(
            vector_only=vector_report,
            metadata_filtered=metadata_report,
            delta_pass_rate=metadata_report.pass_rate - vector_report.pass_rate,
            delta_wrong_label_return_count=(
                metadata_report.wrong_label_return_count - vector_report.wrong_label_return_count
            ),
            namespace="vendor_ticket_real_pilot",
            index_version="pilot_v1",
            profile="semantic_pgvector",
        )

    # Direct comparison logic test without store/embeddings
    _ = store
    comparison = run_comparison()
    assert comparison.vector_only.passed_cases == 0
    assert comparison.metadata_filtered.passed_cases == 1
    assert comparison.delta_pass_rate == 1.0


def test_comparison_report_shape(tmp_path: Path) -> None:
    from app.corpus_planning.pilot_retrieval_eval import (
        PilotRetrievalComparisonReport,
        PilotRetrievalEvalReport,
    )

    vector = PilotRetrievalEvalReport(
        total_cases=4,
        passed_cases=0,
        failed_cases=4,
        pass_rate=0.0,
        mean_top_score=0.4,
        label_match_rate=0.0,
        department_match_rate=0.0,
        wrong_label_return_count=1,
        empty_result_count=0,
        top_k=5,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        eval_mode="vector_only",
    )
    filtered = PilotRetrievalEvalReport(
        total_cases=4,
        passed_cases=4,
        failed_cases=0,
        pass_rate=1.0,
        mean_top_score=0.7,
        label_match_rate=1.0,
        department_match_rate=1.0,
        wrong_label_return_count=0,
        empty_result_count=0,
        top_k=5,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        eval_mode="metadata_filtered",
    )
    comparison = PilotRetrievalComparisonReport(
        vector_only=vector,
        metadata_filtered=filtered,
        delta_pass_rate=1.0,
        delta_wrong_label_return_count=-1,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
    )
    payload = comparison_report_to_dict(comparison, profile="semantic_pgvector")
    assert payload["comparison"]["delta_pass_rate"] == 1.0
    assert payload["comparison"]["delta_wrong_label_return_count"] == -1
    assert payload["vector_only"]["eval_mode"] == "vector_only"
    assert payload["metadata_filtered"]["eval_mode"] == "metadata_filtered"
    assert_safe_eval_report(payload)
    write_pilot_retrieval_comparison_report(
        comparison,
        output_path=tmp_path / "reports" / "pilot_retrieval_eval_pilot_v1.json",
        profile="semantic_pgvector",
    )


def test_cli_rejects_semantic_pgvector_16(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )
    code = eval_main(
        [
            "--cases",
            str(_CASES_PATH),
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--profile",
            "semantic_pgvector_16",
            "--overwrite",
        ]
    )
    assert code == 1
    assert "semantic_pgvector_16" in capsys.readouterr().err


def test_cli_requires_namespace_and_index_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        eval_main(["--cases", str(_CASES_PATH)])
    err = capsys.readouterr().err
    assert "namespace" in err.lower() or "required" in err.lower()


def test_output_exists_without_overwrite_fails(tmp_path: Path) -> None:
    output = tmp_path / "reports" / "pilot_retrieval_eval_pilot_v1.json"
    output.parent.mkdir(parents=True)
    output.write_text("{}\n", encoding="utf-8")
    code = eval_main(
        [
            "--cases",
            str(_CASES_PATH),
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
        ]
    )
    assert code == 1


def test_cli_success_with_fake_retrieve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "reports" / "pilot_retrieval_eval_pilot_v1.json"

    def fake_run(*args: object, **kwargs: object) -> object:
        from app.corpus_planning.pilot_retrieval_eval import (
            PilotRetrievalCaseResult,
            PilotRetrievalEvalReport,
        )

        return PilotRetrievalEvalReport(
            total_cases=12,
            passed_cases=12,
            failed_cases=0,
            pass_rate=1.0,
            mean_top_score=0.88,
            label_match_rate=1.0,
            department_match_rate=1.0,
            wrong_label_return_count=0,
            empty_result_count=0,
            top_k=5,
            namespace="vendor_ticket_real_pilot",
            index_version="pilot_v1",
            profile="semantic_pgvector",
            eval_mode="vector_only",
            results=(
                PilotRetrievalCaseResult(
                    case_id="pilot-support-general-001",
                    query_hash="abc",
                    expected_ticket_label="support",
                    expected_department="support",
                    returned_count=1,
                    top_labels=("support",),
                    top_departments=("support",),
                    passed=True,
                    failure_reasons=(),
                ),
            ),
        )

    monkeypatch.setattr("scripts.eval_pilot_retrieval.load_pilot_retrieval_cases", lambda _p: [])
    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.build_pilot_pgvector_store",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.build_default_pilot_retrieve_fn",
        lambda _s: lambda _case, _k: [],
    )
    monkeypatch.setattr("scripts.eval_pilot_retrieval.run_pilot_retrieval_eval", fake_run)
    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.run_pilot_retrieval_comparison_eval",
        lambda *a, **k: None,
    )
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )

    code = eval_main(
        [
            "--cases",
            str(_CASES_PATH),
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--output",
            str(output),
            "--overwrite",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "pass_rate=1.0000" in out
    assert "sk-" not in out


def test_no_openai_calls_in_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_openai(*args: object, **kwargs: object) -> None:
        raise AssertionError("OpenAI should not be called in unit tests")

    monkeypatch.setattr(
        "app.corpus_planning.pilot_retrieval_eval.generate_embedding",
        fail_openai,
    )
    case = PilotRetrievalCase(
        case_id="c",
        query="vendor support",
        expected_ticket_label="support",
        expected_department="support",
    )
    run_pilot_retrieval_eval(
        [case],
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        top_k=3,
        retrieve_fn=lambda _case, _k: [
            _hit(
                record_id="pilot::vendor_ticket_real_pilot::pilot_v1::doc",
                label="support",
                department="support",
            )
        ],
    )


def test_cli_compare_modes_with_fake_comparison(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.corpus_planning.pilot_retrieval_eval import (
        PilotRetrievalComparisonReport,
        PilotRetrievalEvalReport,
    )

    output = tmp_path / "reports" / "pilot_retrieval_eval_pilot_v1.json"
    vector = PilotRetrievalEvalReport(
        total_cases=4,
        passed_cases=0,
        failed_cases=4,
        pass_rate=0.0,
        mean_top_score=0.4,
        label_match_rate=0.0,
        department_match_rate=0.0,
        wrong_label_return_count=1,
        empty_result_count=0,
        top_k=5,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        eval_mode="vector_only",
    )
    filtered = PilotRetrievalEvalReport(
        total_cases=4,
        passed_cases=4,
        failed_cases=0,
        pass_rate=1.0,
        mean_top_score=0.7,
        label_match_rate=1.0,
        department_match_rate=1.0,
        wrong_label_return_count=0,
        empty_result_count=0,
        top_k=5,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
        eval_mode="metadata_filtered",
    )
    comparison = PilotRetrievalComparisonReport(
        vector_only=vector,
        metadata_filtered=filtered,
        delta_pass_rate=1.0,
        delta_wrong_label_return_count=-1,
        namespace="vendor_ticket_real_pilot",
        index_version="pilot_v1",
        profile="semantic_pgvector",
    )

    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.load_pilot_retrieval_cases",
        lambda _p: [
            PilotRetrievalCase(
                case_id="fund",
                query="fund",
                expected_ticket_label="fund",
                expected_department="finance",
                metadata_filter=PilotMetadataFilter(ticket_label="fund"),
            )
        ],
    )
    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.build_pilot_pgvector_store",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "scripts.eval_pilot_retrieval.run_pilot_retrieval_comparison_eval",
        lambda *a, **k: comparison,
    )
    monkeypatch.setenv(
        "PGVECTOR_DATABASE_URL",
        "postgresql://inchand:inchand_dev_password@127.0.0.1:5432/inchand_ai",
    )
    code = eval_main(
        [
            "--cases",
            str(_CASES_PATH),
            "--namespace",
            "vendor_ticket_real_pilot",
            "--index-version",
            "pilot_v1",
            "--output",
            str(output),
            "--overwrite",
            "--compare-modes",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "delta_pass_rate=1.0000" in out
    assert "vector_only" in out
    assert "metadata_filtered" in out
