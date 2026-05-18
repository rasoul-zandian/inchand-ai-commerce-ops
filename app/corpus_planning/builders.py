"""Build pilot corpus planning metadata (no corpus files or vector operations)."""

from __future__ import annotations

from app.corpus_planning.models import PilotCorpusPlan, PilotCorpusStatus


def build_pilot_corpus_plan(
    *,
    corpus_id: str,
    source_batch_id: str,
    candidate_record_count: int,
    approved_record_count: int = 0,
    blocked_record_count: int = 0,
    privacy_review_completed: bool = False,
    replay_review_completed: bool = False,
    status: PilotCorpusStatus | None = None,
    notes: str | None = None,
) -> PilotCorpusPlan:
    """Create a planning-only pilot corpus plan from aggregate batch metadata."""
    resolved_status = status
    if resolved_status is None:
        if not privacy_review_completed or not replay_review_completed:
            resolved_status = PilotCorpusStatus.REVIEW_REQUIRED
        elif approved_record_count > 0:
            resolved_status = PilotCorpusStatus.APPROVED_FOR_BUILD
        else:
            resolved_status = PilotCorpusStatus.PLANNED

    return PilotCorpusPlan(
        corpus_id=corpus_id,
        source_batch_id=source_batch_id,
        candidate_record_count=candidate_record_count,
        approved_record_count=approved_record_count,
        blocked_record_count=blocked_record_count,
        privacy_review_completed=privacy_review_completed,
        replay_review_completed=replay_review_completed,
        status=resolved_status,
        notes=notes,
    )


def corpus_plan_ready_for_build(plan: PilotCorpusPlan) -> bool:
    """True only when governance gates are satisfied and status allows build."""
    return (
        plan.privacy_review_completed
        and plan.replay_review_completed
        and plan.status == PilotCorpusStatus.APPROVED_FOR_BUILD
    )
