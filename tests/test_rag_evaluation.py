"""Tests for offline RAG retrieval evaluation (mock RAGResult, no OpenAI)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.rag.evaluation import (
    RetrievalEvalCase,
    default_vendor_ticket_eval_cases,
    evaluate_retrieval_case,
    evaluate_retrieval_cases,
    load_retrieval_eval_cases,
    load_vendor_ticket_eval_cases_from_file,
    run_default_vendor_ticket_retrieval_eval,
)
from app.rag.types import RAGDocument, RAGResult
from pydantic import ValidationError


def _project_eval_cases_path() -> Path:
    return Path(__file__).resolve().parents[1] / "corpus" / "vendor_ticket" / "eval_cases.json"


def test_load_retrieval_eval_cases_parses_valid_file() -> None:
    file_model = load_retrieval_eval_cases(_project_eval_cases_path())
    assert file_model.eval_version == "1"
    assert file_model.workflow_type == "vendor_ticket"
    assert file_model.locale == "fa-IR"
    assert len(file_model.cases) == 15


def test_default_vendor_ticket_eval_cases_loads_from_file_and_preserves_order() -> None:
    from_file = load_vendor_ticket_eval_cases_from_file(_project_eval_cases_path())
    default_list = default_vendor_ticket_eval_cases()
    assert [c.case_id for c in default_list] == [c.case_id for c in from_file]
    assert [c.case_id for c in default_list] == [
        "vt-settlement-discrepancy-001",
        "vt-tone-respectful-002",
        "vt-escalation-sla-003",
        "vt-short-settlement-004",
        "vt-short-escalation-005",
        "vt-financial-indirect-006",
        "vt-escalation-vague-007",
        "vt-conv-settlement-008",
        "vt-policy-style-tone-009",
        "vt-near-miss-autorefund-010",
        "vt-near-miss-settlement-wording-011",
        "vt-single-approved-pattern-012",
        "vt-policy-financial-only-013",
        "vt-escalation-repeat-sla-014",
        "vt-style-threat-avoid-015",
    ]


def test_loaded_cases_include_workflow_metadata_from_file() -> None:
    cases = default_vendor_ticket_eval_cases()
    for c in cases:
        assert c.metadata.get("workflow_type") == "vendor_ticket"
        assert c.metadata.get("locale") == "fa-IR"
        assert c.metadata.get("eval_version") == "1"


def test_malformed_eval_json_raises_value_error(tmp_path: Path) -> None:
    bad = tmp_path / "eval_cases.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match="valid JSON"):
        load_retrieval_eval_cases(bad)


def test_invalid_eval_schema_raises_validation_error(tmp_path: Path) -> None:
    bad = tmp_path / "eval_cases.json"
    bad.write_text(json.dumps({"eval_version": "1"}), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_retrieval_eval_cases(bad)


def _doc(did: str, source_type: str) -> RAGDocument:
    return RAGDocument(
        document_id=did,
        title="t",
        content="c",
        source_type=source_type,
        score=0.9,
        metadata={},
    )


def test_evaluate_retrieval_case_passes_when_expected_present() -> None:
    case = RetrievalEvalCase(
        case_id="c1",
        query="q",
        expected_document_ids=["a", "b"],
        required_source_types=["policy", "style_guide"],
        top_k=3,
    )
    result = RAGResult(
        documents=[
            _doc("a", "policy"),
            _doc("b", "style_guide"),
            _doc("x", "policy"),
        ],
        provider="semantic",
        metadata={},
    )
    out = evaluate_retrieval_case(case, result=result)
    assert out.passed is True
    assert out.matched_document_ids == ["a", "b"]
    assert out.missing_document_ids == []
    assert out.missing_source_types == []
    assert out.retrieved_document_ids == ["a", "b", "x"]


def test_evaluate_retrieval_case_fails_when_expected_missing() -> None:
    case = RetrievalEvalCase(
        case_id="c2",
        query="q",
        expected_document_ids=["a", "missing"],
        top_k=2,
    )
    result = RAGResult(documents=[_doc("a", "policy")], provider="mock", metadata={})
    out = evaluate_retrieval_case(case, result=result)
    assert out.passed is False
    assert out.missing_document_ids == ["missing"]
    assert out.matched_document_ids == ["a"]


def test_required_source_types_enforced() -> None:
    case = RetrievalEvalCase(
        case_id="c3",
        query="q",
        expected_document_ids=["z"],
        required_source_types=["style_guide"],
        top_k=2,
    )
    result = RAGResult(documents=[_doc("z", "policy")], provider="mock", metadata={})
    out = evaluate_retrieval_case(case, result=result)
    assert out.passed is False
    assert out.missing_source_types == ["style_guide"]


def test_retrieved_source_types_unique_first_seen_order() -> None:
    case = RetrievalEvalCase(case_id="c4", query="q", expected_document_ids=[], top_k=5)
    result = RAGResult(
        documents=[
            _doc("1", "policy"),
            _doc("2", "policy"),
            _doc("3", "style_guide"),
            _doc("4", "approved_pattern"),
            _doc("5", "policy"),
        ],
        provider="mock",
        metadata={},
    )
    out = evaluate_retrieval_case(case, result=result)
    assert out.retrieved_source_types == ["policy", "style_guide", "approved_pattern"]


def test_ranking_metrics_perfect_retrieval() -> None:
    case = RetrievalEvalCase(
        case_id="m1",
        query="q",
        expected_document_ids=["a"],
        top_k=3,
    )
    result = RAGResult(documents=[_doc("a", "policy")], provider="mock", metadata={})
    out = evaluate_retrieval_case(case, result=result)
    assert out.recall_at_k == 1.0
    assert out.hit_rate == 1.0
    assert out.mrr == 1.0
    assert out.first_match_rank == 1


def test_ranking_metrics_partial_retrieval() -> None:
    case = RetrievalEvalCase(
        case_id="m2",
        query="q",
        expected_document_ids=["a", "b"],
        top_k=3,
    )
    result = RAGResult(documents=[_doc("a", "policy")], provider="mock", metadata={})
    out = evaluate_retrieval_case(case, result=result)
    assert out.recall_at_k == 0.5
    assert out.hit_rate == 1.0
    assert out.mrr == 1.0
    assert out.first_match_rank == 1


def test_ranking_metrics_later_first_match() -> None:
    case = RetrievalEvalCase(
        case_id="m3",
        query="q",
        expected_document_ids=["target"],
        top_k=5,
    )
    result = RAGResult(
        documents=[
            _doc("x", "policy"),
            _doc("y", "policy"),
            _doc("target", "policy"),
        ],
        provider="mock",
        metadata={},
    )
    out = evaluate_retrieval_case(case, result=result)
    assert out.first_match_rank == 3
    assert out.mrr == pytest.approx(1.0 / 3.0)
    assert out.hit_rate == 1.0
    assert out.recall_at_k == 1.0


def test_ranking_metrics_no_match() -> None:
    case = RetrievalEvalCase(
        case_id="m4",
        query="q",
        expected_document_ids=["missing"],
        top_k=3,
    )
    result = RAGResult(documents=[_doc("other", "policy")], provider="mock", metadata={})
    out = evaluate_retrieval_case(case, result=result)
    assert out.recall_at_k == 0.0
    assert out.hit_rate == 0.0
    assert out.mrr == 0.0
    assert out.first_match_rank is None


def test_ranking_metrics_empty_expected_ids() -> None:
    case = RetrievalEvalCase(case_id="m5", query="q", expected_document_ids=[], top_k=3)
    result = RAGResult(documents=[_doc("a", "policy")], provider="mock", metadata={})
    out = evaluate_retrieval_case(case, result=result)
    assert out.recall_at_k == 0.0
    assert out.hit_rate == 0.0
    assert out.mrr == 0.0
    assert out.first_match_rank is None


def test_aggregate_report_metrics_average() -> None:
    cases = [
        RetrievalEvalCase(case_id="a", query="q1", expected_document_ids=["d1"], top_k=2),
        RetrievalEvalCase(case_id="b", query="q2", expected_document_ids=["d2", "d3"], top_k=2),
    ]

    def retrieve_fn(query: str, top_k: int) -> RAGResult:
        if query == "q1":
            return RAGResult(documents=[_doc("d1", "policy")], provider="mock", metadata={})
        return RAGResult(documents=[_doc("d2", "policy")], provider="mock", metadata={})

    report = evaluate_retrieval_cases(cases, retrieve_fn=retrieve_fn)
    assert report.mean_recall_at_k == pytest.approx((1.0 + 0.5) / 2.0)
    assert report.mean_hit_rate == 1.0
    assert report.mean_mrr == 1.0


def test_empty_cases_aggregate_metrics_zero() -> None:
    def _empty_retrieve(_query: str, _k: int) -> RAGResult:
        return RAGResult(documents=[], provider="x", metadata={})

    report = evaluate_retrieval_cases([], retrieve_fn=_empty_retrieve)
    assert report.mean_recall_at_k == 0.0
    assert report.mean_hit_rate == 0.0
    assert report.mean_mrr == 0.0


def test_evaluate_retrieval_cases_counts_and_pass_rate() -> None:
    cases = [
        RetrievalEvalCase(case_id="p1", query="q1", expected_document_ids=["a"], top_k=2),
        RetrievalEvalCase(case_id="p2", query="q2", expected_document_ids=["x"], top_k=2),
    ]

    def retrieve_fn(query: str, top_k: int) -> RAGResult:
        if query == "q1":
            return RAGResult(documents=[_doc("a", "policy")], provider="mock", metadata={})
        return RAGResult(documents=[_doc("y", "policy")], provider="mock", metadata={})

    report = evaluate_retrieval_cases(cases, retrieve_fn=retrieve_fn)
    assert report.total_cases == 2
    assert report.passed_cases == 1
    assert report.failed_cases == 1
    assert report.pass_rate == 0.5
    assert report.metadata.get("evaluator") == "offline_retrieval_eval"


def test_empty_cases_pass_rate_zero() -> None:
    def _empty_retrieve(_query: str, _k: int) -> RAGResult:
        return RAGResult(documents=[], provider="x", metadata={})

    report = evaluate_retrieval_cases([], retrieve_fn=_empty_retrieve)
    assert report.total_cases == 0
    assert report.pass_rate == 0.0
    assert report.passed_cases == 0
    assert report.failed_cases == 0
    assert report.mean_recall_at_k == 0.0
    assert report.mean_hit_rate == 0.0
    assert report.mean_mrr == 0.0


def test_default_vendor_ticket_eval_cases_non_empty() -> None:
    cases = default_vendor_ticket_eval_cases()
    assert len(cases) == 15
    assert all(c.expected_document_ids for c in cases)


def test_run_default_vendor_ticket_retrieval_eval() -> None:
    report = run_default_vendor_ticket_retrieval_eval()
    assert report.total_cases > 0
    assert report.metadata.get("evaluator") == "offline_retrieval_eval"
    assert report.pass_rate == 1.0


def test_near_miss_after_expected_hit_no_violation() -> None:
    case = RetrievalEvalCase(
        case_id="nm1",
        query="q",
        expected_document_ids=["expected"],
        top_k=5,
        metadata={"near_miss_document_ids": ["near-miss"]},
    )
    result = RAGResult(
        documents=[
            _doc("expected", "policy"),
            _doc("near-miss", "policy"),
        ],
        provider="mock",
        metadata={},
    )
    out = evaluate_retrieval_case(case, result=result)
    assert out.passed is True
    assert out.near_miss_document_ids == ["near-miss"]
    assert out.near_miss_violations == []


def test_near_miss_before_first_expected_hit_violation() -> None:
    case = RetrievalEvalCase(
        case_id="nm2",
        query="q",
        expected_document_ids=["expected"],
        top_k=5,
        metadata={"near_miss_document_ids": ["near-miss"]},
    )
    result = RAGResult(
        documents=[
            _doc("near-miss", "policy"),
            _doc("expected", "policy"),
        ],
        provider="mock",
        metadata={},
    )
    out = evaluate_retrieval_case(case, result=result)
    assert out.passed is True
    assert out.near_miss_violations == ["near-miss"]


def test_near_miss_no_expected_hit_any_retrieved_is_violation() -> None:
    case = RetrievalEvalCase(
        case_id="nm3",
        query="q",
        expected_document_ids=["missing"],
        top_k=5,
        metadata={"near_miss_document_ids": ["near-miss"]},
    )
    result = RAGResult(
        documents=[_doc("near-miss", "policy"), _doc("other", "policy")],
        provider="mock",
        metadata={},
    )
    out = evaluate_retrieval_case(case, result=result)
    assert out.passed is False
    assert out.near_miss_violations == ["near-miss"]


def test_near_miss_invalid_metadata_no_violation() -> None:
    case = RetrievalEvalCase(
        case_id="nm4",
        query="q",
        expected_document_ids=["expected"],
        top_k=5,
        metadata={"near_miss_document_ids": "not-a-list"},
    )
    result = RAGResult(
        documents=[_doc("wrong", "policy"), _doc("expected", "policy")],
        provider="mock",
        metadata={},
    )
    out = evaluate_retrieval_case(case, result=result)
    assert out.near_miss_document_ids == []
    assert out.near_miss_violations == []


def test_report_aggregates_near_miss_counts_and_case_ids() -> None:
    cases = [
        RetrievalEvalCase(
            case_id="agg-a",
            query="q1",
            expected_document_ids=["good"],
            top_k=3,
            metadata={"near_miss_document_ids": ["bad"]},
        ),
        RetrievalEvalCase(
            case_id="agg-b",
            query="q2",
            expected_document_ids=["good2"],
            top_k=3,
            metadata={"near_miss_document_ids": ["bad2"]},
        ),
    ]

    def retrieve_fn(query: str, top_k: int) -> RAGResult:
        if query == "q1":
            return RAGResult(
                documents=[_doc("bad", "policy"), _doc("good", "policy")],
                provider="mock",
                metadata={},
            )
        return RAGResult(documents=[_doc("good2", "policy")], provider="mock", metadata={})

    report = evaluate_retrieval_cases(cases, retrieve_fn=retrieve_fn)
    assert report.near_miss_violation_count == 1
    assert report.cases_with_near_miss_violations == ["agg-a"]
