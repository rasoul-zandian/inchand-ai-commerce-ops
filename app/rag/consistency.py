"""Offline consistency checks between corpus manifest and retrieval eval cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.rag.corpus_manifest import CorpusManifest, load_corpus_manifest
from app.rag.evaluation import RetrievalEvalCase, load_vendor_ticket_eval_cases_from_file

_DEFAULT_VENDOR_TICKET_MANIFEST = (
    Path(__file__).resolve().parents[2] / "corpus" / "vendor_ticket" / "manifest.json"
)


class CorpusEvalConsistencyIssue(BaseModel):
    """Single mismatch between an eval case and the corpus manifest."""

    issue_type: str
    message: str
    case_id: str | None = None
    document_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CorpusEvalConsistencyReport(BaseModel):
    """Aggregate result of a manifest vs eval cross-check."""

    passed: bool
    manifest_document_count: int
    eval_case_count: int
    issue_count: int
    issues: list[CorpusEvalConsistencyIssue]
    metadata: dict[str, Any] = Field(default_factory=dict)


def check_corpus_eval_consistency(
    *,
    manifest: CorpusManifest,
    eval_cases: list[RetrievalEvalCase],
) -> CorpusEvalConsistencyReport:
    """Ensure eval expected ids exist in the manifest and required source types match.

    For each case, ``required_source_types`` must be covered by the ``source_type`` values of
    that case's expected documents only. Issues are emitted in deterministic order.
    """
    manifest_ids = {doc.document_id for doc in manifest.documents}
    manifest_by_id = {doc.document_id: doc for doc in manifest.documents}
    issues: list[CorpusEvalConsistencyIssue] = []

    for case in eval_cases:
        for expected_id in case.expected_document_ids:
            if expected_id not in manifest_ids:
                issues.append(
                    CorpusEvalConsistencyIssue(
                        issue_type="missing_expected_document",
                        message="Eval case references document_id not present in corpus manifest.",
                        case_id=case.case_id,
                        document_id=expected_id,
                        metadata={},
                    )
                )

        expected_document_ids = list(case.expected_document_ids)
        expected_document_source_types: list[str | None] = []
        for eid in expected_document_ids:
            if eid in manifest_by_id:
                expected_document_source_types.append(manifest_by_id[eid].source_type)
            else:
                expected_document_source_types.append(None)

        covered_types = {t for t in expected_document_source_types if t is not None}

        seen_required: set[str] = set()
        for req in case.required_source_types:
            if req in seen_required:
                continue
            seen_required.add(req)
            if req not in covered_types:
                issues.append(
                    CorpusEvalConsistencyIssue(
                        issue_type="missing_required_source_type",
                        message=(
                            "Eval case requires source_type not covered by "
                            "its expected corpus documents."
                        ),
                        case_id=case.case_id,
                        document_id=None,
                        metadata={
                            "required_source_type": req,
                            "expected_document_ids": expected_document_ids,
                            "expected_document_source_types": expected_document_source_types,
                        },
                    )
                )

    meta = {
        "workflow_type": manifest.workflow_type,
        "manifest_version": manifest.manifest_version,
        "locale": manifest.locale,
    }
    return CorpusEvalConsistencyReport(
        passed=len(issues) == 0,
        manifest_document_count=len(manifest.documents),
        eval_case_count=len(eval_cases),
        issue_count=len(issues),
        issues=issues,
        metadata=meta,
    )


def check_default_vendor_ticket_corpus_eval_consistency() -> CorpusEvalConsistencyReport:
    """Load default vendor-ticket manifest and eval file, then run consistency check."""
    manifest = load_corpus_manifest(_DEFAULT_VENDOR_TICKET_MANIFEST)
    cases = load_vendor_ticket_eval_cases_from_file(None)
    return check_corpus_eval_consistency(manifest=manifest, eval_cases=cases)


def assert_corpus_eval_consistency(report: CorpusEvalConsistencyReport) -> None:
    """Raise ``AssertionError`` with a short summary when ``report.passed`` is false."""
    if report.passed:
        return
    lines = [
        (
            f"- {issue.issue_type} case_id={issue.case_id!r} "
            f"document_id={issue.document_id!r}: {issue.message}"
        )
        for issue in report.issues
    ]
    body = "\n".join(lines) if lines else "(no issue details)"
    raise AssertionError(f"Corpus/eval consistency failed ({report.issue_count} issue(s)):\n{body}")
