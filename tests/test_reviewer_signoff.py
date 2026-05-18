"""Tests for human reviewer sign-off workflow (no corpus build or indexing)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.corpus_planning.reviewer_builders import (
    build_default_reviewer_checklist,
    build_signoff_record,
    corpus_ready_after_signoff,
)
from app.corpus_planning.reviewer_models import (
    ReviewerChecklistItem,
    ReviewerChecklistResult,
    ReviewerDecision,
    ReviewerRole,
    ReviewerSignoffRecord,
)
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SIGNOFF_DOC = _REPO_ROOT / "docs" / "operations" / "reviewer_signoff_workflow.md"
_PILOT_CORPUS_DIR = _REPO_ROOT / "corpus" / "vendor_ticket_real_pilot"


def _passed_checklist() -> list[ReviewerChecklistResult]:
    return [
        ReviewerChecklistResult(item=item, passed=True, notes=None)
        for item in ReviewerChecklistItem
    ]


def _base_signoff_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "signoff_id": "signoff_replay166_privacy_001",
        "source_batch_id": "replay_166",
        "reviewer_role": ReviewerRole.PRIVACY_REVIEWER,
        "reviewer_id": "reviewer_ops_01",
        "checklist_results": _passed_checklist(),
        "privacy_review_completed": True,
        "replay_review_completed": True,
        "approved_record_count": 20,
        "signed_at_utc": "2026-05-16T12:00:00Z",
    }
    base.update(overrides)
    return base


def test_approved_signoff_passes_readiness() -> None:
    record = build_signoff_record(
        **_base_signoff_kwargs(),
        decision=ReviewerDecision.APPROVED,
    )
    assert corpus_ready_after_signoff(record) is True


@pytest.mark.parametrize(
    "decision",
    [
        ReviewerDecision.REJECTED,
        ReviewerDecision.NEEDS_REDACTION,
        ReviewerDecision.ESCALATE,
    ],
)
def test_blocking_decisions_fail_readiness(decision: ReviewerDecision) -> None:
    record = build_signoff_record(
        **_base_signoff_kwargs(),
        decision=decision,
    )
    assert corpus_ready_after_signoff(record) is False


def test_incomplete_checklist_fails_validation() -> None:
    partial = [
        ReviewerChecklistResult(
            item=ReviewerChecklistItem.NO_RAW_PII_VISIBLE,
            passed=True,
        )
    ]
    with pytest.raises(ValidationError, match="missing required checklist"):
        build_signoff_record(
            **_base_signoff_kwargs(checklist_results=partial),
            decision=ReviewerDecision.APPROVED,
        )


def test_approved_with_failed_checklist_item_fails_validation() -> None:
    checklist = _passed_checklist()
    checklist[0] = ReviewerChecklistResult(
        item=ReviewerChecklistItem.NO_RAW_PII_VISIBLE,
        passed=False,
    )
    with pytest.raises(ValidationError, match="approved decision requires"):
        build_signoff_record(
            **_base_signoff_kwargs(checklist_results=checklist),
            decision=ReviewerDecision.APPROVED,
        )


def test_missing_replay_or_privacy_gate_fails_readiness() -> None:
    record = build_signoff_record(
        **_base_signoff_kwargs(privacy_review_completed=False),
        decision=ReviewerDecision.APPROVED,
    )
    assert corpus_ready_after_signoff(record) is False


def test_validation_errors_on_unsafe_notes_and_ids() -> None:
    with pytest.raises(ValidationError, match="single-line"):
        ReviewerChecklistResult(
            item=ReviewerChecklistItem.NO_RAW_PII_VISIBLE,
            passed=True,
            notes="line one\nline two",
        )

    with pytest.raises(ValidationError, match="whitespace"):
        ReviewerSignoffRecord(
            signoff_id="bad id",
            source_batch_id="replay_166",
            reviewer_role=ReviewerRole.PRIVACY_REVIEWER,
            reviewer_id="rev1",
            decision=ReviewerDecision.APPROVED,
            checklist_results=_passed_checklist(),
            privacy_review_completed=True,
            replay_review_completed=True,
        )

    with pytest.raises(ValidationError):
        build_signoff_record(
            signoff_id="",
            source_batch_id="replay_166",
            reviewer_role=ReviewerRole.PRIVACY_REVIEWER,
            reviewer_id="rev1",
            decision=ReviewerDecision.APPROVED,
            checklist_results=_passed_checklist(),
            privacy_review_completed=True,
            replay_review_completed=True,
        )


def test_default_checklist_starts_unpassed() -> None:
    checklist = build_default_reviewer_checklist()
    assert len(checklist) == len(ReviewerChecklistItem)
    assert all(not item.passed for item in checklist)


def test_reviewer_signoff_workflow_doc_exists() -> None:
    text = _SIGNOFF_DOC.read_text(encoding="utf-8")
    assert "Reviewer Sign-off Workflow" in text
    assert "corpus_ready_after_signoff" in text
    assert "no_raw_pii_visible" in text
    assert "Human approval only" in text or "human-only" in text.lower()
    assert "pgvector" in text.lower()
    assert "embeddings" in text.lower()


@pytest.mark.skipif(
    _PILOT_CORPUS_DIR.exists(),
    reason="local pilot corpus present after controlled build",
)
def test_no_pilot_corpus_directory_created() -> None:
    assert not _PILOT_CORPUS_DIR.exists()
