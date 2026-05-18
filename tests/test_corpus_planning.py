"""Tests for pilot corpus planning contracts (no indexing or embeddings)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.corpus_planning.builders import build_pilot_corpus_plan, corpus_plan_ready_for_build
from app.corpus_planning.models import PilotCorpusPlan, PilotCorpusStatus
from pydantic import ValidationError

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PILOT_PLANNING_DOC = _REPO_ROOT / "docs" / "operations" / "pilot_corpus_planning.md"


def test_pilot_corpus_plan_count_validation() -> None:
    plan = build_pilot_corpus_plan(
        corpus_id="vendor_ticket_real_pilot_v1",
        source_batch_id="replay_166",
        candidate_record_count=166,
        approved_record_count=20,
        blocked_record_count=28,
    )
    assert plan.approved_record_count == 20
    assert plan.blocked_record_count == 28

    with pytest.raises(ValidationError):
        PilotCorpusPlan(
            corpus_id="x",
            source_batch_id="batch",
            candidate_record_count=10,
            approved_record_count=11,
            blocked_record_count=0,
        )

    with pytest.raises(ValidationError):
        PilotCorpusPlan(
            corpus_id="x",
            source_batch_id="batch",
            candidate_record_count=10,
            approved_record_count=6,
            blocked_record_count=6,
        )


def test_ready_for_build_requires_all_gates() -> None:
    ready_plan = build_pilot_corpus_plan(
        corpus_id="vendor_ticket_real_pilot_v1",
        source_batch_id="replay_166",
        candidate_record_count=166,
        approved_record_count=15,
        privacy_review_completed=True,
        replay_review_completed=True,
        status=PilotCorpusStatus.APPROVED_FOR_BUILD,
    )
    assert corpus_plan_ready_for_build(ready_plan) is True

    missing_privacy = ready_plan.model_copy(update={"privacy_review_completed": False})
    assert corpus_plan_ready_for_build(missing_privacy) is False

    wrong_status = ready_plan.model_copy(update={"status": PilotCorpusStatus.BLOCKED})
    assert corpus_plan_ready_for_build(wrong_status) is False


def test_blocked_and_review_required_states() -> None:
    blocked = build_pilot_corpus_plan(
        corpus_id="pilot",
        source_batch_id="replay_50",
        candidate_record_count=50,
        blocked_record_count=50,
        status=PilotCorpusStatus.BLOCKED,
    )
    assert blocked.status == PilotCorpusStatus.BLOCKED
    assert corpus_plan_ready_for_build(blocked) is False

    review = build_pilot_corpus_plan(
        corpus_id="pilot",
        source_batch_id="replay_166",
        candidate_record_count=166,
        privacy_review_completed=False,
        replay_review_completed=True,
    )
    assert review.status == PilotCorpusStatus.REVIEW_REQUIRED
    assert corpus_plan_ready_for_build(review) is False


def test_pilot_corpus_planning_doc_governance() -> None:
    text = _PILOT_PLANNING_DOC.read_text(encoding="utf-8")
    assert "Pilot Corpus Planning" in text
    assert "## Preconditions" in text
    assert "## Corpus governance rules" in text
    assert "vendor_ticket_real_pilot" in text
    assert "not_started" in text
    assert "pgvector" in text.lower()
    assert "embeddings" in text.lower()
    assert "no raw" in text.lower() or "No raw" in text
    assert "privacy review" in text.lower()
    assert "10" in text and "25" in text


def test_planning_doc_excludes_indexing_execution() -> None:
    text = _PILOT_PLANNING_DOC.read_text(encoding="utf-8")
    assert "Planning only" in text or "planning only" in text
    assert "not created" in text.lower() or "not created in this planning" in text.lower()
    assert "ingestion jobs" in text.lower() or "no corpus directories" in text.lower()
