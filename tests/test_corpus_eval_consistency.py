"""Tests for corpus manifest vs retrieval eval consistency guard."""

from __future__ import annotations

import pytest
from app.rag.consistency import (
    assert_corpus_eval_consistency,
    check_corpus_eval_consistency,
    check_default_vendor_ticket_corpus_eval_consistency,
)
from app.rag.corpus_manifest import CorpusManifest, CorpusManifestDocument
from app.rag.evaluation import RetrievalEvalCase


def test_default_vendor_ticket_consistency_passes() -> None:
    report = check_default_vendor_ticket_corpus_eval_consistency()
    assert report.passed is True
    assert report.issue_count == 0
    assert report.manifest_document_count == 5
    assert report.eval_case_count == 15
    assert report.metadata.get("workflow_type") == "vendor_ticket"
    assert report.metadata.get("manifest_version") == "1"
    assert report.metadata.get("locale") == "fa-IR"


def test_required_source_type_covered_by_expected_documents_passes() -> None:
    manifest = CorpusManifest(
        manifest_version="1",
        workflow_type="vendor_ticket",
        locale="fa-IR",
        documents=[
            CorpusManifestDocument(
                document_id="d1",
                source_type="policy",
                path="a.txt",
                title="t1",
                metadata={},
            ),
            CorpusManifestDocument(
                document_id="d2",
                source_type="approved_pattern",
                path="b.txt",
                title="t2",
                metadata={},
            ),
        ],
    )
    cases = [
        RetrievalEvalCase(
            case_id="ok",
            query="q",
            expected_document_ids=["d1", "d2"],
            required_source_types=["policy", "approved_pattern"],
            top_k=5,
        )
    ]
    report = check_corpus_eval_consistency(manifest=manifest, eval_cases=cases)
    assert report.passed is True
    assert report.issue_count == 0


def test_required_source_type_not_covered_creates_issue() -> None:
    manifest = CorpusManifest(
        manifest_version="1",
        workflow_type="vendor_ticket",
        locale="fa-IR",
        documents=[
            CorpusManifestDocument(
                document_id="d1",
                source_type="policy",
                path="a.txt",
                title="t1",
                metadata={},
            ),
            CorpusManifestDocument(
                document_id="d2",
                source_type="policy",
                path="b.txt",
                title="t2",
                metadata={},
            ),
        ],
    )
    cases = [
        RetrievalEvalCase(
            case_id="bad-types",
            query="q",
            expected_document_ids=["d1", "d2"],
            required_source_types=["policy", "style_guide"],
            top_k=5,
        )
    ]
    report = check_corpus_eval_consistency(manifest=manifest, eval_cases=cases)
    assert report.passed is False
    assert report.issue_count == 1
    issue = report.issues[0]
    assert issue.issue_type == "missing_required_source_type"
    assert issue.case_id == "bad-types"
    assert issue.document_id is None
    assert issue.metadata["required_source_type"] == "style_guide"
    assert issue.metadata["expected_document_ids"] == ["d1", "d2"]
    assert issue.metadata["expected_document_source_types"] == ["policy", "policy"]


def test_missing_document_and_missing_source_type_both_reported() -> None:
    manifest = CorpusManifest(
        manifest_version="1",
        workflow_type="vendor_ticket",
        locale="fa-IR",
        documents=[
            CorpusManifestDocument(
                document_id="real",
                source_type="policy",
                path="r.txt",
                title="t",
                metadata={},
            )
        ],
    )
    cases = [
        RetrievalEvalCase(
            case_id="combo",
            query="q",
            expected_document_ids=["ghost", "real"],
            required_source_types=["policy", "style_guide"],
            top_k=5,
        )
    ]
    report = check_corpus_eval_consistency(manifest=manifest, eval_cases=cases)
    assert report.passed is False
    assert report.issue_count == 2
    assert report.issues[0].issue_type == "missing_expected_document"
    assert report.issues[0].document_id == "ghost"
    assert report.issues[1].issue_type == "missing_required_source_type"
    assert report.issues[1].metadata["required_source_type"] == "style_guide"
    assert report.issues[1].metadata["expected_document_source_types"] == [None, "policy"]


def test_duplicate_required_source_types_single_issue() -> None:
    manifest = CorpusManifest(
        manifest_version="1",
        workflow_type="vendor_ticket",
        locale="fa-IR",
        documents=[
            CorpusManifestDocument(
                document_id="d1",
                source_type="policy",
                path="a.txt",
                title="t",
                metadata={},
            ),
        ],
    )
    cases = [
        RetrievalEvalCase(
            case_id="dup-req",
            query="q",
            expected_document_ids=["d1"],
            required_source_types=["style_guide", "style_guide", "style_guide"],
            top_k=5,
        )
    ]
    report = check_corpus_eval_consistency(manifest=manifest, eval_cases=cases)
    assert report.issue_count == 1
    assert report.issues[0].issue_type == "missing_required_source_type"


def test_missing_expected_document_creates_issue() -> None:
    manifest = CorpusManifest(
        manifest_version="1",
        workflow_type="vendor_ticket",
        locale="fa-IR",
        documents=[
            CorpusManifestDocument(
                document_id="only-one",
                source_type="policy",
                path="p.txt",
                title="t",
                metadata={},
            )
        ],
    )
    cases = [
        RetrievalEvalCase(
            case_id="c1",
            query="q",
            expected_document_ids=["only-one", "ghost-id"],
            top_k=5,
        )
    ]
    report = check_corpus_eval_consistency(manifest=manifest, eval_cases=cases)
    assert report.passed is False
    assert report.issue_count == 1
    assert report.manifest_document_count == 1
    assert report.eval_case_count == 1
    assert report.issues[0].issue_type == "missing_expected_document"
    assert report.issues[0].case_id == "c1"
    assert report.issues[0].document_id == "ghost-id"


def test_assert_corpus_eval_consistency_raises_on_failure() -> None:
    manifest = CorpusManifest(
        manifest_version="1",
        workflow_type="w",
        locale="fa-IR",
        documents=[
            CorpusManifestDocument(
                document_id="a",
                source_type="policy",
                path="a.txt",
                title="t",
                metadata={},
            )
        ],
    )
    cases = [RetrievalEvalCase(case_id="x", query="q", expected_document_ids=["missing"], top_k=2)]
    report = check_corpus_eval_consistency(manifest=manifest, eval_cases=cases)
    with pytest.raises(AssertionError, match="missing_expected_document"):
        assert_corpus_eval_consistency(report)


def test_assert_corpus_eval_consistency_succeeds_when_passed() -> None:
    report = check_default_vendor_ticket_corpus_eval_consistency()
    assert_corpus_eval_consistency(report)
