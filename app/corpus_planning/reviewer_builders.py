"""Build reviewer sign-off records and evaluate corpus readiness gates."""

from __future__ import annotations

from app.corpus_planning.reviewer_models import (
    ReviewerChecklistItem,
    ReviewerChecklistResult,
    ReviewerDecision,
    ReviewerRole,
    ReviewerSignoffRecord,
)

_DEFAULT_CHECKLIST: tuple[ReviewerChecklistItem, ...] = (
    ReviewerChecklistItem.NO_RAW_PII_VISIBLE,
    ReviewerChecklistItem.ANONYMIZATION_VERIFIED,
    ReviewerChecklistItem.RETRIEVAL_SAFE,
    ReviewerChecklistItem.GOVERNANCE_APPROVED,
    ReviewerChecklistItem.CORPUS_SCOPE_VALIDATED,
)

_BLOCKING_DECISIONS = frozenset(
    {
        ReviewerDecision.REJECTED,
        ReviewerDecision.NEEDS_REDACTION,
        ReviewerDecision.ESCALATE,
    }
)


def build_default_reviewer_checklist(
    *,
    passed: bool = False,
) -> list[ReviewerChecklistResult]:
    """Return the standard checklist with deterministic default pass/fail."""
    return [
        ReviewerChecklistResult(item=item, passed=passed, notes=None) for item in _DEFAULT_CHECKLIST
    ]


def build_signoff_record(
    *,
    signoff_id: str,
    source_batch_id: str,
    reviewer_role: ReviewerRole,
    reviewer_id: str,
    decision: ReviewerDecision,
    checklist_results: list[ReviewerChecklistResult] | None = None,
    privacy_review_completed: bool,
    replay_review_completed: bool,
    approved_record_count: int = 0,
    signed_at_utc: str | None = None,
) -> ReviewerSignoffRecord:
    """Create a human reviewer sign-off record (planning metadata only)."""
    resolved_checklist = checklist_results or build_default_reviewer_checklist()
    return ReviewerSignoffRecord(
        signoff_id=signoff_id,
        source_batch_id=source_batch_id,
        reviewer_role=reviewer_role,
        reviewer_id=reviewer_id,
        decision=decision,
        checklist_results=resolved_checklist,
        privacy_review_completed=privacy_review_completed,
        replay_review_completed=replay_review_completed,
        approved_record_count=approved_record_count,
        signed_at_utc=signed_at_utc,
    )


def corpus_ready_after_signoff(record: ReviewerSignoffRecord) -> bool:
    """True only when replay/privacy gates and human approval are all satisfied."""
    if not record.replay_review_completed or not record.privacy_review_completed:
        return False
    if record.decision in _BLOCKING_DECISIONS:
        return False
    if record.decision != ReviewerDecision.APPROVED:
        return False
    if record.requires_escalation:
        return False
    if not record.all_checklist_passed:
        return False
    return True
