"""Auditable redraft artifact contract (hashes only; no draft persistence)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


def hash_redraft_content(text: str) -> str:
    """Deterministic SHA-256 hex digest for redraft audit and change tracking."""
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


class RedraftResult(BaseModel):
    """Compact auditable record of a controlled redraft (no full draft text stored)."""

    redraft_id: str
    source_action_id: str
    review_item_id: str
    created_at: datetime = Field(default_factory=_utc_now)
    previous_draft_hash: str
    redraft_hash: str
    operator_guidance: str
    requires_human_approval: bool = True
    qa_passed: bool | None = None
    qa_issue_count: int = 0
    llm_provider: str | None = None
    llm_model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def build_redraft_audit_metadata(result: RedraftResult) -> dict[str, Any]:
    """Compact audit slice for logs/responses (no draft bodies)."""
    return {
        "redraft_id": result.redraft_id,
        "source_action_id": result.source_action_id,
        "qa_passed": result.qa_passed,
        "qa_issue_count": result.qa_issue_count,
        "requires_human_approval": result.requires_human_approval,
        "previous_draft_hash": result.previous_draft_hash,
        "redraft_hash": result.redraft_hash,
    }


def build_redraft_result(
    *,
    source_action_id: str,
    review_item_id: str,
    previous_draft: str,
    redraft_text: str,
    operator_guidance: str,
    qa_passed: bool | None,
    qa_issue_count: int,
    llm_provider: str | None,
    llm_model: str | None,
    redraft_id: str | None = None,
    created_at: datetime | None = None,
) -> RedraftResult:
    """Materialize an auditable redraft artifact from controlled execution output."""
    result = RedraftResult(
        redraft_id=redraft_id or str(uuid.uuid4()),
        source_action_id=source_action_id,
        review_item_id=review_item_id,
        created_at=created_at or _utc_now(),
        previous_draft_hash=hash_redraft_content(previous_draft),
        redraft_hash=hash_redraft_content(redraft_text),
        operator_guidance=operator_guidance.strip(),
        requires_human_approval=True,
        qa_passed=qa_passed,
        qa_issue_count=qa_issue_count,
        llm_provider=llm_provider,
        llm_model=llm_model,
        metadata={},
    )
    result.metadata["audit"] = build_redraft_audit_metadata(result)
    return result
